"""用全市場(上市 + 上櫃)重跑 [#13] 的主要發現。

[#23]:原本只用上市的 1,166 次處置,而上櫃還有 1,819 次 —— 漏掉的比用到的多。
合併之後 2,985 次、乾淨樣本 2,368 筆。

上櫃是**完全獨立的樣本外複現**:假設成形的時候從來沒看過它。

用法:.venv/bin/python -m src.run_wholemarket
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
from src.market import index_series
from src.study import Window, one_sample, resolve_window
from src.universe import all_prices, all_punishes, summary


if TYPE_CHECKING:
    from datetime import date


#: [#13] 的主要發現:出關前六個交易日買、前一日賣
PRE_RELEASE = Window(entry=-6, exit=-1)
RAW = Path("data/raw/prices")
#: 少於這麼多筆就不報,算出來沒有意義
MIN_GROUP = 6


def closes_by_code(prices: pd.DataFrame) -> dict[str, dict[date, float]]:
    """每檔的收盤序列。逐窗口的等權基準要用它。"""
    out: dict[str, dict[date, float]] = {}
    for code, group in prices.groupby("code"):
        series = {
            day.date(): float(close)
            for day, close in zip(group.day, group.close, strict=True)
            if pd.notna(close) and close > 0
        }
        if series:
            out[str(code)] = series
    return out


def main() -> int:
    """跑全市場,並分市場報。"""
    cli.no_args(__doc__)
    prices = all_prices()
    punishes = all_punishes()
    if prices.empty or punishes.empty:
        print("沒有資料。先跑 src.fetch_prices 和 src.fetch_tpex")
        return 1
    facts = summary(prices, punishes)
    print(
        f"宇集 {facts['codes']} 檔 {facts['codes_by_market']}、"
        f"{facts['rows']:,} 列、{facts['span']}"
    )
    print(f"處置 {facts['events']} 次 {facts['events_by_market']}\n")

    runs = pre_release_run(
        punishes[punishes.nth > 0],
        prices,
        index_series(RAW),
        all_punishes=punishes,
    )
    events = [
        e
        for e in disposition_events(runs)
        if e.tags["truly_released"] and e.tags["has_excess"]
    ]
    days = sorted(day.date() for day in trading_days(prices))
    closes = closes_by_code(prices)
    # market 從**公告那一列**認,不是按代號查:轉上市的股票(6426、6446)
    # 在兩個市場都有處置公告,按代號查會讓它的上櫃事件全部被標成上市。
    # 這一欄正是這個模組說「一定要能分市場看」的那一欄,不能用錯的 join 湊
    market = {
        (str(row["code"]), pd.Timestamp(row["start"]).date()): str(row["market"])
        for row in punishes.to_dict("records")
    }

    # (市場, 舊基準超額, 新基準超額, 進場的年月 —— 拔靴的群集)
    rows: list[tuple[str, float, float, str]] = []
    for event in events:
        span = resolve_window(event, days, PRE_RELEASE)
        if span is None or span[0] <= event.knowable or event.code not in closes:
            continue
        got = window_excess(closes[event.code], closes, *span)
        if got is None:
            continue
        rows.append(
            (
                market.get((event.code, event.tags["start"]), "?"),  # type: ignore[arg-type]
                float(event.tags["old_excess"]),  # type: ignore[arg-type]
                got,
                f"{span[0]:%Y-%m}",
            )
        )

    print(f"乾淨樣本 {len(rows)} 筆")
    print("舊基準是市值加權的加權指數;新基準是全宇集逐窗口的等權買進持有\n")
    print(
        f"{'市場':6}{'n':>6}{'月':>4}{'舊中位':>10}{'新中位':>10}"
        f"{'勝率':>8}{'群集拔靴 95% CI':>20}{'≤0 比例':>9}"
    )
    for label in ("全部", "twse", "otc"):
        sub = [r for r in rows if label == "全部" or r[0] == label]
        if len(sub) < MIN_GROUP:
            continue
        old = [r[1] for r in sub]
        new = [r[2] for r in sub]
        median, _ = one_sample(new)
        win = sum(1 for v in new if v > 0) / len(new) * 100
        months = [r[3] for r in sub]
        low, high, nonpos = clustered_ci(new, months)
        print(
            f"{label:6}{len(sub):>6}{len(set(months)):>4}"
            f"{st.median(old):>+9.2f}%{median:>+9.2f}%"
            f"{win:>7.1f}%{f'[{low:+.2f}, {high:+.2f}]':>20}{nonpos:>8.1%}"
        )
    print(
        "\n信賴區間是按月重抽的群集拔靴,不是 Wilcoxon 的 p 值 —— 事件叢聚在"
        "同一段行情裡(2,265 筆只落在約 1,081 個買進日,最多 20 筆共用一天),"
        "\n把它們當獨立樣本會把 p 算得太小。「≤0 比例」是重抽中位數不為正的"
        "比例,比一個小 p 值誠實。"
    )
    print(
        "\n上櫃是獨立的樣本外複現 —— 假設成形時沒看過它。"
        "但滑價風險在上櫃更高:流動性較差,而處置期間是集合競價。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
