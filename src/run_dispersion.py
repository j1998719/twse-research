"""跑 [#19] 事前登記的出貨訊號檢定。

參數在 [#21] 的留言裡先寫死了:回看 8 週、回落 2 個百分點,持有期 4/8/13 週,
三個訊號定義 —— 合計 9 個檢定,一次 BH 校正。跑完不補測。

樣本是 [#21] 的 20 檔系統性抽樣。**這不是全市場研究**,是先導測試:集保
查詢頁一檔一週要兩個請求,全市場回溯要約 10 萬個請求([#23])。
"""

from __future__ import annotations

from src.dispersion import DROP_PP, LOOKBACK, signals, triggered
from src.eventdata import (
    PUBLISH_LAG,
    available_codes,
    load_closes,
    load_weeks,
)
from src.eventstats import (
    Comparison,
    Observation,
    adjust,
    compare,
    demean_by_period,
    effective_n,
    horizon_returns,
    non_overlapping,
)


#: 事前登記的持有期,單位是週。
#:
#: 注意這是「幾個集保週次」而不是固定天數:集保在農曆年那一週沒有資料
#: (2026-02-13 直接跳到 02-26),所以跨過那個缺口的窗口會多出一週 ——
#: 13 週的窗口有約三分之一實際是 98 天而不是 91 天。
HORIZONS = (4, 8, 13)
#: 事前登記的三個訊號
SIGNALS = ("big_rolled_over", "holders_peaked", "distributing")
#: 校正後低於這個才算顯著
ALPHA = 0.05
#: 一致性那一段至少要幾檔才值得印
MIN_STOCKS = 3


def main() -> int:
    """跑完 9 個檢定,把結果印出來。"""
    codes = available_codes()
    closes = load_closes()
    print(f"樣本 {len(codes)} 檔,基準用 {len(closes)} 檔逐窗口買進持有等權")
    print(f"回看 {LOOKBACK} 週、回落 {DROP_PP} 個百分點,持有期 {HORIZONS} 週\n")

    # (訊號, 持有期) -> 該組合的所有觀察
    pooled: dict[tuple[str, int], list[Observation]] = {
        (name, h): [] for name in SIGNALS for h in HORIZONS
    }

    for code in codes:
        series = closes.get(code)
        if not series:
            print(f"  {code}: 沒有價格資料,跳過")
            continue
        sigs = signals(load_weeks(code))
        for horizon in HORIZONS:
            rets = horizon_returns(
                [s.day for s in sigs], series, closes, horizon, PUBLISH_LAG
            )
            for name in SIGNALS:
                fired = set(triggered(sigs, name))
                hit = [i for i, s in enumerate(sigs) if s in fired]
                miss = [i for i, s in enumerate(sigs) if s not in fired]
                for group, is_event in ((hit, True), (miss, False)):
                    for i in non_overlapping(group, horizon):
                        value = rets[i]
                        if value is not None:
                            pooled[(name, horizon)].append(
                                Observation(
                                    code=code,
                                    period=sigs[i].day,
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
    """跑一輪 9 個檢定並印表。"""
    results = []
    for (name, horizon), items in pooled.items():
        use = demean_by_period(items) if demean else items
        event = [o.excess for o in use if o.is_event]
        control = [o.excess for o in use if not o.is_event]
        got = compare(f"{name}/{horizon}週", event, control, deduped=True)
        if got is not None:
            results.append(got)
    print(f"\n=== {title} ===")
    if demean:
        # direction_split 把整個橫斷面切成上升/沒上升兩邊,所以每一期扣掉的
        # 是「兩組聯集」的中位數 —— 兩組的中位數會依構造對稱地落在 0 兩側,
        # 勝率也會被推向 50%。這幾欄在這一輪不能當幅度讀,只有 p 值有意義
        # (Mann-Whitney 用的是等級,期間內的平移不影響它)。
        print("  註:去期間化之後,中位數與勝率依構造會靠近 0 與 50%,只看 p 值")
    _print_table(results)


def _print_table(results: list[Comparison]) -> None:
    """九個檢定的結果表。"""
    print(
        f"{'訊號':20}{'週':>3}{'事件n':>6}{'對照n':>6}"
        f"{'事件中位':>9}{'對照中位':>9}{'事件勝率':>9}{'對照勝率':>9}"
        f"{'原始p':>8}{'校正p':>8}"
    )
    scored = adjust(results)
    for got, adjusted in scored:
        label, weeks = got.name.rsplit("/", 1)
        mark = " <-" if adjusted < ALPHA else ""
        print(
            f"{label:20}{weeks.replace('週', ''):>3}{got.n_event:>6}"
            f"{got.n_control:>6}{got.median_event:>+8.1f}%"
            f"{got.median_control:>+8.1f}%{got.win_rate_event:>8.0%}"
            f"{got.win_rate_control:>9.0%}{got.pvalue:>8.3f}{adjusted:>8.3f}{mark}"
        )
    hits = sum(1 for _, a in scored if a < ALPHA)
    print(f"\n{len(results)} 個檢定,FDR 校正後顯著:{hits} 個")


def _print_periods(pooled: dict[tuple[str, int], list[Observation]]) -> None:
    """觀察筆數 vs 不同期間數。

    20 檔共用同一組集保週次,同一週裡的股票一起漲跌,所以同一週的多筆觀察
    不是多個獨立樣本。表上的 n 會高估資訊量,這一段是為了讓它高估多少看得見。
    """
    print("\n事件組的觀察筆數 vs 不同週次(獨立樣本數更接近後者):")
    for (name, horizon), items in sorted(pooled.items()):
        events = [o for o in items if o.is_event]
        if not events:
            continue
        print(
            f"  {name:18} {horizon:>2}週  {len(events):>3} 筆 / "
            f"{effective_n(events):>2} 個不同週次"
        )


if __name__ == "__main__":
    raise SystemExit(main())
