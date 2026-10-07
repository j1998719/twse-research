"""可轉債每日成交行情(櫃買 rsta0113「每日轉(交)換公司債買賣斷交易行情表」,#64)。

跟條款看板(cbboard.py)同一個端點、同一種格式(TITLE / DATADATE / HEADER / BODY,
cp950),2017-01 起每天一份。每一檔有「等價」和「議價」兩列,只取等價;沒成交的
日子收市是空白,但「明日參價」有值。

解不出來一律拋 QuoteError —— 「0 列」和「那天沒資料」長得一樣,#26 就是這樣誤判了四次。
"""

from __future__ import annotations

import csv
import gzip
import io
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from src.cbboard import DATA_DAY, ENCODING


if TYPE_CHECKING:
    from pathlib import Path

#: 一定要有的欄位
NEEDED = ("代號", "收市", "單位", "金額", "明日參價")


class QuoteError(ValueError):
    """這份行情解不出來。"""


@dataclass(frozen=True, slots=True)
class Quote:
    """一檔可轉債在那一天的行情(每 100 元面額的價格)。沒有就是 None。"""

    code: str
    name: str
    close: float | None
    #: 成交張數
    units: int | None
    #: 成交金額(元)
    amount: int | None
    #: 明日參考價。沒成交的日子拿它當價格,但要標記
    reference: float | None


@dataclass(frozen=True)
class QuoteDay:
    """一天的行情。"""

    day: date
    quotes: tuple[Quote, ...]


def _number(text: str) -> float | None:
    cleaned = text.strip().replace(",", "").replace("+", "")
    if not cleaned or cleaned in {"-", "--", "---"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        msg = f"看不懂的數字:{text!r}"
        raise QuoteError(msg) from None


def parse_quotes(raw: bytes) -> QuoteDay:
    """一份行情的原始位元組 → QuoteDay。"""
    if not raw.strip():
        msg = "空檔案"
        raise QuoteError(msg)
    try:
        text = raw.decode(ENCODING)
    except UnicodeDecodeError as exc:
        msg = f"不是 {ENCODING}:{exc}"
        raise QuoteError(msg) from None
    rows = list(csv.reader(io.StringIO(text)))
    stamp = next((",".join(r[1:]) for r in rows if r and r[0] == "DATADATE"), "")
    hit = DATA_DAY.search(stamp)
    if hit is None:
        msg = "DATADATE 解不出日期(錯誤頁?)"
        raise QuoteError(msg)
    year, month, dd = (int(g) for g in hit.groups())
    day = date(year + 1911, month, dd)
    header = next((r[1:] for r in rows if r and r[0] == "HEADER"), None)
    if header is None:
        msg = f"{day} 沒有 HEADER"
        raise QuoteError(msg)
    at = {name.strip(): i for i, name in enumerate(header)}
    missing = [n for n in NEEDED if n not in at]
    if missing:
        msg = f"{day} 的表頭少了 {missing}"
        raise QuoteError(msg)
    quotes = []
    for cells in (r[1:] for r in rows if r and r[0] == "BODY"):
        code = cells[at["代號"]].strip()
        if not code:  # 議價那一列
            continue
        units, amount = _number(cells[at["單位"]]), _number(cells[at["金額"]])
        quotes.append(
            Quote(
                code=code,
                name=cells[at["名稱"]].strip() if "名稱" in at else "",
                close=_number(cells[at["收市"]]),
                units=None if units is None else int(units),
                amount=None if amount is None else int(amount),
                reference=_number(cells[at["明日參價"]]),
            )
        )
    if not quotes:
        msg = f"{day} 一檔都沒有"
        raise QuoteError(msg)
    return QuoteDay(day=day, quotes=tuple(quotes))


def quote_path(root: Path, day: date) -> Path:
    """存檔位置:root/年/RSta0113.YYYYMMDD-C.csv.gz。"""
    return root / f"{day:%Y}" / f"RSta0113.{day:%Y%m%d}-C.csv.gz"


def load_quotes(root: Path) -> list[QuoteDay]:
    """讀回所有存檔,由舊到新。"""
    return [
        parse_quotes(gzip.decompress(p.read_bytes()))
        for p in sorted(root.glob("*/RSta0113.*-C.csv.gz"))
    ]
