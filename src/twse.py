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

#: 民國日期是「年 月 日」三段
DATE_PARTS = 3
#: 民國年不可能有四位數;超過就是誤傳了西元
ROC_YEAR_MAX = 999

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def roc_to_date(text: str) -> date:
    """民國日期轉西元。接受 "115.08.04" 與 "115/08/21" 兩種寫法。"""
    parts = re.split(r"[./-]", text.strip())
    if len(parts) != DATE_PARTS:
        msg = f"看不懂的日期:{text!r}"
        raise ValueError(msg)
    year, month, day = (int(p) for p in parts)
    # 民國年不可能有四位數。擋住西元日期被當成民國年默默算出 3937 年
    if year > ROC_YEAR_MAX:
        msg = f"看不懂的日期,這像是西元不是民國:{text!r}"
        raise ValueError(msg)
    return date(year + 1911, month, day)


def is_common_stock(code: str) -> bool:
    """是不是上市普通股。ETF、權證、特別股都會回 False。"""
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

    # S310:網址由本模組的常數拼成,不是外部輸入,沒有 file: 之類的風險
    req = urllib.request.Request(url + params, headers={"User-Agent": UA})  # noqa: S310
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
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


# 「處置措施」欄的文字 -> 第幾次處置。「人工管制撮合」是另一種措施,不編號。
NTH_BY_MEASURE = {"第一次處置": 1, "第二次處置": 2}


def nth_of(measure: str) -> int:
    """第幾次處置;不是編號型措施(例如人工管制撮合)回 0。"""
    return NTH_BY_MEASURE.get(measure.strip(), 0)


@dataclass(frozen=True)
class Punish:
    """一次處置公告。"""

    announced: date
    code: str
    name: str
    #: 第幾次處置,取自「處置措施」。
    #: 注意:API 另有「累計」欄,那個值是相對於查詢區間算的,換個區間就變,不可用。
    nth: int
    measure: str
    condition: str
    start: date
    end: date
    detail: str = field(repr=False)


def parse_notices(payload: dict[str, Any], *, common_only: bool = True) -> list[Notice]:
    """把注意股 API 的回應轉成 Notice。"""
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
    """把「115/08/24～115/08/28」拆成起訖兩個日期。單日的話起迄相同。"""
    parts = re.split(r"[~～]", text.strip())
    first = roc_to_date(parts[0])
    last = roc_to_date(parts[1]) if len(parts) > 1 else first
    return first, last


def parse_punishes(
    payload: dict[str, Any], *, common_only: bool = True
) -> list[Punish]:
    """把處置股 API 的回應轉成 Punish。"""
    rows: list[Punish] = []
    for row in payload.get("data") or []:
        code = str(row[2]).strip()
        if common_only and not is_common_stock(code):
            continue
        start, end = parse_period(str(row[6]))
        measure = str(row[7]).strip()
        rows.append(
            Punish(
                announced=roc_to_date(str(row[1])),
                code=code,
                name=str(row[3]).strip(),
                nth=nth_of(measure),
                measure=measure,
                condition=str(row[5]).strip(),
                start=start,
                end=end,
                detail=str(row[8]).strip(),
            )
        )
    return rows
