"""第二次處置 × 處置前流動性(#30、#31)。

原本的 run_chain_liquidity.py 在拿不到的機器上,這裡照 #31 的登記重做,
並重現 #30 那張表(816 筆第二次處置、W2≥200M 320 筆、中位數 +4.80%)。

報酬走 [#22] 的框架:出關前 6 日收盤買、前 1 日收盤賣,扣成本,再扣同窗口
全宇集等權買進持有。每一格報兩版:不順延(當初的算法,用來對照)與
漲跌停順延(現在的規則,#45、#58)。信賴區間是按月群集拔靴。

用法:.venv/bin/python -m src.run_chain_liquidity
"""

from __future__ import annotations

import statistics as st
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from src import cli
from src.disposition_study import pre_release_run, trading_days
from src.events.disposition import events as disposition_events
from src.eventstats import clustered_ci, window_excess
from src.liquidity import chain_levels
from src.market import index_series
from src.run_wholemarket import closes_by_code
from src.study import Window, resolve_window
from src.universe import all_actions, all_prices, all_punishes


if TYPE_CHECKING:
    from datetime import date

RAW = Path("data/raw/prices")
PRE_RELEASE = Window(entry=-6, exit=-1)
SECOND = 2
#: 門檻(百萬元),跟 #30 的表一樣
THRESHOLDS = (0, 50, 100, 200, 400)
#: 少於這麼多筆就不報中位數和 CI
MIN_GROUP = 6


def second_dispositions(prices: pd.DataFrame, punishes: pd.DataFrame) -> pd.DataFrame:
    """第二次處置,每一筆帶 W1、W2(百萬元)與兩版超額報酬。"""
    days = trading_days(prices)
    levels = chain_levels(punishes, prices, days)
    runs = pre_release_run(
        punishes[punishes.nth > 0], prices, index_series(RAW), all_punishes=punishes
    )
    events = {
        (e.code, e.tags["start"]): e
        for e in disposition_events(runs)
        if e.tags["truly_released"] and e.tags["nth"] == SECOND
    }
    calendar: list[date] = [d.date() for d in days]
    closes = closes_by_code(prices, all_actions())
    rows = []
    second = punishes[punishes.nth == SECOND]
    for row, (w1, w2) in zip(
        second.to_dict("records"),
        levels.loc[second.index].itertuples(index=False),
        strict=True,
    ):
        code = str(row["code"])
        event = events.get((code, pd.Timestamp(row["start"]).date()))
        if event is None or code not in closes:
            continue
        span = resolve_window(event, calendar, PRE_RELEASE)
        if span is None or span[0] <= event.knowable:
            continue
        rows.append(
            {
                "code": code,
                "month": f"{span[0]:%Y-%m}",
                "w1": w1,
                "w2": w2,
                "old": window_excess(closes[code], closes, *span, defer_limits=False),
                "new": window_excess(closes[code], closes, *span),
            }
        )
    return pd.DataFrame(rows)


def _cell(sub: pd.DataFrame, column: str) -> str:
    values = sub[column].dropna()
    if len(values) < MIN_GROUP:
        return f"{len(values):>4}  樣本太少"
    low, high, _ = clustered_ci(
        values.tolist(), sub.loc[values.index, "month"].tolist()
    )
    return (
        f"{len(values):>4} {st.median(values):+6.2f}% {(values > 0).mean() * 100:5.1f}%"
        f" [{low:+.2f},{high:+.2f}]"
    )


def main() -> int:
    """W1 / W2 各門檻下的 n、中位數、勝率、群集拔靴 CI。"""
    cli.no_args(__doc__)
    table = second_dispositions(all_prices(), all_punishes())
    print(f"第二次處置 {len(table)} 筆(真出關、事前可知)")
    print(
        f"W1 算得出來 {table.w1.notna().sum()} 筆、W2 算得出來 {table.w2.notna().sum()} 筆\n"
    )
    print(
        f"{'門檻':<10}{'n  中位數  勝率  CI(不順延,對照 #30)':<44}{'n  中位數  勝率  CI(順延)'}"
    )
    for var in ("w1", "w2"):
        for m in THRESHOLDS:
            sub = table[table[var] >= m] if m else table[table[var].notna()]
            label = f"{var.upper()}≥{m}M" if m else f"{var.upper()} 無"
            print(f"{label:<10}{_cell(sub, 'old'):<44}{_cell(sub, 'new')}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
