"""除權息、減資、變更面額:還原股價用的事件。

每一個事件變成一個「因子 = 參考價 / 前一日收盤」,交給 adjust.py 去乘。
六個來源(上市、上櫃各三種),欄位名稱和日期格式各不相同,所以一律
**用欄名找欄位**,不用位置 —— 證交所的 TWT49U 在 2008–2018 年的版面
「權值」「息值」是分開的兩欄,寫死索引會在舊年份安靜地取錯欄。

格式來自開源專案裡的真實回應 fixture(jiansoft/stock_crawler、
TechTWC/TWstock)。幾個坑:

* **除權息參考價會扣掉現金增資的認購權價值**,但市場常常不照這個跳空
  (6225 在 2026-08-18 參考價 30.04、開盤基準 44.4、收漲停)。所以優先用
  「減除股利參考價」,沒有才退回除權息參考價。
* **減資併同除息辦理的,不在除權息表裡**(TWT49U 的附註寫的),而是在
  減資表的「除權參考價」欄。那一欄有值就用它當最終參考價。
* 同一檔同一天在兩個來源都出現時,只留一個 —— 減資表的優先,因為它的
  參考價已經包含了除息。
* 減資表會有已公告、還沒恢復買賣的列,價格欄是 "-",跳過。
* 日期有三種寫法:"114年01月17日"、"112/07/20"、"1150921"(民國)。
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from src.prices import to_float
from src.tpex import is_common_stock


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0"}

#: 因子超出這個範圍就當成資料錯誤 —— 一次 20 倍的跳空不是除權息
FACTOR_RANGE = (0.05, 20.0)

_ROC_FULL = re.compile(r"^(\d{2,3})年(\d{1,2})月(\d{1,2})日$")
_ROC_SLASH = re.compile(r"^(\d{2,3})/(\d{1,2})/(\d{1,2})$")
_ROC_PACKED = re.compile(r"^(\d{3})(\d{2})(\d{2})$")
#: 民國年轉西元
ROC_OFFSET = 1911


def parse_roc(text: str) -> date | None:
    """三種民國日期寫法都認。認不出來回 None,不要猜。"""
    clean = text.strip()
    for pattern in (_ROC_FULL, _ROC_SLASH, _ROC_PACKED):
        match = pattern.match(clean)
        if match:
            y, m, d = (int(g) for g in match.groups())
            try:
                return date(y + ROC_OFFSET, m, d)
            except ValueError:
                return None
    return None


@dataclass(frozen=True)
class Source:
    """一個事件來源:網址、查詢參數的日期格式,以及要找的欄名。

    每一種欄位都給幾個候選名稱,依序找第一個存在的。
    """

    kind: str
    url: str
    #: 上市用 YYYYMMDD,上櫃用 YYYY/MM/DD
    tpex: bool
    day: tuple[str, ...]
    code: tuple[str, ...]
    prev: tuple[str, ...]
    ref: tuple[str, ...]
    #: 減資併同除息時的最終參考價。有值就取代 ref
    override: tuple[str, ...] = ()
    #: 同一天兩個來源都有時,數字小的優先
    priority: int = 1


SOURCES = (
    Source(
        kind="twse_dividend",
        url="https://www.twse.com.tw/rwd/zh/exRight/TWT49U",
        tpex=False,
        day=("資料日期",),
        code=("股票代號",),
        prev=("除權息前收盤價",),
        ref=("減除股利參考價", "除權息參考價"),
    ),
    Source(
        kind="otc_dividend",
        url="https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ",
        tpex=True,
        day=("除權息日期",),
        code=("代號",),
        prev=("除權息前收盤價",),
        ref=("減除股利參考價", "除權息參考價"),
    ),
    Source(
        kind="twse_reduction",
        url="https://www.twse.com.tw/rwd/zh/reducation/TWTAUU",
        tpex=False,
        day=("恢復買賣日期",),
        code=("股票代號",),
        prev=("停止買賣前收盤價格",),
        ref=("恢復買賣參考價",),
        override=("除權參考價",),
        priority=0,
    ),
    Source(
        kind="otc_reduction",
        url="https://www.tpex.org.tw/www/zh-tw/bulletin/revivt",
        tpex=True,
        day=("恢復買賣日期",),
        code=("股票代號",),
        prev=("最後交易日之收盤價格",),
        ref=("減資恢復買賣開始日參考價格",),
        override=("除權參考價",),
        priority=0,
    ),
    Source(
        kind="twse_par",
        url="https://www.twse.com.tw/rwd/zh/change/TWTB8U",
        tpex=False,
        day=("恢復買賣日期",),
        code=("股票代號", "證券代號"),
        prev=("停止買賣前收盤價格", "最後交易日之收盤價格"),
        ref=("恢復買賣參考價", "恢復買賣開始參考價"),
        priority=0,
    ),
    Source(
        kind="otc_par",
        url="https://www.tpex.org.tw/www/zh-tw/bulletin/pvChgRslt",
        tpex=True,
        day=("恢復買賣日期",),
        code=("證券代號", "股票代號"),
        prev=("最後交易日之收盤價格", "停止買賣前收盤價格"),
        ref=("恢復買賣開始參考價", "恢復買賣參考價"),
        priority=0,
    ),
)


@dataclass(frozen=True)
class Action:
    """一次讓價格跳空的事件。day 之前的價格要乘上 factor。"""

    code: str
    day: date
    factor: float
    kind: str


def table(payload: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    """欄名與資料。證交所是最上層的 fields/data,櫃買是 tables[0]。"""
    if payload.get("tables"):
        first = payload["tables"][0]
        fields, data = first.get("fields") or [], first.get("data") or []
    else:
        fields, data = payload.get("fields") or [], payload.get("data") or []
    return [str(f).strip() for f in fields], data


def complete(payload: dict[str, Any]) -> bool:
    """櫃買的回應有 totalCount;跟實際列數對不上代表被截斷了。"""
    tables = payload.get("tables") or []
    if not tables:
        return True
    total = tables[0].get("totalCount")
    return total is None or total == len(tables[0].get("data") or [])


def _column(fields: Sequence[str], names: Sequence[str]) -> int | None:
    for name in names:
        if name in fields:
            return fields.index(name)
    return None


def _price(row: Sequence[str], at: int | None) -> float | None:
    if at is None or at >= len(row):
        return None
    value = to_float(str(row[at]))
    # "0.00" 在減資表的除權參考價欄代表沒有,不是零元
    return value or None


def parse(payload: dict[str, Any], source: Source) -> list[Action]:
    """把一個來源的回應讀成事件。欄位找不到就報錯,不要安靜地回空的。"""
    fields, data = table(payload)
    if not data:
        return []
    at_day = _column(fields, source.day)
    at_code = _column(fields, source.code)
    at_prev = _column(fields, source.prev)
    at_ref = _column(fields, source.ref)
    if None in (at_day, at_code, at_prev, at_ref):
        msg = f"{source.kind} 的欄位變了:{fields}"
        raise ValueError(msg)
    at_override = _column(fields, source.override)
    # 有減除股利參考價就不用除權息參考價,但那一列是空的時候要退回去
    at_fallback = _column(fields, source.ref[1:]) if len(source.ref) > 1 else None

    # 同一檔同一天只留一列。減資表會把同一次減資依申報日列好幾次,其中
    # 有的列除權參考價有值、有的是 "--" —— 有值的那列才包含了併同的除息
    found: dict[tuple[str, date], tuple[bool, Action]] = {}
    for row in data:
        code = str(row[at_code]).strip()  # type: ignore[index]
        day = parse_roc(str(row[at_day]))  # type: ignore[index]
        if day is None or not is_common_stock(code):
            continue
        prev = _price(row, at_prev)
        final = _price(row, at_override)
        ref = final or _price(row, at_ref) or _price(row, at_fallback)
        if prev is None or ref is None:
            continue
        factor = ref / prev
        if not FACTOR_RANGE[0] < factor < FACTOR_RANGE[1]:
            continue
        key = (code, day)
        if key in found and (found[key][0] or final is None):
            continue
        found[key] = (final is not None, Action(code, day, factor, source.kind))
    return [action for _, action in found.values()]


def merge(groups: Iterable[tuple[Source, list[Action]]]) -> list[Action]:
    """同一檔同一天在不同來源都出現時只留一個,priority 小的優先。"""
    best: dict[tuple[str, date], tuple[int, Action]] = {}
    for source, actions in groups:
        for action in actions:
            key = (action.code, action.day)
            held = best.get(key)
            if held is None or source.priority < held[0]:
                best[key] = (source.priority, action)
    return sorted((a for _, a in best.values()), key=lambda a: (a.code, a.day))


def _param(day: date, *, tpex: bool) -> str:
    return f"{day:%Y/%m/%d}" if tpex else f"{day:%Y%m%d}"


def fetch(source: Source, start: date, end: date) -> dict[str, Any]:
    """抓一段期間。"""
    query = (
        f"startDate={_param(start, tpex=source.tpex)}"
        f"&endDate={_param(end, tpex=source.tpex)}&response=json"
    )
    req = urllib.request.Request(f"{source.url}?{query}", headers=UA)  # noqa: S310
    with urllib.request.urlopen(req, timeout=60) as res:  # noqa: S310
        body: bytes = res.read()
    loaded: dict[str, Any] = json.loads(body)
    return loaded


def cached(
    source: Source, start: date, end: date, cache_dir: Path, *, today: date
) -> dict[str, Any]:
    """抓一段期間並存快取。期間還沒結束的不存 —— 之後還會有新的事件。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{source.kind}_{start:%Y%m%d}_{end:%Y%m%d}.json"
    if path.exists():
        hit: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return hit
    payload = fetch(source, start, end)
    if not complete(payload):
        msg = f"{source.kind} {start}~{end} 被截斷了,要把期間切小"
        raise ValueError(msg)
    if end < today:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload
