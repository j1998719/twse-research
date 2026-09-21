"""證交所注意股／處置股公告抓取與解析。

資料來源是證交所的公開 JSON API,不需要帳號。日期用民國年,要轉成西元。
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

NOTICE_URL = "https://www.twse.com.tw/rwd/zh/announcement/notice"
PUNISH_URL = "https://www.twse.com.tw/rwd/zh/announcement/punish"

# 上市普通股是四位數字且不以 00 開頭;
# 00 開頭的四位數是 ETF(0050、0056),權證是六位數,特別股帶英文字母
COMMON_STOCK = re.compile(r"^(?!00)\d{4}$")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def roc_to_date(text: str) -> date:
    """民國日期轉西元。接受 "115.08.04" 與 "115/08/21" 兩種寫法。"""
    parts = re.split(r"[./-]", text.strip())
    if len(parts) != 3:
        msg = f"看不懂的日期:{text!r}"
        raise ValueError(msg)
    year, month, day = (int(p) for p in parts)
    # 民國年不可能有四位數。擋住西元日期被當成民國年默默算出 3937 年
    if year >= 1000:
        msg = f"看不懂的日期,這像是西元不是民國:{text!r}"
        raise ValueError(msg)
    return date(year + 1911, month, day)


def is_common_stock(code: str) -> bool:
    return bool(COMMON_STOCK.match(code.strip()))


def fetch(
    url: str, start: date, end: date, cache_dir: Path | None = None
) -> dict[str, Any]:
    """打一次 API。給 cache_dir 的話會把原始回應存下來,重跑時直接讀檔。"""
    params = f"?startDate={start:%Y%m%d}&endDate={end:%Y%m%d}&response=json"
    name = f"{Path(url).name}_{start:%Y%m%d}_{end:%Y%m%d}.json"

    if cache_dir is not None:
        cached = cache_dir / name
        if cached.exists():
            # json.loads 回傳 Any,要標出型別才通得過 mypy strict
            hit: dict[str, Any] = json.loads(cached.read_text(encoding="utf-8"))
            return hit

    req = urllib.request.Request(url + params, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload: dict[str, Any] = json.loads(resp.read().decode("utf-8"))

    if payload.get("stat") != "OK":
        msg = f"API 回傳異常:{payload.get('stat')}"
        raise RuntimeError(msg)

    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    time.sleep(1)  # 對證交所客氣一點
    return payload


@dataclass(frozen=True)
class Notice:
    """一次注意股公布。"""

    day: date
    code: str
    name: str
    reason: str
    close: str
    per: str


@dataclass(frozen=True)
class Punish:
    """一次處置公告。"""

    announced: date
    code: str
    name: str
    nth: int
    condition: str
    start: date
    end: date
    measure: str
    detail: str = field(repr=False)


def parse_notices(payload: dict[str, Any], *, common_only: bool = True) -> list[Notice]:
    rows: list[Notice] = []
    for row in payload.get("data") or []:
        code = str(row[1]).strip()
        if common_only and not is_common_stock(code):
            continue
        rows.append(
            Notice(
                day=roc_to_date(str(row[5])),
                code=code,
                name=str(row[2]).strip(),
                reason=str(row[4]).strip(),
                close=str(row[6]).strip(),
                per=str(row[7]).strip(),
            )
        )
    return rows


def parse_period(text: str) -> tuple[date, date]:
    """ "115/08/24～115/08/28" -> (起, 迄)。單日的話起迄相同。"""
    parts = re.split(r"[~～]", text.strip())
    first = roc_to_date(parts[0])
    last = roc_to_date(parts[1]) if len(parts) > 1 else first
    return first, last


def parse_punishes(
    payload: dict[str, Any], *, common_only: bool = True
) -> list[Punish]:
    rows: list[Punish] = []
    for row in payload.get("data") or []:
        code = str(row[2]).strip()
        if common_only and not is_common_stock(code):
            continue
        start, end = parse_period(str(row[6]))
        rows.append(
            Punish(
                announced=roc_to_date(str(row[1])),
                code=code,
                name=str(row[3]).strip(),
                nth=int(row[4]),
                condition=str(row[5]).strip(),
                start=start,
                end=end,
                measure=str(row[7]).strip(),
                detail=str(row[8]).strip(),
            )
        )
    return rows
