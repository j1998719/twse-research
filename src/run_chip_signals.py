"""籌碼面的全市場事件研究:跑 #60 事前登記的 7 個檢定。

四個假設(src/events/chips.py):投信連買 5 天、外資連買 5 天、股價漲而融資減、
券資比 ≥ 30% 而融券增加。事件日收盤之後才知道,所以下一個交易日收盤進場,
持有 5 / 20 個交易日。報酬 = 扣成本、扣同窗口全宇集等權買進持有,漲跌停順延、
還原除權息,跟 #22 框架的 window_excess 同一套定義。

判定(#60,第二輪開始前更正過):BH 校正後 p < 0.05、按月群集拔靴 CI 不跨 0、
上市上櫃方向一致,三個都要。形成期 2020-01 ~ 2023-12;找到的才在 2024-01 之後驗證。

⚠️ 跑完發現登記的「跟 0 比」是錯的虛無假設(#60 第二輪結果):超額報酬扣了成本、
而且單檔中位數天生低於全市場平均(右偏),隨機挑股票也是 5 日 −1.24%、20 日 −2.95%。
所以每個檢定旁邊一定要看安慰劑(同一段期間、同流動性門檻、隨機股票 × 隨機日,
同一套算法)和「跟安慰劑比」的 Mann-Whitney p。那一欄才有意義。

用法:.venv/bin/python -m src.run_chip_signals
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from src import cli
from src.disposition_study import trading_days
from src.events.chips import rally_on_margin_cut, short_squeeze, streak
from src.eventstats import clustered_ci, non_overlapping, tradable_on_or_after
from src.liquidity import MILLION, daily_value, level
from src.market import ROUND_TRIP_COST_PCT
from src.portfolio import adjusted_marks
from src.run_wholemarket import closes_by_code
from src.study import one_sample
from src.universe import all_actions, all_prices


if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from src.events.chips import Hit

OUT = "data/out"
#: 形成期最後一天(含);之後是樣本外
FORMATION_END = pd.Timestamp("2023-12-31")
#: 流動性門檻:事件日前 20 日成交金額中位數(百萬元)
MIN_VALUE = 10
#: 同期相關:事件日前幾個交易日的超額
PRE_DAYS = 5
ALPHA = 0.05
#: 算相關係數至少要幾筆
MIN_CORR = 3


#: 安慰劑抽幾筆、亂數種子(固定,結果可以重現)
PLACEBO_N = 6000
PLACEBO_SEED = 20261007


def placebo_hits(
    codes: list[str],
    days: pd.DatetimeIndex,
    n: int = PLACEBO_N,
    seed: int = PLACEBO_SEED,
) -> list[Hit]:
    """隨機股票 × 隨機交易日。走跟事件一樣的流動性門檻和算法,就是「沒有訊號」的基準。"""
    rng = random.Random(seed)  # noqa: S311 —— 研究用的可重現抽樣,不是加密
    pool = list(days[30:])
    return [(rng.choice(codes), rng.choice(pool)) for _ in range(n)]


@dataclass(frozen=True)
class Test:
    """登記的一個檢定:哪個假設、持有幾天。"""

    hypothesis: str
    horizon: int


TESTS = (
    Test("H1 投信連買 5 天", 5),
    Test("H1 投信連買 5 天", 20),
    Test("H2 外資連買 5 天", 5),
    Test("H2 外資連買 5 天", 20),
    Test("H3 漲 10% 而融資減 10%", 20),
    Test("H4 券資比 ≥ 30% 而融券增", 5),
    Test("H4 券資比 ≥ 30% 而融券增", 20),
)


class Excess:
    """window_excess 的快取版,數字跟它一樣(測試對照過)。

    個股那一邊照框架算(含漲跌停順延),等權基準按 (進場日, 出場日) 快取 ——
    幾萬個事件共用幾千組日期,每次都對 2,000 檔重算基準會跑好幾個小時。
    """

    def __init__(self, closes: dict[str, dict[date, float]]) -> None:
        """closes:每檔的(還原)收盤序列,同時也是等權基準的宇集。"""
        self.closes = closes
        self.bench: Callable[[date, date], float | None] = lru_cache(maxsize=None)(
            self._bench
        )

    def _bench(self, entry: date, exit_: date) -> float | None:
        rets = [
            s[exit_] / s[entry] - 1
            for s in self.closes.values()
            if entry in s and exit_ in s and s[entry] > 0
        ]
        return sum(rets) / len(rets) * 100 if rets else None

    def __call__(
        self, code: str, entry_day: date, exit_day: date, *, trade: bool = True
    ) -> float | None:
        """trade=False 是同期相關用的:不順延、不扣成本,只看價格怎麼走。"""
        series = self.closes.get(code)
        if series is None:
            return None
        if trade:
            entry = tradable_on_or_after(series, entry_day, buying=True)
            out = tradable_on_or_after(series, exit_day, buying=False)
        else:
            entry = (entry_day, series[entry_day]) if entry_day in series else None
            out = (exit_day, series[exit_day]) if exit_day in series else None
        if entry is None or out is None or entry[1] <= 0 or entry[0] > out[0]:
            return None
        bench = self.bench(entry[0], out[0])
        if bench is None:
            return None
        stock = (out[1] / entry[1] - 1) * 100
        return stock - (ROUND_TRIP_COST_PCT if trade else 0.0) - bench


def scored(
    hits: list[Hit],
    horizon: int,
    days: pd.DatetimeIndex,
    excess: Excess,
    keep: Callable[[str, pd.Timestamp], bool],
) -> pd.DataFrame:
    """事件 → 每筆的超額報酬(同一檔窗口不重疊)與事件前 5 日的同期超額。"""
    pos = {d: i for i, d in enumerate(days)}
    rows = []
    by_code: dict[str, list[int]] = {}
    for code, day in hits:
        if keep(code, day):
            by_code.setdefault(code, []).append(pos[day])
    for code, at in by_code.items():
        for i in non_overlapping(sorted(at), horizon):
            if i + 1 + horizon >= len(days) or i < PRE_DAYS:
                continue
            value = excess(code, days[i + 1].date(), days[i + 1 + horizon].date())
            if value is None:
                continue
            pre = excess(code, days[i - PRE_DAYS].date(), days[i].date(), trade=False)
            rows.append({"code": code, "day": days[i], "excess": value, "pre": pre})
    return pd.DataFrame(rows, columns=["code", "day", "excess", "pre"])


def summarize(frame: pd.DataFrame, market_of: dict[str, str]) -> dict[str, float]:
    """n、中位數、平均、勝率、Wilcoxon p、群集 CI、兩個市場各自的中位數、同期相關。"""
    values = frame.excess.astype(float)
    median, p = one_sample(values.tolist())
    low, high, _ = clustered_ci(values.tolist(), [f"{d:%Y-%m}" for d in frame.day])
    market = frame.code.map(market_of)
    pre = frame.pre.astype(float)
    both = pre.notna()
    corr = (
        float(np.corrcoef(pre[both], values[both])[0, 1])
        if both.sum() >= MIN_CORR
        else float("nan")
    )
    return {
        "n": len(values),
        "codes": frame.code.nunique(),
        "months": frame.day.dt.to_period("M").nunique(),
        "median": median,
        "mean": float(values.mean()),
        "win": float((values > 0).mean() * 100),
        "p": p,
        "low": low,
        "high": high,
        "twse": float(values[market == "twse"].median()),
        "otc": float(values[market == "otc"].median()),
        "pre": float(pre.median()),
        "corr": corr,
    }


def load_hits(
    prices: pd.DataFrame, actions: pd.DataFrame | None
) -> dict[str, list[Hit]]:
    """四個假設的事件(第一次;流動性門檻在 scored 那一層才套)。"""
    days = trading_days(prices)
    chips = pd.concat(
        [
            pd.read_csv(f"{OUT}/{name}", dtype={"code": str}, parse_dates=["day"])
            for name in ("chips.csv", "otc_chips.csv")
        ],
        ignore_index=True,
    )
    margin = pd.read_csv(f"{OUT}/margin.csv", dtype={"code": str}, parse_dates=["day"])
    margin_wide = margin.pivot_table(
        index="day", columns="code", values="margin"
    ).reindex(days)
    short_wide = margin.pivot_table(
        index="day", columns="code", values="short"
    ).reindex(days)
    adjusted = adjusted_marks(prices, actions).reindex(days)
    common = adjusted.columns.intersection(margin_wide.columns)
    return {
        "H1 投信連買 5 天": streak(chips, "trust", days),
        "H2 外資連買 5 天": streak(chips, "foreign", days),
        "H3 漲 10% 而融資減 10%": rally_on_margin_cut(
            adjusted[common], margin_wide[common]
        ),
        "H4 券資比 ≥ 30% 而融券增": short_squeeze(margin_wide, short_wide),
    }


def verdict(s: dict[str, float], q: float) -> bool:
    """「找到了」:BH p < 0.05、群集 CI 不跨 0、上市上櫃和全體方向一致(#60)。"""
    same_sign = np.sign(s["twse"]) == np.sign(s["otc"]) == np.sign(s["median"])
    return q < ALPHA and (s["low"] > 0 or s["high"] < 0) and bool(same_sign)


def line(test: Test, s: dict[str, float], q: float) -> str:
    """結果表的一列。"""
    return (
        f"{test.hypothesis} {test.horizon:>2}日".ljust(26)
        + f"{s['n']:>6}{s['codes']:>6}{s['months']:>4}{s['median']:>+8.2f}%"
        + f"{s['mean']:>+7.2f}%{s['win']:>6.1f}%"
        + f"  [{s['low']:+.2f},{s['high']:+.2f}]".ljust(20)
        + f"{s['twse']:>+7.2f}%{s['otc']:>+7.2f}%{q:>9.4f}{s['pre']:>+9.2f}%{s['corr']:>+7.2f}"
        + f"  {'找到了' if verdict(s, q) else '—'}"
    )


def main() -> int:
    """建事件、跑 7 個檢定、BH 校正、照登記的標準判定。"""
    cli.no_args(__doc__)
    prices = all_prices()
    days = trading_days(prices)
    excess = Excess(closes_by_code(prices, all_actions()))
    value = daily_value(prices)
    market_of = {
        str(c): str(m) for c, m in zip(prices.code, prices.market, strict=True)
    }
    hits = load_hits(prices, all_actions())
    for name, events in hits.items():
        print(f"{name}:全部 {len(events):,} 個事件(第一次、未過流動性門檻)")

    def liquid(code: str, day: pd.Timestamp) -> bool:
        got = level(value, code, day)
        return got is not None and got >= MIN_VALUE * MILLION

    summaries = [
        summarize(
            scored(
                hits[t.hypothesis],
                t.horizon,
                days,
                excess,
                lambda c, d: d <= FORMATION_END and liquid(c, d),
            ),
            market_of,
        )
        for t in TESTS
    ]
    adjusted_p = multipletests([s["p"] for s in summaries], method="fdr_bh")[1]
    form = lambda c, d: d <= FORMATION_END and liquid(c, d)  # noqa: E731
    base = placebo_hits(sorted(excess.closes), days[days <= FORMATION_END])
    placebo = {
        h: scored(base, h, days, excess, form) for h in {t.horizon for t in TESTS}
    }
    for h, frame in sorted(placebo.items()):
        s0 = summarize(frame, market_of)
        print(
            f"安慰劑 {h:>2} 日:n={s0['n']} 中位數 {s0['median']:+.2f}% 勝率 {s0['win']:.1f}%"
            f" CI [{s0['low']:+.2f},{s0['high']:+.2f}] —— 「跟 0 比」的基準其實在這裡"
        )
    print("\n形成期 2020-01 ~ 2023-12,7 個檢定一次 BH 校正")
    print(
        f"{'檢定':<26}{'n':>6}{'檔':>6}{'月':>4}{'中位數':>9}{'平均':>8}{'勝率':>7}"
        f"{'  群集 CI':<20}{'上市':>8}{'上櫃':>8}{'BH p':>9}{'事件前5日':>10}{'相關':>7}  判定"
    )
    for test, s, q in zip(TESTS, summaries, adjusted_p, strict=True):
        print(line(test, s, q))
    print("\n跟安慰劑比(同期、同門檻、隨機股票;Mann-Whitney,雙尾)—— 這一欄才有意義:")
    for test in TESTS:
        got = scored(hits[test.hypothesis], test.horizon, days, excess, form).excess
        null = placebo[test.horizon].excess
        p = float(stats.mannwhitneyu(got, null, alternative="two-sided").pvalue)
        print(
            f"  {test.hypothesis} {test.horizon:>2}日:中位數差"
            f" {got.median() - null.median():+.2f} 個百分點  p={p:.4f}"
        )

    winners = [
        t for t, s, q in zip(TESTS, summaries, adjusted_p, strict=True) if verdict(s, q)
    ]
    if not winners:
        print("\n沒有任何一個「找到了」。")
        return 0
    print("\n樣本外驗證(2024-01 起,只跑「找到了」的,不再校正):")
    for t in winners:
        frame = scored(
            hits[t.hypothesis],
            t.horizon,
            days,
            excess,
            lambda c, d: d > FORMATION_END and liquid(c, d),
        )
        s = summarize(frame, market_of)
        print(
            f"  {t.hypothesis} {t.horizon}日:n={s['n']} 中位數 {s['median']:+.2f}%"
            f" 勝率 {s['win']:.1f}% p={s['p']:.4f} CI [{s['low']:+.2f},{s['high']:+.2f}]"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
