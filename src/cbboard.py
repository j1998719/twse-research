"""櫃買中心的「轉換公司債資訊看板」(RSdrs001)日存檔(#26)。

每個交易日一份,是那一天**仍在櫃檯買賣**的可轉債的條款快照 —— 含後來到期、
被賣回、被贖回而下架的債,所以逐日讀下來就是沒有倖存者偏誤的母體(第二輪)。

檔案格式是 cp950 的 CSV,每列第一欄是列的種類:

    TITLE,轉換公司債資訊看板
    DATADATE,日期:115年09月30日
    ALIGN,...
    HEADER,債券代碼,債券簡稱,轉換起日,...
    BODY,"53887","中磊七    ","2024/03/07",...
    GLOSS,"註2:轉換價格係指下次轉換價格生效日後之轉換價格,..."

幾件實測過的事(第二到第五輪):

* **編碼是 cp950 不是 big5**:big5 有 9 個字解不出來,全在債券簡稱。
* **欄位數會漂移**:2017/2019 是 22 欄(多了「最近停止轉換起日/迄日」),
  之後 20 欄。所以欄位一律按表頭的**名稱**查,不按位置。
* **日期有兩種寫法**:舊的 `20151016`、空白寫成 `0`;新的 `2025/03/11`、
  空白就是空白。兩種都會出現 `19110000` / `1911/00/00` —— 民國 0 年直接加
  1911,也是空白。其他寫法一律報錯,不猜。
* **`0.0000` 是「沒有」**:價格欄的 0 一律當成 None,否則賣回收益率會算成
  負無限大。
* **歷史從 2017-01-17 開始**(第五輪撤回了「2008 就有」的說法)。
* **標的股代號 = 債券代碼前四碼**。序號可以是兩位(`811211` 是 8112 的第
  11 檔),所以不能用「去掉最後一碼」。
* **轉換價格是「下次轉換價格生效日」之後的價格**(GLOSS 註2)。生效日還沒到
  的時候,看板上那個價格**還沒生效**。要取某一天實際有效的轉換價,用
  `src.events.cb.effective_conversion_price`,不要直接讀這一欄。

`parse()` 遇到下面這幾種情況拋 `BoardError`,因為它們都長得跟「那天沒資料」
一模一樣,而這個 issue 已經五次把資料可得性搞錯(四次是「解不出來」被讀成
「拿不到」):

* 空檔案(0 byte 的回應)
* 夠大但既沒有 DATADATE 也沒有 BODY(導向的錯誤頁)
* DATADATE 解不出日期
* 沒有任何 BODY 列,或表頭少了要用的欄位
* 欄位裡出現看不懂的日期或數字
"""

from __future__ import annotations

import csv
import functools
import gzip
import io
import re
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from src.tpex import roc_to_date


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    import pandas as pd

ENCODING = "cp950"
#: 看板檔名裡的日期,例如 RSdrs001.20170117-C.csv
#: 列表裡檔名的日期。看板(RSdrs001)和日行情(RSta0113,#64)同一種寫法
FILE_DAY = re.compile(r"RS\w+\.(\d{8})-C\.csv$", re.IGNORECASE)
#: DATADATE 的寫法:日期:106年01月17日。民國 100 年以前是兩位數
DATA_DAY = re.compile(r"(\d{2,3})年(\d{1,2})月(\d{1,2})日")
#: 新格式的日期 2025/03/11
SLASHED = re.compile(r"^(\d{4})/(\d{2})/(\d{2})$")
#: 舊格式的日期 20151016
COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
#: 日期欄的「沒有」:新格式是空白,舊格式是 0
BLANK_DATES = {"", "0"}
#: 民國 0 年加 1911 的那種「沒有」:19110000、1911/00/00
ROC_ZERO_YEAR = 1911
#: 標的股代號的長度:債券代碼的前四碼
UNDERLYING_LEN = 4

