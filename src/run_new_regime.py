"""新制(5 個營業日)處置的「公告後最早買」:跑 #65 事前登記的 2 個檢定。

2026-08-10 起處置只關 5 個營業日,出關前第 6 個交易日幾乎都是公告當天收盤 ——
那時還不知道會被處置。新制版的策略:公告後第一個交易日收盤買、出關前一天收盤賣
(跟網頁卡片的「公告後最早」同一個定義,build_report.earliest_buy)。

報酬照 #22 框架(還原除權息、漲跌停順延、扣來回成本、扣等權宇集)。
對照不跟 0 比(#60):每筆事件配 PLACEBO_K 檔隨機股票,同一個買賣日期、同一套算法,
「事件 − 安慰劑平均」做 Wilcoxon 符號秩、雙尾。

- N1:新制全部編號處置
- N2:新制第二次處置
兩個一起 BH。

用法:.venv/bin/python -m src.run_new_regime
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from src import cli
from src.disposition_study import trading_days
from src.run_chip_signals import Excess
from src.run_wholemarket import closes_by_code
from src.universe import all_actions, all_prices, all_punishes


if TYPE_CHECKING:
    from collections.abc import Sequence

#: 新制開始(這天以後開始的處置是 5 個營業日)
NEW_RULES = pd.Timestamp("2026-08-10")
SECOND = 2
#: 每筆事件配幾檔安慰劑、最多試幾次、亂數種子(固定,結果可以重現)
PLACEBO_K = 20
PLACEBO_TRIES = 200
PLACEBO_SEED = 20261007


def new_regime_events(punishes: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    """新制編號處置 → (代號, 第幾次, 買點, 賣點)。

    買點 = 公告日之後第一個交易日;賣點 = 出關日前一個交易日。買點不早於賣點、
    或還沒出關(賣點超過資料最後一天)的不算。
    """
    rows = []
    last = days.max()
    picked = punishes[
        (punishes.nth > 0) & (pd.to_datetime(punishes.start) >= NEW_RULES)
    ]
    for code, nth, announced, end in zip(
        picked.code, picked.nth, picked.announced, picked.end, strict=True
    ):
        at_release = int(days.searchsorted(pd.Timestamp(end), side="right"))
        at_buy = int(days.searchsorted(pd.Timestamp(announced), side="right"))
        if at_release >= len(days) or at_buy >= len(days):
            continue
        buy, sell = days[at_buy], days[at_release - 1]
        if buy < sell <= last:
            rows.append({"code": str(code), "nth": int(nth), "buy": buy, "sell": sell})
    return pd.DataFrame(rows, columns=["code", "nth", "buy", "sell"])


def paired_gaps(
    events: pd.DataFrame, excess: Excess, universe: Sequence[str], rng: random.Random
) -> pd.DataFrame:
    """每筆事件的超額、同日期隨機股票的平均超額、兩者的差。算不出來的不算。"""
    rows = []
    for code, nth, buy, sell in events.itertuples(index=False):
        got = excess(code, buy.date(), sell.date())
        if got is None:
            continue
        null: list[float] = []
        for _ in range(PLACEBO_TRIES):
            if len(null) == PLACEBO_K:
                break
            other = rng.choice(universe)
            if other == code:
                continue
            value = excess(other, buy.date(), sell.date())
            if value is not None:
                null.append(value)
        if not null:
            continue
        base = sum(null) / len(null)
        rows.append(
            {"code": code, "nth": nth, "event": got, "placebo": base, "gap": got - base}
        )
    return pd.DataFrame(rows, columns=["code", "nth", "event", "placebo", "gap"])


def main() -> int:
    """建事件、配安慰劑、2 個檢定一次 BH。"""
    cli.no_args(__doc__)
    prices = all_prices()
    days = trading_days(prices)
    excess = Excess(closes_by_code(prices, all_actions()))
    events = new_regime_events(all_punishes(), days)
    table = paired_gaps(
        events,
        excess,
        sorted(excess.closes),
        random.Random(PLACEBO_SEED),  # noqa: S311 —— 抽樣,不是密碼
    )
    print(f"新制編號處置:{len(events)} 筆,算得出報酬 {len(table)} 筆\n")
    tests = [("N1 全部編號處置", table), ("N2 第二次處置", table[table.nth == SECOND])]
    pvalues = [float(stats.wilcoxon(t.gap).pvalue) for _, t in tests]
    adjusted = multipletests(pvalues, method="fdr_bh")[1]
    for (name, t), p, q in zip(tests, pvalues, adjusted, strict=True):
        print(
            f"{name:<12} n={len(t):>3}  事件中位數 {t.event.median():+.2f}%"
            f"  安慰劑中位數 {t.placebo.median():+.2f}%  差的中位數 {t.gap.median():+.2f}"
            f"  差的平均 {t.gap.mean():+.2f}  勝過安慰劑 {(t.gap > 0).mean() * 100:.0f}%"
            f"  原始 p={p:.4f}  BH p={q:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
