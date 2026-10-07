"""除權息:跑 #28 事前登記的 3 個檢定。

錨點是除權息交易日 T(預告大約提前一到兩週,所以 T 事前知道)。報酬全部是還原版
(corporate_actions.csv,#59),股價用 long_prices(2016 起);#22 框架的超額(扣成本、
扣等權宇集、漲跌停順延);流動性門檻 20 日成交金額中位數 ≥ 1,000 萬元。

- H1 除息後回彈:T 收盤進、T+5 收盤出,事件 vs 同日安慰劑
- H2 除息前買盤:T−5 收盤進、T−1 收盤出,事件 vs 同日安慰劑
- H3 殖利率高 vs 低:T 收盤進、T+20 出,最高 1/3 vs 最低 1/3,按月去期間化

安慰劑跟事件**同一天**:從前後 20 個交易日都沒有除權息的股票裡隨機挑,季節自動對齊
(除權息 7 月一個月就 6,672 次)。Mann-Whitney 雙尾,3 個一次 BH。
形成 2016–2021,找到了的才在 2022 起驗證。

用法:.venv/bin/python -m src.run_dividends
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from src import cli
from src.liquidity import MILLION, daily_value, level
from src.run_chip_signals import Excess, scored, summarize
from src.run_limitups import Split, compare, line
from src.run_wholemarket import closes_by_code
from src.universe import all_actions


if TYPE_CHECKING:
    from collections.abc import Callable

    from src.events.chips import Hit

HISTORY = Path("data/out/long_prices.csv")
FORMATION_END = pd.Timestamp("2021-12-31")
MIN_VALUE = 10
ALPHA = 0.05
#: 安慰劑:前後幾個交易日不能有除權息、每個事件挑幾檔
CLEAR = 20
PER_EVENT = 3
SEED = 20261007
TERCILE = (1 / 3, 2 / 3)


def shifted(hits: list[Hit], days: pd.DatetimeIndex, offset: int) -> list[Hit]:
    """每個事件日往前(負)或往後移 offset 個交易日;超出範圍的丟掉。"""
    pos = {d: i for i, d in enumerate(days)}
    out = []
    for code, day in hits:
        at = pos[day] + offset
        if 0 <= at < len(days):
            out.append((code, days[at]))
    return out


def same_day_placebo(
    hits: list[Hit],
    pool: list[str],
    actions: dict[str, list[pd.Timestamp]],
    days: pd.DatetimeIndex,
    per_event: int = PER_EVENT,
    seed: int = SEED,
) -> list[Hit]:
    """每個事件日挑 per_event 檔「前後 CLEAR 個交易日都沒有除權息」的股票,同一天。"""
    rng = random.Random(seed)  # noqa: S311 —— 研究用的可重現抽樣,不是加密
    pos = {d: i for i, d in enumerate(days)}
    near: dict[str, set[int]] = {
        code: {pos[d] for d in ds if d in pos} for code, ds in actions.items()
    }
    out: list[Hit] = []
    for _, day in hits:
        at = pos[day]
        ok = [c for c in pool if not any(abs(at - p) <= CLEAR for p in near.get(c, ()))]
        out.extend((rng.choice(ok), day) for _ in range(per_event) if ok)
    return out


def load() -> tuple[
    pd.DatetimeIndex, Excess, pd.DataFrame, pd.DataFrame, dict[str, str]
]:
    """2016 起的長日線、超額報酬計算器(還原)、每日成交金額、除權息事件表、市場。"""
    prices = pd.read_csv(HISTORY, dtype={"code": str}, parse_dates=["day"])
    actions = all_actions()
    if actions is None:
        msg = "沒有 corporate_actions.csv,算不出還原報酬;先跑 fetch_actions"
        raise SystemExit(msg)
    days = pd.DatetimeIndex(sorted(prices.day.unique()))
    market_of = {
        str(c): str(m) for c, m in zip(prices.code, prices.market, strict=True)
    }
    return (
        days,
        Excess(closes_by_code(prices, actions)),
        daily_value(prices),
        actions,
        market_of,
    )


def dividend_events(
    actions: pd.DataFrame, days: pd.DatetimeIndex, priced: set[str]
) -> tuple[list[Hit], dict[Hit, float], dict[str, list[pd.Timestamp]]]:
    """(除息事件, 每個事件的殖利率 1 − 因子, 每檔所有除權息 / 減資日)。"""
    trading = set(days)
    div = actions[actions.kind.str.endswith("dividend")]
    events = [
        (str(c), pd.Timestamp(d))
        for c, d in zip(div.code, div.day, strict=True)
        if pd.Timestamp(d) in trading and str(c) in priced
    ]
    yields = {
        (str(c), pd.Timestamp(d)): 1 - float(f)
        for c, d, f in zip(div.code, div.day, div.factor, strict=True)
    }
    near: dict[str, list[pd.Timestamp]] = {}
    for c, d in zip(actions.code, actions.day, strict=True):
        near.setdefault(str(c), []).append(pd.Timestamp(d))
    return events, yields, near


def main() -> int:
    """3 個檢定、BH、同日安慰劑、樣本外。"""
    cli.no_args(__doc__)
    days, excess, value, actions, market_of = load()
    events, yields, near = dividend_events(actions, days, set(excess.closes))
    placebo = same_day_placebo(events, sorted(excess.closes), near, days)
    print(f"除權息事件 {len(events):,} 筆;同日安慰劑 {len(placebo):,} 筆\n")

    def liquid(code: str, day: pd.Timestamp) -> bool:
        got = level(value, code, day)
        return got is not None and got >= MIN_VALUE * MILLION

    def window(hits: list[Hit], offset: int, hold: int, late: bool) -> pd.DataFrame:
        """錨點 T 移到「進場前一天」(scored 在下一個交易日收盤進場)。"""
        keep: Callable[[str, pd.Timestamp], bool] = (
            (lambda c, d: d > FORMATION_END and liquid(c, d))
            if late
            else (lambda c, d: d <= FORMATION_END and liquid(c, d))
        )
        return scored(shifted(hits, days, offset - 1), hold, days, excess, keep)

    tests = {"H1 除息後回彈(T → T+5)": (0, 5), "H2 除息前買盤(T−5 → T−1)": (-5, 4)}

    def same_day(
        late: bool,
    ) -> list[tuple[str, dict[str, float], dict[str, float], float]]:
        out = []
        for name, (offset, hold) in tests.items():
            ev, null = (
                window(events, offset, hold, late),
                window(placebo, offset, hold, late),
            )
            p = float(
                stats.mannwhitneyu(
                    ev.excess, null.excess, alternative="two-sided"
                ).pvalue
            )
            out.append((name, summarize(ev, market_of), summarize(null, market_of), p))
        return out

    form = [y for (c, d), y in yields.items() if d <= FORMATION_END]
    lo, hi = (float(pd.Series(form).quantile(t)) for t in TERCILE)

    def h3(late: bool) -> Split:
        high = [h for h in events if yields.get(h, 0) >= hi]
        low = [h for h in events if yields.get(h, 1) <= lo]
        return compare(
            "H3 殖利率高 vs 低(T → T+20)", high, low, lambda hs: window(hs, 0, 20, late)
        )

    rows = same_day(late=False)
    third = h3(late=False)
    q = [
        float(x)
        for x in multipletests([r[3] for r in rows] + [third.p], method="fdr_bh")[1]
    ]
    print(f"形成組(2016–2021),3 個檢定一次 BH;殖利率三分位切點 {lo:.2%} / {hi:.2%}")
    found = []
    for (name, s, s0, _), adj in zip(rows, q[:2], strict=True):
        apart = s["high"] < s0["low"] or s["low"] > s0["high"]
        found.append(adj < ALPHA and apart)
        print(
            f"  {name}:事件 n={s['n']} {s['median']:+.2f}% CI [{s['low']:+.2f},{s['high']:+.2f}]"
            f"  |  同日安慰劑 n={s0['n']} {s0['median']:+.2f}% CI [{s0['low']:+.2f},{s0['high']:+.2f}]"
            f"  |  差 {s['median'] - s0['median']:+.2f}  BH p={adj:.4f}  {'找到了' if found[-1] else '—'}"
        )
    found.append(q[-1] < ALPHA)
    print(line(third, q[-1]) + ("  找到了" if found[-1] else ""))

    print("\n驗證組(2022 起;找到了的才算數,其他只看方向,判斷線索):")
    for (name, s, s0, p), (_, f0, f00, _), ok in zip(
        same_day(late=True), rows, found[:2], strict=True
    ):
        same = (s["median"] - s0["median"]) * (f0["median"] - f00["median"]) > 0
        print(
            f"  {name}:差 {s['median'] - s0['median']:+.2f}  p={p:.4f}  方向{'一致' if same else '相反'}{'(登記的驗證)' if ok else ''}"
        )
    later = h3(late=True)
    same = (later.med_a - later.med_b) * (third.med_a - third.med_b) > 0
    print(
        line(later, None)
        + f"  方向{'一致' if same else '相反'}{'(登記的驗證)' if found[-1] else ''}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
