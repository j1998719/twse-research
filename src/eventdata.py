"""事件研究的資料載入。

本來散在 src/run_*.py 裡,而那些檔案被 coverage 排除 —— 所以連「哪一天之後
的價格才算」這種會左右結論的參數都沒有測試看著。而且 run_concentration 去
import run_dispersion,讓一個研究的進入點變成另一個研究的函式庫。

集中在這裡,兩個 runner 都從這裡拿。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from src.tdcc import Band, Week


#: 抓下來的集保歷史,一檔一個 JSON
HISTORY = Path("data/raw/tdcc/history")
#: 每日行情
PRICES = Path("data/out/prices.csv")
#: 集保資料日期到實際可交易之間的時滯。進場不能早於這個
PUBLISH_LAG = timedelta(days=5)
#: 價格從哪一天開始讀。
#:
#: 集保查詢頁只有約 52 週(最早 2025-10-03),所以再往前的價格對這個研究
#: 沒有用,只會讓載入變慢。留一點前置是為了讓基準有東西可以算第一天的報酬。
PRICE_FROM = "2025-08-01"


def load_weeks(code: str, history: Path = HISTORY) -> list[Week]:
    """把抓下來的 JSON 還原成 Week,由舊到新。"""
    raw = json.loads((history / f"{code}.json").read_text(encoding="utf-8"))
    weeks = [
        Week(
            day=_as_date(stamp),
            code=code,
            bands={key: Band(**vals) for key, vals in bands.items()},
        )
        for stamp, bands in raw.items()
    ]
    return sorted(weeks, key=lambda w: w.day)


def _as_date(stamp: str) -> date:
    return date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))


def available_codes(history: Path = HISTORY) -> list[str]:
    """有抓到集保歷史的股票代號。"""
    return sorted(p.stem for p in history.glob("*.json"))


def load_closes(
    codes: set[str] | None = None,
    prices: Path = PRICES,
    since: str = PRICE_FROM,
) -> dict[str, dict[date, float]]:
    """讀收盤價。codes 不給就全部讀。

    基準要用整個宇集,所以通常是全部讀,不只讀樣本那幾檔。

    價格是 0 或缺值的那一天整天跳過 —— 補一個 0 進去會讓報酬變成 -100%。
    """
    frame = pd.read_csv(prices, dtype={"code": str}, usecols=["day", "code", "close"])
    frame = frame[frame["day"] >= since]
    out: dict[str, dict[date, float]] = {}
    for code, group in frame.groupby("code"):
        name = str(code)
        if codes is not None and name not in codes:
            continue
        series = {
            date.fromisoformat(day): float(close)
            for day, close in zip(group["day"], group["close"], strict=True)
            if pd.notna(close) and close > 0
        }
        if series:
            out[name] = series
    return out
