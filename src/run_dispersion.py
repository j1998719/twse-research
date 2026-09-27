"""跑 [#19] 事前登記的出貨訊號檢定。

參數在 [#21] 的留言裡先寫死了:回看 8 週、回落 2 個百分點,持有期 4/8/13 週,
三個訊號定義 —— 合計 9 個檢定,一次 BH 校正。跑完不補測。

樣本是 [#21] 的 20 檔系統性抽樣。**這不是全市場研究**,是先導測試:集保
查詢頁一檔一週要兩個請求,全市場回溯要約 10 萬個請求([#23])。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from src.dispersion import DROP_PP, LOOKBACK, Signal, signals
from src.eventstats import (
    Comparison,
    adjust,
    compare,
    equal_weight_index,
    excess_return,
    median,
    non_overlapping,
)
from src.tdcc import Band, Week


HISTORY = Path("data/raw/tdcc/history")
PRICES = Path("data/out/prices.csv")
#: 集保資料日期到實際可交易之間的時滯。進場不能早於這個
PUBLISH_LAG = timedelta(days=5)
#: 事前登記的持有期,單位是週
HORIZONS = (4, 8, 13)
#: 事前登記的三個訊號
SIGNALS = ("big_rolled_over", "holders_peaked", "distributing")
#: 校正後低於這個才算顯著
ALPHA = 0.05
#: 一致性那一段至少要幾檔才值得印
MIN_STOCKS = 3


def load_weeks(code: str) -> list[Week]:
    """把抓下來的 JSON 還原成 Week。"""
    raw = json.loads((HISTORY / f"{code}.json").read_text(encoding="utf-8"))
    return [
        Week(
            day=date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:])),
            code=code,
            bands={key: Band(**vals) for key, vals in bands.items()},
        )
        for stamp, bands in raw.items()
    ]


def load_closes(codes: set[str]) -> dict[str, dict[date, float]]:
    """讀本地收盤價。基準要用整個宇集,所以不只讀樣本那幾檔。"""
    frame = pd.read_csv(PRICES, dtype={"code": str}, usecols=["day", "code", "close"])
    frame = frame[frame["day"] >= "2025-08-01"]
    out: dict[str, dict[date, float]] = {}
    for code, group in frame.groupby("code"):
        if code not in codes:
            continue
        out[str(code)] = {
            date.fromisoformat(d): float(c)
            for d, c in zip(group["day"], group["close"], strict=True)
            if pd.notna(c) and c > 0
        }
    return out


def first_on_or_after(
    series: dict[date, float], day: date
) -> tuple[date, float] | None:
    """當天或之後最近一個有價格的交易日。"""
    later = sorted(d for d in series if d >= day)
    return (later[0], series[later[0]]) if later else None


def main() -> int:
    """跑完 9 個檢定,把結果印出來。"""
    codes = sorted(p.stem for p in HISTORY.glob("*.json"))
    universe = set(
        pd.read_csv(PRICES, dtype={"code": str}, usecols=["code"])["code"].unique()
    )
    closes = load_closes(universe)
    bench = equal_weight_index({c: dict(s) for c, s in closes.items()})
    print(f"樣本 {len(codes)} 檔,基準用 {len(closes)} 檔等權")
    print(f"回看 {LOOKBACK} 週、回落 {DROP_PP} 個百分點,持有期 {HORIZONS} 週\n")

    # (訊號, 持有期) -> (事件組報酬, 對照組報酬)
    buckets: dict[tuple[str, int], tuple[list[float], list[float]]] = {
        (name, h): ([], []) for name in SIGNALS for h in HORIZONS
    }
    per_stock: dict[tuple[str, int], list[tuple[str, float]]] = {
        key: [] for key in buckets
    }

    for code in codes:
        series = closes.get(code)
        if not series:
            print(f"  {code}: 沒有價格資料,跳過")
            continue
        sigs = signals(sorted(load_weeks(code), key=lambda w: w.day))
        for horizon in HORIZONS:
            rets = _returns(sigs, series, bench, horizon)
            for name in SIGNALS:
                hit = [i for i, s in enumerate(sigs) if getattr(s, name)]
                miss = [i for i, s in enumerate(sigs) if not getattr(s, name)]
                event, control = buckets[(name, horizon)]
                event.extend(_pick(rets, hit, horizon))
                control.extend(_pick(rets, miss, horizon))
                # 一致性看的是同一檔內「事件組中位 − 對照組中位」,不是絕對
                # 超額。絕對超額對每一組都是負的,因為中位數比不過由平均
                # 驅動的等權基準 —— 20 檔裡只有 6 檔贏基準,中位數落後
                # 14.3 個百分點。同一檔內相減,基準那一項就抵掉了。
                theirs = _pick(rets, miss, horizon)
                mine = _pick(rets, hit, horizon)
                if mine and theirs:
                    per_stock[(name, horizon)].append(
                        (code, median(mine) - median(theirs))
                    )

    results = [
        got
        for (name, horizon), (event, control) in buckets.items()
        if (got := compare(f"{name}/{horizon}週", event, control, deduped=True))
    ]
    _print_table(results)
    _print_consistency(per_stock)
    return 0


def _pick(rets: list[float | None], positions: list[int], horizon: int) -> list[float]:
    """挑出互不重疊的那些位置,並丟掉算不出報酬的。"""
    return [
        v for i in non_overlapping(positions, horizon) if (v := rets[i]) is not None
    ]


def _returns(
    sigs: list[Signal],
    series: dict[date, float],
    bench: dict[date, float],
    horizon: int,
) -> list[float | None]:
    """每個訊號週次持有 horizon 週的超額報酬。算不出來的是 None。"""
    days = [s.day for s in sigs]
    return [
        _excess(series, bench, day, days[i + horizon])
        if i + horizon < len(days)
        else None
        for i, day in enumerate(days)
    ]


def _print_table(results: list[Comparison]) -> None:
    """九個檢定的結果表。"""
    print(
        f"{'訊號':20}{'週':>3}{'事件n':>6}{'對照n':>6}"
        f"{'事件中位':>9}{'對照中位':>9}{'勝率':>7}{'原始p':>8}{'校正p':>8}"
    )
    for got, adjusted in adjust(results):
        name, horizon = got.name.rsplit("/", 1)
        mark = " <-" if adjusted < ALPHA else ""
        print(
            f"{name:20}{horizon.replace('週', ''):>3}{got.n_event:>6}"
            f"{got.n_control:>6}{got.median_event:>+8.1f}%"
            f"{got.median_control:>+8.1f}%{got.win_rate_event:>6.0%}"
            f"{got.pvalue:>8.3f}{adjusted:>8.3f}{mark}"
        )
    hits = sum(1 for _, a in adjust(results) if a < ALPHA)
    print(f"\n{len(results)} 個檢定,FDR 校正後顯著:{hits} 個")


def _print_consistency(
    per_stock: dict[tuple[str, int], list[tuple[str, float]]],
) -> None:
    """每檔的方向是否一致。全不顯著時,這是判斷還值不值得追的依據([#21])。"""
    print("\n每檔方向一致性(同一檔內 事件組中位 − 對照組中位 > 0 的檔數):")
    for key, items in sorted(per_stock.items()):
        if len(items) < MIN_STOCKS:
            continue
        pos = sum(1 for _, v in items if v > 0)
        print(
            f"  {key[0]:18} {key[1]:>2}週  {pos}/{len(items)} 檔為正 ({pos / len(items):.0%})"
        )


def _excess(
    series: dict[date, float],
    bench: dict[date, float],
    day: date,
    exit_day: date,
) -> float | None:
    """資料日期 + 時滯之後進場,持有到出場週的同一個時滯點。"""
    entry = first_on_or_after(series, day + PUBLISH_LAG)
    out = first_on_or_after(series, exit_day + PUBLISH_LAG)
    if entry is None or out is None:
        return None
    b_in = first_on_or_after(bench, entry[0])
    b_out = first_on_or_after(bench, out[0])
    if b_in is None or b_out is None:
        return None
    return excess_return(entry[1], out[1], b_in[1], b_out[1])


if __name__ == "__main__":
    raise SystemExit(main())
