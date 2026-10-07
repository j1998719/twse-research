"""注意股階段佈局:5 個交易日內第 3 次被列注意,之後的走勢(#3)。

事件:src/events/notices.py(只用當天以前的公告)。下一個交易日收盤進場,持有
5 / 10 / 20 個交易日;報酬是 #22 框架的超額(扣成本、扣等權宇集、漲跌停順延、
還原除權息);流動性門檻 20 日成交金額中位數 ≥ 1,000 萬元。比較對象是安慰劑:
上市股票 × 同期隨機交易日,同門檻、同算法,Mann-Whitney 雙尾,3 個一次 BH。
形成 2020–2023,找到了的才在 2024 起驗證。⚠️ 只有上市:櫃買的注意股還沒接。

順便描述(不是檢定):事件後 10 個交易日內真的被處置的比例、隔幾天。

用法:.venv/bin/python -m src.run_notice_stage
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from src import cli
from src.disposition_study import trading_days
from src.events.notices import third_notice
from src.liquidity import MILLION, daily_value, level
from src.run_chip_signals import Excess, placebo_hits, scored, summarize
from src.run_wholemarket import closes_by_code
from src.universe import all_actions, all_prices, all_punishes


if TYPE_CHECKING:
    from collections.abc import Callable

    from src.events.chips import Hit

NOTICES = Path("data/out/notices.csv")
FORMATION_END = pd.Timestamp("2023-12-31")
HORIZONS = (5, 10, 20)
MIN_VALUE = 10
ALPHA = 0.05
#: 描述用:事件後幾個交易日內被處置
FOLLOW = 10


def disposed_after(
    hits: list[Hit], punishes: pd.DataFrame, days: pd.DatetimeIndex
) -> tuple[float, float]:
    """事件後 FOLLOW 個交易日內有處置公告的比例,以及公告在事件後第幾個交易日(中位數)。"""
    by_code: dict[str, list[pd.Timestamp]] = {}
    for code, when in zip(
        punishes.code.astype(str), pd.to_datetime(punishes.announced), strict=True
    ):
        by_code.setdefault(code, []).append(when)
    gaps = []
    for code, day in hits:
        at = int(days.searchsorted(day))
        later = [
            int(days.searchsorted(w)) - at for w in by_code.get(code, []) if w > day
        ]
        soon = [g for g in later if g <= FOLLOW]
        if soon:
            gaps.append(min(soon))
    share = len(gaps) / len(hits) if hits else 0.0
    return share, statistics.median(gaps) if gaps else float("nan")


def main() -> int:
    """3 個檢定、BH、跟安慰劑比、樣本外、被處置的比例。"""
    cli.no_args(__doc__)
    prices = all_prices()
    days = trading_days(prices)
    excess = Excess(closes_by_code(prices, all_actions()))
    value = daily_value(prices)
    market_of = {
        str(c): str(m) for c, m in zip(prices.code, prices.market, strict=True)
    }
    listed = sorted(
        {c for c, m in market_of.items() if m == "twse"} & set(excess.closes)
    )
    notices = pd.read_csv(NOTICES, dtype={"code": str}, parse_dates=["day"])
    hits = third_notice(notices, days)

    def liquid(code: str, day: pd.Timestamp) -> bool:
        got = level(value, code, day)
        return got is not None and got >= MIN_VALUE * MILLION

    def compare(
        keep: Callable[[str, pd.Timestamp], bool],
        span: tuple[pd.Timestamp, pd.Timestamp],
    ) -> list[tuple[int, dict[str, float], dict[str, float], float]]:
        base = placebo_hits(listed, days[(days >= span[0]) & (days <= span[1])])
        out = []
        for h in HORIZONS:
            ev, null = (
                scored(hits, h, days, excess, keep),
                scored(base, h, days, excess, keep),
            )
            p = float(
                stats.mannwhitneyu(
                    ev.excess, null.excess, alternative="two-sided"
                ).pvalue
            )
            out.append((h, summarize(ev, market_of), summarize(null, market_of), p))
        return out

    print(
        f"第 3 次注意的事件(第一次、未過門檻):{len(hits)} 筆;上市股票 {len(listed)} 檔\n"
    )
    first, last = days[0], days[-1]
    form = compare(
        lambda c, d: d <= FORMATION_END and liquid(c, d), (first, FORMATION_END)
    )
    q = multipletests([r[3] for r in form], method="fdr_bh")[1]
    found = []
    print("形成組(2020–2023),3 個檢定一次 BH:")
    for (h, s, s0, _), adj in zip(form, q, strict=True):
        apart = s["high"] < s0["low"] or s["low"] > s0["high"]
        ok = adj < ALPHA and apart
        found.append(ok)
        print(
            f"  持有 {h:>2} 日:事件 n={s['n']} 中位數 {s['median']:+.2f}% 勝率 {s['win']:.1f}%"
            f" CI [{s['low']:+.2f},{s['high']:+.2f}]  |  安慰劑 {s0['median']:+.2f}%"
            f" CI [{s0['low']:+.2f},{s0['high']:+.2f}]  |  差 {s['median'] - s0['median']:+.2f}"
            f"  BH p={adj:.4f}  {'找到了' if ok else '—'}"
        )
    if any(found):
        print("\n驗證組(2024 起,只看找到了的,不再校正):")
        later = compare(
            lambda c, d: d > FORMATION_END and liquid(c, d), (FORMATION_END, last)
        )
        for (h, s, s0, p), ok in zip(later, found, strict=True):
            if ok:
                print(
                    f"  持有 {h:>2} 日:事件 {s['median']:+.2f}%(n={s['n']})vs 安慰劑 {s0['median']:+.2f}%  差 {s['median'] - s0['median']:+.2f}  p={p:.4f}"
                )
    else:
        print("\n形成組沒有「找到了」,照登記不跑驗證組。")

    listed_punishes = all_punishes()
    listed_punishes = listed_punishes[
        (listed_punishes.market == "twse") & (listed_punishes.nth > 0)
    ]
    share, gap = disposed_after(hits, listed_punishes, days)
    print(
        f"\n描述:事件後 {FOLLOW} 個交易日內被處置 {share:.1%},處置公告在事件後第 {gap:.0f} 個交易日(中位數)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
