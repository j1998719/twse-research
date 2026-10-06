"""證交所每日收盤行情。

一次請求拿一天的全市場資料,比一檔一檔抓快十倍。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from src.net import TLS
from src.twse import UA, is_common_stock


if TYPE_CHECKING:
    from pathlib import Path


INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"

#: 沒有成交時證交所會填這些符號,不是數字
BLANKS = {"--", "---", "-----", "", "X", "x"}

#: 星期六是 5,所以 weekday 小於 5 就是平日
SATURDAY = 5

#: 本益比在第 16 欄(索引 15)
PER_COLUMN = 15

#: 星期六是 5,所以小於 5 就是平日
SATURDAY = 5


def to_float(text: str) -> float | None:
    """把「1,234.50」轉成 1234.5;沒成交的符號回 None。"""
    clean = text.strip().replace(",", "")
    if clean in BLANKS:
        return None
    try:
        return float(clean)
    except ValueError:
        return None


@dataclass(frozen=True)
class Bar:
    """一檔股票一天的價量。"""

    day: date
    code: str
    name: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int
    #: 本益比。虧損或 EPS 為零時證交所填 0,所以 0 代表「沒有獲利」而不是「很便宜」
    per: float | None


def parse_day(
    payload: dict[str, Any], day: date, *, common_only: bool = True
) -> list[Bar]:
    """從當日行情的回應裡挑出個股表並轉成 Bar。"""
    table = None
    for candidate in payload.get("tables") or []:
        if "證券代號" in (candidate.get("fields") or []):
            table = candidate
            break
    if table is None:
        return []

    bars: list[Bar] = []
    for row in table.get("data") or []:
        code = str(row[0]).strip()
        if common_only and not is_common_stock(code):
            continue
        volume = to_float(str(row[2]))
        bars.append(
            Bar(
                day=day,
                code=code,
                name=str(row[1]).strip(),
                open=to_float(str(row[5])),
                high=to_float(str(row[6])),
                low=to_float(str(row[7])),
                close=to_float(str(row[8])),
                volume=int(volume) if volume is not None else 0,
                per=to_float(str(row[15])) if len(row) > PER_COLUMN else None,
            )
        )
    return bars


def fetch_day(
    day: date, cache_dir: Path, *, pause: float = 1.5
) -> dict[str, Any] | None:
    """抓一天。非交易日回 None。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"mi_index_{day:%Y%m%d}.json"
    if cached.exists():
        raw = cached.read_text(encoding="utf-8")
        if not raw.strip():
            return None
        hit: dict[str, Any] = json.loads(raw)
        return hit

    url = f"{INDEX_URL}?date={day:%Y%m%d}&type=ALLBUT0999&response=json"
    # S310:網址由本模組的常數拼成,不是外部輸入,沒有 file: 之類的風險
    req = urllib.request.Request(url, headers={"User-Agent": UA})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=30, context=TLS) as resp:  # noqa: S310
            payload: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError):
        time.sleep(pause * 4)  # 被擋就等久一點再讓呼叫端重試
        raise

    time.sleep(pause)
    if payload.get("stat") != "OK":
        # 非交易日:寫一個空檔案記住,下次不用再問。
        #
        # 只在**週末**這樣做。平日回 stat != OK 可能是真的休市,也可能是
        # 限流或暫時性錯誤 —— 兩者長得一模一樣,而寫下空檔案就永遠不會再
        # 重試了。實測 2026-09-21(週一)就是這樣被記成非交易日,而那天
        # 上櫃有 891 檔在交易、上市其實有 1,085 檔。
        #
        # 平日不寫快取,下次跑會再問一次。代價是真的國定假日每次都會多問
        # 一次,那比永久少一天資料便宜太多。
        if day.weekday() >= SATURDAY:
            cached.write_text("", encoding="utf-8")
        return None

    cached.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def weekdays(start: date, end: date) -> list[date]:
    """週一到週五。國定假日靠 API 回非交易日來排除。"""
    days: list[date] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < SATURDAY:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days
