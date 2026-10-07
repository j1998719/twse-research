"""證交所公告的休市日(#54)。

處置股卡片要往後推算出關日、t−6、t−1。以前只跳過週末,所以國定假日會被當成
交易日 —— 2026 年國慶日 10/10 是星期六,10/09(五)補假休市,推算出來的買點就
差了一天。

證交所的「市場開休市日期」一年一張表,但表裡也有不是休市的列:「國曆新年開始
交易日」「農曆春節前最後交易日」那種是**交易日**,要排除;「市場無交易,僅辦理
結算交割作業」是休市。

抓到就存一份快取;抓不到(或還沒公告明年)就用快取,再不行就是空集合 —— 那時候
推算會退回「只看星期幾」,跟以前一樣。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from src.net import TLS
from src.prices import TAIPEI


if TYPE_CHECKING:
    from pathlib import Path

URL = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule"
UA = {"User-Agent": "Mozilla/5.0"}
#: 名稱裡有這些字的列是交易日,不是休市
TRADING_MARKS = ("開始交易", "最後交易")
#: 快取超過這麼多天就重抓一次(證交所偶爾會補公告)
MAX_AGE_DAYS = 7


def parse(payload: dict[str, Any]) -> set[date]:
    """一年的開休市表 → 休市的日期。欄位用名稱找。"""
    fields = [str(f) for f in payload.get("fields") or []]
    if "日期" not in fields or "名稱" not in fields:
        return set()
    at_day, at_name = fields.index("日期"), fields.index("名稱")
    out = set()
    for row in payload.get("data") or []:
        name = str(row[at_name])
        if any(mark in name for mark in TRADING_MARKS):
            continue
        try:
            out.add(date.fromisoformat(str(row[at_day]).strip()))
        except ValueError:
            continue
    return out


def _fetch(year: int) -> dict[str, Any]:
    url = f"{URL}?response=json&queryYear={year}"
    req = urllib.request.Request(url, headers=UA)  # noqa: S310
    with urllib.request.urlopen(req, timeout=30, context=TLS) as res:  # noqa: S310
        loaded: dict[str, Any] = json.loads(res.read())
    return loaded


def load(years: list[int], cache_dir: Path, *, today: date) -> set[date]:
    """這幾年的休市日。快取太舊或沒有就重抓;抓不到就用手上有的。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out: set[date] = set()
    for year in years:
        path = cache_dir / f"holidays_{year}.json"
        fresh = (
            path.exists()
            and (
                today - datetime.fromtimestamp(path.stat().st_mtime, tz=TAIPEI).date()
            ).days
            <= MAX_AGE_DAYS
        )
        if not fresh:
            try:
                payload = _fetch(year)
                if parse(payload):
                    path.write_text(
                        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                    )
            except (OSError, ValueError, urllib.error.URLError):
                pass
        if path.exists():
            out |= parse(json.loads(path.read_text(encoding="utf-8")))
    return out