#: 欄位名 → Bond 的屬性。表頭少了任何一個就報錯
DATE_FIELDS = {
    "轉換起日": "conversion_start",
    "轉換迄日": "conversion_end",
    "下次轉換價格生效日期": "next_reset",
    "最近賣回權起日": "put_start",
    "最近賣回權迄日": "put_end",
    "強制贖回起日": "call_start",
    "強制贖回迄日": "call_end",
    "終止櫃檯買賣日": "delisted",
}
PRICE_FIELDS = {
    "轉換價格": "conversion_price",
    "最近賣回權價格": "put_price",
    "強制贖回價格": "call_price",
    "轉債參考價格": "reference_price",
    "轉換標的股票價格": "stock_price",
}
AMOUNT_FIELDS = {"原始發行總額": "issued", "上月底發行餘額": "outstanding"}
NEEDED = ("債券代碼", "債券簡稱", *DATE_FIELDS, *PRICE_FIELDS, *AMOUNT_FIELDS)


class BoardError(ValueError):
    """這份看板解不出來。跟「那天沒有資料」不一樣,所以不能安靜地回空表。"""


@dataclass(frozen=True, slots=True)
class Bond:
    """看板上的一列:一檔可轉債在那一天的條款。日期與價格空白是 None。"""

    code: str
    name: str
    conversion_start: date | None
    conversion_end: date | None
    #: 看板上的轉換價格。是「下次轉換價格生效日」之後的價格,不一定已經生效
    conversion_price: float | None
    next_reset: date | None
    #: 「最近一次」的賣回權,不是「下一次」—— 看板不預告更遠的賣回日
    put_start: date | None
    put_end: date | None
    put_price: float | None
    call_start: date | None
    call_end: date | None
    call_price: float | None
    delisted: date | None
    issued: int | None
    #: 上月底發行餘額(元)
    outstanding: int | None
    reference_price: float | None
    stock_price: float | None

    @property
    def underlying(self) -> str:
        """標的股代號:債券代碼的前四碼。"""
        return self.code[:UNDERLYING_LEN]


@dataclass(frozen=True)
class Board:
    """一天的看板。"""

    day: date
    bonds: tuple[Bond, ...]

    def bond(self, code: str) -> Bond | None:
        """按債券代碼找一列。"""
        return next((b for b in self.bonds if b.code == code), None)


# 兩千多份看板、七十萬列,不同的日期字串只有幾千個:快取起來,同一個日期
# 共用同一個物件,記憶體和時間都省一個數量級
@functools.cache
def _cell_date(text: str, field: str) -> date | None:
    cleaned = text.strip()
    if cleaned in BLANK_DATES:
        return None
    hit = SLASHED.match(cleaned) or COMPACT.match(cleaned)
    if hit is None:
        msg = f"{field} 的日期看不懂:{cleaned!r}"
        raise BoardError(msg)
    # 「19110000」「1911/00/00」是民國 0 年 0 月 0 日換成西元 —— 來源把空白
    # 的民國日期直接加了 1911,意思同樣是「沒有」
    if int(hit.group(1)) == ROC_ZERO_YEAR:
        return None
    try:
        return date(*(int(g) for g in hit.groups()))
    except ValueError:
        msg = f"{field} 的日期不存在:{cleaned!r}"
        raise BoardError(msg) from None


def _cell_number(text: str, field: str) -> float | None:
    cleaned = text.strip().replace(",", "")
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        msg = f"{field} 的數字看不懂:{cleaned!r}"
        raise BoardError(msg) from None
    # 0.0000 是這個來源的「沒有」
    return value or None


def _bond(cells: Sequence[str], at: dict[str, int]) -> Bond:
    values: dict[str, Any] = {
        attr: _cell_date(cells[at[name]], name) for name, attr in DATE_FIELDS.items()
    }
    values.update(
        {
            attr: _cell_number(cells[at[name]], name)
            for name, attr in PRICE_FIELDS.items()
        }
    )
    for name, attr in AMOUNT_FIELDS.items():
        amount = _cell_number(cells[at[name]], name)
        values[attr] = None if amount is None else int(amount)
    return Bond(
        code=cells[at["債券代碼"]].strip(),
        name=cells[at["債券簡稱"]].strip(),
        **values,
    )


def _data_day(rows: Iterable[list[str]]) -> date:
    for row in rows:
        if row and row[0] == "DATADATE":
            hit = DATA_DAY.search(",".join(row[1:]))
            if hit is not None:
                year, month, day = (int(g) for g in hit.groups())
                return date(year + 1911, month, day)
    msg = "DATADATE 解不出日期"
    raise BoardError(msg)


