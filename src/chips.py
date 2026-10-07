"""三大法人買賣超。

欄位一律用名稱查,不用索引 —— 證交所調整過欄位順序,
寫死索引的話舊年份會安靜地取到錯的欄位。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.net import TLS
from src.prices import SATURDAY, to_float
from src.twse import UA, is_common_stock


if TYPE_CHECKING:
    from datetime import date
    from pathlib import Path

T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"

#: 每一類法人的買賣超欄位。同一類可能拆成好幾欄(例如外資),要全部加起來。
#: 用「欄名包含這些字」來比對,證交所偶爾會微調用詞
FOREIGN_PARTS = ("外陸資買賣超", "外資自營商買賣超", "外資買賣超")
TRUST_PARTS = ("投信買賣超",)
#: 自營商總買賣超那一欄,不能跟「自行買賣」「避險」兩個細項一起加,會重複計算
DEALER_EXACT = "自營商買賣超股數"


@dataclass(frozen=True)
class Chips:
    """一檔股票一天的三大法人買賣超(股數,正數是買超)。"""

    day: date
    code: str
    name: str
    foreign: int
    trust: int
    dealer: int

    @property
    def total(self) -> int:
        """三大法人合計。"""
        return self.foreign + self.trust + self.dealer


def _column_index(fields: list[str], parts: tuple[str, ...]) -> list[int]:
    """找出欄名包含其中任一關鍵字的欄位位置。"""
    return [
        i
        for i, name in enumerate(fields)
        if any(part in name.replace(" ", "") for part in parts)
    ]


def _sum_columns(row: list[Any], indexes: list[int]) -> int:
    total = 0.0
    for i in indexes:
        if i < len(row):
            value = to_float(str(row[i]))
            if value is not None:
                total += value
    return int(total)


def parse_chips(
    payload: dict[str, Any], day: date, *, common_only: bool = True
) -> list[Chips]:
    """把三大法人買賣超日報轉成 Chips。"""
    fields = payload.get("fields") or []
    if not fields:
        return []

    foreign_at = _column_index(fields, FOREIGN_PARTS)
    trust_at = _column_index(fields, TRUST_PARTS)
    dealer_at = [
        i for i, name in enumerate(fields) if name.replace(" ", "") == DEALER_EXACT
    ]

    rows: list[Chips] = []
    for row in payload.get("data") or []:
        code = str(row[0]).strip()
        if common_only and not is_common_stock(code):
            continue
        rows.append(
            Chips(
                day=day,
                code=code,
                name=str(row[1]).strip(),
                foreign=_sum_columns(row, foreign_at),
                trust=_sum_columns(row, trust_at),
                dealer=_sum_columns(row, dealer_at),
            )
        )
    return rows


def fetch_chips(
    day: date, cache_dir: Path, *, pause: float = 1.5
) -> dict[str, Any] | None:
    """抓一天的三大法人買賣超。非交易日回 None。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"t86_{day:%Y%m%d}.json"
    if cached.exists():
        raw = cached.read_text(encoding="utf-8")
        if not raw.strip():
            return None
        hit: dict[str, Any] = json.loads(raw)
        return hit

    url = f"{T86_URL}?date={day:%Y%m%d}&selectType=ALL&response=json"
    # S310:網址由本模組的常數拼成,不是外部輸入
    req = urllib.request.Request(url, headers={"User-Agent": UA})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=30, context=TLS) as resp:  # noqa: S310
            payload: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError):
        time.sleep(pause * 4)
        raise

    time.sleep(pause)
    if payload.get("stat") != "OK":
        cached.write_text("", encoding="utf-8")  # 非交易日,記住別再問
        return None

    cached.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


# --- 上櫃 ---
#
# 櫃買的三大法人表有 24 欄,每一類法人都是「買進股數、賣出股數、買賣超股數」
# 三欄,欄名完全一樣,也沒有分組資訊 —— 只能照位置讀。所以每一列都驗算一次:
# 外資合計 + 投信 + 自營商合計 必須等於最後的三大法人合計。櫃買哪天調了
# 欄位順序,這個等式就會壞,直接報錯,而不是安靜地把投信讀成自營商。

OTC_URL = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
#: 外資及陸資合計、投信、自營商合計、三大法人合計的「買賣超股數」位置
OTC_FOREIGN, OTC_TRUST, OTC_DEALER, OTC_TOTAL = 10, 13, 22, 23
OTC_COLUMNS = 24


def parse_otc_chips(payload: dict[str, Any], day: date) -> list[Chips]:
    """櫃買的三大法人買賣明細。"""
    tables = payload.get("tables") or []
    if not tables or not tables[0].get("data"):
        return []
    rows: list[Chips] = []
    for row in tables[0]["data"]:
        code = str(row[0]).strip()
        if not is_common_stock(code):
            continue
        if len(row) != OTC_COLUMNS:
            msg = f"上櫃三大法人的欄數變了:{len(row)} 欄"
            raise ValueError(msg)
        foreign, trust, dealer, total = (
            int(to_float(str(row[i])) or 0)
            for i in (OTC_FOREIGN, OTC_TRUST, OTC_DEALER, OTC_TOTAL)
        )
        if foreign + trust + dealer != total:
            msg = (
                f"上櫃三大法人的欄位順序變了:{code} {foreign}+{trust}+{dealer}≠{total}"
            )
            raise ValueError(msg)
        rows.append(
            Chips(
                day=day,
                code=code,
                name=str(row[1]).strip(),
                foreign=foreign,
                trust=trust,
                dealer=dealer,
            )
        )
    return rows


def fetch_otc_chips(
    day: date, cache_dir: Path, *, pause: float = 1.5
) -> dict[str, Any] | None:
    """抓一天的上櫃三大法人。沒有資料回 None;只有週末會記成空檔案。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"otc_{day:%Y%m%d}.json"
    if cached.exists():
        raw = cached.read_text(encoding="utf-8")
        return json.loads(raw) if raw.strip() else None
    url = f"{OTC_URL}?type=Daily&sect=EW&date={day:%Y/%m/%d}&response=json"
    req = urllib.request.Request(url, headers={"User-Agent": UA})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=60, context=TLS) as resp:  # noqa: S310
            payload: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError):
        time.sleep(pause * 4)
        raise
    time.sleep(pause)
    tables = payload.get("tables") or []
    if not tables or not tables[0].get("data"):
        if day.weekday() >= SATURDAY:
            cached.write_text("", encoding="utf-8")
        return None
    cached.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload
