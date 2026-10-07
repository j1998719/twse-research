"""融資融券餘額:上市(證交所 MI_MARGN)與上櫃(櫃買)。

單位一律是**張**,兩個來源本來就都是張。

證交所的表有兩組同名欄位(融資、融券都叫「買進、賣出、前日餘額、今日餘額」),
所以不能直接用欄名找。表格附了 groups(股票 2 欄、融資 6 欄、融券 6 欄),
這裡把它展開成「融資/今日餘額」這種完整名稱再找 —— 用位置寫死的話,
哪天證交所在前面多加一欄,融資和融券就會安靜地對調。

櫃買的欄名本身就分得開(「資餘額」「券餘額」),直接用名稱找。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.net import TLS
from src.prices import surely_closed, to_float
from src.tpex import is_common_stock


if TYPE_CHECKING:
    from datetime import date
    from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0"}
TWSE_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
OTC_URL = "https://www.tpex.org.tw/www/zh-tw/margin/balance"


@dataclass(frozen=True)
class Margin:
    """一檔股票一天收盤後的融資、融券餘額(張)。"""

    day: date
    code: str
    market: str
    margin: int
    short: int


def qualified_fields(table: dict[str, Any]) -> list[str]:
    """把 groups 展開,讓同名欄位分得開:「融資/今日餘額」「融券/今日餘額」。

    沒有 groups 的表就照原本的欄名。groups 的總寬度跟欄位數對不上時
    報錯,不要猜。
    """
    fields = [str(f).strip() for f in table.get("fields") or []]
    groups = table.get("groups")
    if not groups:
        return fields
    if sum(int(g.get("span") or 0) for g in groups) != len(fields):
        msg = f"欄位分組的寬度跟欄位數對不上:{groups} / {fields}"
        raise ValueError(msg)
    out: list[str] = []
    for group in groups:
        title = str(group.get("title") or "").strip()
        for _ in range(int(group["span"])):
            name = fields[len(out)]
            out.append(f"{title}/{name}" if title else name)
    return out


def _balance(row: list[Any], at: int) -> int:
    value = to_float(str(row[at]))
    return int(value) if value is not None else 0


def parse_twse(payload: dict[str, Any], day: date) -> list[Margin]:
    """證交所的融資融券彙總。個股在有「代號」那一張表,合計列會濾掉。"""
    for table in payload.get("tables") or []:
        fields = qualified_fields(table)
        if "股票/代號" in fields or "代號" in fields:
            break
    else:
        return []
    try:
        at_code = (
            fields.index("股票/代號") if "股票/代號" in fields else fields.index("代號")
        )
        at_margin = fields.index("融資/今日餘額")
        at_short = fields.index("融券/今日餘額")
    except ValueError:
        msg = f"上市融資融券的欄位變了:{fields}"
        raise ValueError(msg) from None
    return [
        Margin(
            day=day,
            code=str(row[at_code]).strip(),
            market="twse",
            margin=_balance(row, at_margin),
            short=_balance(row, at_short),
        )
        for row in table.get("data") or []
        if is_common_stock(str(row[at_code]))
    ]


def parse_otc(payload: dict[str, Any], day: date) -> list[Margin]:
    """櫃買的融資融券餘額。"""
    tables = payload.get("tables") or []
    if not tables or not tables[0].get("data"):
        return []
    fields = [str(f).strip() for f in tables[0].get("fields") or []]
    try:
        at_code = fields.index("代號")
        at_margin = fields.index("資餘額")
        at_short = fields.index("券餘額")
    except ValueError:
        msg = f"上櫃融資融券的欄位變了:{fields}"
        raise ValueError(msg) from None
    return [
        Margin(
            day=day,
            code=str(row[at_code]).strip(),
            market="otc",
            margin=_balance(row, at_margin),
            short=_balance(row, at_short),
        )
        for row in tables[0]["data"]
        if is_common_stock(str(row[at_code]))
    ]


def _has_data(payload: dict[str, Any], *, otc: bool) -> bool:
    if otc:
        tables = payload.get("tables") or []
        return bool(tables and tables[0].get("data"))
    return payload.get("stat") == "OK" and any(
        t.get("data") for t in payload.get("tables") or []
    )


def cached(
    day: date, cache_dir: Path, *, otc: bool, pause: float = 1.5
) -> dict[str, Any] | None:
    """抓一天並存快取。沒有資料回 None。

    沒有資料的日子只在**週末**記成空檔案。平日沒資料可能是國定假日,
    也可能是限流或暫時性錯誤,兩者長得一樣 —— 記下來就永遠不會再重試了
    (prices.fetch_day 的教訓)。
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{'otc' if otc else 'twse'}_{day:%Y%m%d}.json"
    if path.exists():
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw) if raw.strip() else None

    if otc:
        url = f"{OTC_URL}?date={day:%Y/%m/%d}&response=json"
    else:
        url = f"{TWSE_URL}?date={day:%Y%m%d}&selectType=STOCK&response=json"
    req = urllib.request.Request(url, headers=UA)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=60, context=TLS) as res:  # noqa: S310
            payload: dict[str, Any] = json.loads(res.read())
    except (urllib.error.URLError, TimeoutError):
        time.sleep(pause * 4)
        raise
    time.sleep(pause)

    if not _has_data(payload, otc=otc):
        if surely_closed(day):
            path.write_text("", encoding="utf-8")
        return None
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload
