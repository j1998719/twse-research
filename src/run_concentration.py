"""跑 [#20] 的集中度檢定。

[#20] 原本只跑穩懋一檔,而且用的是 [#19] 的 review 抓出問題**之前**的管線:
沒有去期間化,基準是每日再平衡指數對上買進持有的個股。那一輪唯一留下的
「線索」是 Gini 隨持有期單調變強(原始 p 從 0.975 降到 0.049)—— 而期間
叢聚正是會製造那種梯度的東西,所以必須用修好的機制重驗。

事前登記的組合和 [#20] 一樣:3 個指標 × 5 個持有期 = 15 個檢定,一次 BH
校正。改變的是樣本(穩懋一檔 → [#21] 的 20 檔系統性抽樣,因為穩懋是上櫃、
本地沒有價格)以及修好的報酬算法。

這仍然不是全市場研究,見 [#23]。
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from src.eventstats import (
    Observation,
    adjust,
    compare,
    demean_by_period,
    direction_split,
    effective_n,
    horizon_returns,
    non_overlapping,
)
from src.run_dispersion import HISTORY, PRICES, load_closes, load_weeks
from src.tdcc import effective_holders, gini, herfindahl


#: 集保資料日期到實際可交易之間的時滯
PUBLISH_LAG = timedelta(days=5)
#: 事前登記的持有期(幾個集保週次)
HORIZONS = (1, 2, 4, 8, 13)
#: 事前登記的三個指標
METRICS = ("HHI", "等效持有人數", "Gini")
#: 校正後低於這個才算顯著
ALPHA = 0.05


def metric_series(code: str) -> tuple[list[object], dict[str, list[float | None]]]:
    """一檔股票的週次日期,以及三個集中度指標的逐週值。"""
    weeks = sorted(load_weeks(code), key=lambda w: w.day)
    return [w.day for w in weeks], {
        "HHI": [herfindahl(w) for w in weeks],
        "等效持有人數": [effective_holders(w) for w in weeks],
        "Gini": [gini(w) for w in weeks],
    }


def main() -> int:
    """跑 15 個檢定,原始與去期間化各一輪。"""
    codes = sorted(p.stem for p in HISTORY.glob("*.json"))
    universe = set(
        pd.read_csv(PRICES, dtype={"code": str}, usecols=["code"])["code"].unique()
    )
    closes = load_closes(universe)
    print(f"樣本 {len(codes)} 檔,基準用 {len(closes)} 檔逐窗口買進持有等權")
    print(f"事件 = 指標比上一週上升。持有期 {HORIZONS} 個集保週次\n")

    pooled: dict[tuple[str, int], list[Observation]] = {
        (m, h): [] for m in METRICS for h in HORIZONS
    }
    for code in codes:
        series = closes.get(code)
        if not series:
            continue
        days, metrics = metric_series(code)
        for horizon in HORIZONS:
            rets = horizon_returns(days, series, closes, horizon, PUBLISH_LAG)  # type: ignore[arg-type]
            for name in METRICS:
                rising, falling = direction_split(metrics[name])
                for group, is_event in ((rising, True), (falling, False)):
                    for i in non_overlapping(group, horizon):
                        value = rets[i]
                        if value is not None:
                            pooled[(name, horizon)].append(
                                Observation(
                                    code=code,
                                    period=days[i],
                                    excess=value,
                                    is_event=is_event,
                                )
                            )

    _report("原始(未去期間化)", pooled, demean=False)
    _report("去期間化後 —— 這是主要結果", pooled, demean=True)
    _print_periods(pooled)
    return 0


def _report(
    title: str,
    pooled: dict[tuple[str, int], list[Observation]],
    *,
    demean: bool,
) -> None:
    """跑一輪 15 個檢定並印表。"""
    results = []
    for (name, horizon), items in pooled.items():
        use = demean_by_period(items) if demean else items
        got = compare(
            f"{name}/{horizon}週",
            [o.excess for o in use if o.is_event],
            [o.excess for o in use if not o.is_event],
            deduped=True,
        )
        if got is not None:
            results.append(got)
    print(f"\n=== {title} ===")
    print(
        f"{'指標':16}{'週':>3}{'事件n':>6}{'對照n':>6}"
        f"{'事件中位':>9}{'對照中位':>9}{'事件勝率':>9}{'對照勝率':>9}"
        f"{'原始p':>8}{'校正p':>8}"
    )
    scored = adjust(results)
    for got, adjusted in scored:
        label, weeks = got.name.rsplit("/", 1)
        mark = " <-" if adjusted < ALPHA else ""
        print(
            f"{label:16}{weeks.replace('週', ''):>3}{got.n_event:>6}"
            f"{got.n_control:>6}{got.median_event:>+8.1f}%"
            f"{got.median_control:>+8.1f}%{got.win_rate_event:>8.0%}"
            f"{got.win_rate_control:>9.0%}{got.pvalue:>8.3f}{adjusted:>8.3f}{mark}"
        )
    hits = sum(1 for _, a in scored if a < ALPHA)
    print(f"\n{len(results)} 個檢定,FDR 校正後顯著:{hits} 個")


def _print_periods(pooled: dict[tuple[str, int], list[Observation]]) -> None:
    """觀察筆數 vs 不同週次。20 檔共用同一組週次,筆數會高估獨立樣本數。"""
    print("\n事件組筆數 vs 不同週次(獨立樣本數更接近後者):")
    for (name, horizon), items in sorted(pooled.items()):
        events = [o for o in items if o.is_event]
        if events:
            print(
                f"  {name:14} {horizon:>2}週  {len(events):>3} 筆 / "
                f"{effective_n(events):>2} 週"
            )


if __name__ == "__main__":
    raise SystemExit(main())
