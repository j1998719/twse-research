"""櫃買中心(上櫃)的行情與處置公告。

[#23] 量出來現有研究只涵蓋 2,957 檔普通股裡的 1,105 檔(37.4%)—— 缺的
1,852 檔全是上櫃。這個模組補那一半。

兩個來源的成本差很多:

* **處置公告**:一個請求就拿到 2020 至今(3,072 列、2,480 次處置、810 檔)
* **每日行情**:一天一個請求,七年約 1,750 個 —— 和現有的 TWSE 抓取同量級

日期用民國年。回 0 列代表非交易日,不是錯誤。
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import date  # noqa: TC003 - Quote 的欄位在 runtime 也要它
from typing import TYPE_CHECKING, Any

from src.prices import to_float


if TYPE_CHECKING:
    from collections.abc import Iterator

UA = {"User-Agent": "Mozilla/5.0"}
QUOTES_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"
DISPOSAL_URL = "https://www.tpex.org.tw/www/zh-tw/bulletin/disposal"

#: 只看普通股:四碼、不以 00 開頭。這個來源混了 ETF(00 開頭)和
#: 轉換公司債(五碼,例如 36053),兩者都不是我們要研究的標的
COMMON_STOCK_LEN = 4


def is_common_stock(code: str) -> bool:
    """四碼、不以 00 開頭、全是數字。"""
    cleaned = code.strip()
    return (
        len(cleaned) == COMMON_STOCK_LEN
        and cleaned.isdigit()
        and not cleaned.startswith("00")
    )


def roc(day: date) -> str:
    """西元轉民國,格式 115/09/23。"""
    return f"{day.year - 1911}/{day.month:02d}/{day.day:02d}"


def _fetch(url: str, params: str) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310
        f"{url}?{params}&response=json", headers=UA
    )
    with urllib.request.urlopen(request, timeout=60) as res:  # noqa: S310
        body: bytes = res.read()
    loaded: dict[str, Any] = json.loads(body)
    return loaded


def _rows(payload: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    """第一張表的欄名與資料。沒有表就是空的。"""
    tables = payload.get("tables") or []
    if not tables:
        return [], []
    first = tables[0]
    return [str(f).strip() for f in (first.get("fields") or [])], (
        first.get("data") or []
    )


@dataclass(frozen=True)
class Quote:
    """一檔上櫃股票一天的行情。"""

    day: date
    code: str
    name: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None


def parse_quotes(payload: dict[str, Any], day: date) -> list[Quote]:
    """把每日行情讀成 Quote。

    欄位用名稱查而不是索引 —— 這個來源的欄名帶著不固定的空白
    (「收盤 」、「 成交金額(元)」),所以比對前要 strip。證交所調整過欄位
    順序,寫死索引的話舊年份會安靜地取到錯的欄位([#11] 的教訓)。
    """
    fields, data = _rows(payload)
    if not fields:
        return []
    at = {name: i for i, name in enumerate(fields)}
    needed = ("代號", "名稱", "收盤", "開盤", "最高", "最低", "成交股數")
    if any(name not in at for name in needed):
        msg = f"上櫃行情的欄位變了:{fields}"
        raise ValueError(msg)
    out: list[Quote] = []
    for row in data:
        code = str(row[at["代號"]]).strip()
        if not is_common_stock(code):
            continue
        out.append(
            Quote(
                day=day,
                code=code,
                name=str(row[at["名稱"]]).strip(),
                open=to_float(row[at["開盤"]]),
                high=to_float(row[at["最高"]]),
                low=to_float(row[at["最低"]]),
                close=to_float(row[at["收盤"]]),
                volume=to_float(row[at["成交股數"]]),
            )
        )
    return out


def fetch_quotes(day: date) -> dict[str, Any]:
    """抓一天的全櫃買行情。非交易日會回一張空表,不是錯誤。"""
    return _fetch(QUOTES_URL, f"date={roc(day)}&type=EW")


def fetch_disposals(start: date, end: date) -> dict[str, Any]:
    """抓一段期間的處置公告。七年一次抓完沒問題。"""
    return _fetch(DISPOSAL_URL, f"startDate={roc(start)}&endDate={roc(end)}")


def parse_disposals(payload: dict[str, Any]) -> Iterator[dict[str, str]]:
    """把處置公告讀成一列一個 dict,只留普通股。

    **「累計」那一欄不是第幾次處置。** 處置次數在「處置內容」的文字裡 ——
    [#8] 就是把累計當成次數,算出 70% 的第二次處置率(真值 34%)。
    這裡原樣保留兩欄,判斷次數交給上層。
    """
    fields, data = _rows(payload)
    if not fields:
        return
    at = {name: i for i, name in enumerate(fields)}
    if "證券代號" not in at:
        msg = f"上櫃處置公告的欄位變了:{fields}"
        raise ValueError(msg)
    for row in data:
        code = str(row[at["證券代號"]]).strip()
        if not is_common_stock(code):
            continue
        yield {name: str(row[i]).strip() for name, i in at.items() if name}