def parse(raw: bytes) -> Board:
    """一份看板的原始位元組 → Board。解不出來一律拋 BoardError。"""
    if not raw.strip():
        msg = "空檔案(0 byte 的回應),不是「那天沒有資料」"
        raise BoardError(msg)
    try:
        text = raw.decode(ENCODING)
    except UnicodeDecodeError as exc:
        msg = f"不是 {ENCODING}:{exc}"
        raise BoardError(msg) from None
    rows = list(csv.reader(io.StringIO(text)))
    day = _data_day(rows)
    header = next((row[1:] for row in rows if row and row[0] == "HEADER"), None)
    body = [row[1:] for row in rows if row and row[0] == "BODY"]
    if header is None or not body:
        msg = f"{day} 沒有 HEADER 或 BODY 列"
        raise BoardError(msg)
    at = {name.strip(): i for i, name in enumerate(header)}
    missing = [name for name in NEEDED if name not in at]
    if missing:
        msg = f"{day} 的表頭少了 {missing}(欄位名變了?)"
        raise BoardError(msg)
    bonds = []
    for cells in body:
        if len(cells) != len(header):
            msg = f"{day} 有一列 {len(cells)} 欄,表頭是 {len(header)} 欄"
            raise BoardError(msg)
        bonds.append(_bond(cells, at))
    return Board(day=day, bonds=tuple(bonds))


def parse_listing(payload: dict[str, Any]) -> list[tuple[date, str]]:
    """月份列表(cbDaily 的回應)→ [(資料日期, 看板檔的路徑)],由舊到新。

    列表上的民國日期必須跟檔名裡的日期一致 —— 對不上就是來源格式變了,
    猜哪一個對都可能讓整份看板錨到錯的一天。
    """
    out: list[tuple[date, str]] = []
    for table in payload.get("tables") or []:
        if "資料日期" not in (table.get("fields") or []):
            continue
        for row in table.get("data") or []:
            day = roc_to_date(str(row[0]))
            hit = FILE_DAY.search(str(row[1]))
            if day is None or hit is None or hit.group(1) != f"{day:%Y%m%d}":
                msg = f"列表的日期 {row[0]!r} 和檔案 {row[1]!r} 對不上"
                raise BoardError(msg)
            out.append((day, str(row[1])))
    return sorted(out)


def months(start: date, end: date) -> list[date]:
    """期間內每個月的第一天(含頭尾所在的月份)。列表一個月一個請求。"""
    out = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        out.append(cursor)
        cursor = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
    return out


def board_path(root: Path, day: date) -> Path:
    """一天的看板存在哪裡:root/年/RSdrs001.YYYYMMDD-C.csv.gz。"""
    return root / f"{day:%Y}" / f"RSdrs001.{day:%Y%m%d}-C.csv.gz"


def load_boards(root: Path) -> list[Board]:
    """讀回所有存檔,由舊到新。壞掉的檔案直接報錯 —— 存檔前已經驗過,壞了就是有問題。"""
    return [
        parse(gzip.decompress(path.read_bytes()))
        for path in sorted(root.glob("*/RSdrs001.*-C.csv.gz"))
    ]


@dataclass(frozen=True)
class Linkage:
    """看板上的債接不接得到股價。"""

    bonds: int
    bonds_priced: int
    underlyings: int
    priced: tuple[str, ...]
    missing: tuple[str, ...]


def link_to_prices(boards: Sequence[Board], prices: pd.DataFrame) -> Linkage:
    """債券代碼前四碼 → 股價表的代號。驗的是**代號對得上**,不是每天都有價格。

    第一到四輪說「標的全部都有股價」都是離線用眼睛查的,沒進程式也沒進測試,
    所以既不會重跑、壞了也不會被發現。這裡讓它變成一個會被檢查的數字。
    """
    codes = {b.code for board in boards for b in board.bonds}
    underlyings = {code[:UNDERLYING_LEN] for code in codes}
    have = set(prices.code.astype(str)) if not prices.empty else set()
    return Linkage(
        bonds=len(codes),
        bonds_priced=sum(1 for code in codes if code[:UNDERLYING_LEN] in have),
        underlyings=len(underlyings),
        priced=tuple(sorted(underlyings & have)),
        missing=tuple(sorted(underlyings - have)),
    )
