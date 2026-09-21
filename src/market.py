"""大盤指數、漲跌停價、交易成本。

漲跌停不是單純的前收盤 ×1.1 —— 台股的價格只能落在特定檔位上,
所以要先算出檔位再取整。
"""

from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from pathlib import Path


#: 台股手續費(買賣各一次)加證交稅(賣出),來回總成本
#: 0.1425% × 2 + 0.3% = 0.585%。券商折扣另計,這裡用未折扣的保守值
ROUND_TRIP_COST_PCT = 0.585

#: 一般股票的漲跌幅限制
LIMIT_PCT = 0.10

#: (價格上界, 檔位)。價格落在哪一段就用那個檔位
TICKS: list[tuple[float, float]] = [
    (10, 0.01),
    (50, 0.05),
    (100, 0.1),
    (500, 0.5),
    (1000, 1.0),
    (float("inf"), 5.0),
]

INDEX_NAME = "發行量加權股價指數"

EXRIGHT_URL = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U"


def tick_size(price: float) -> float:
    """這個價位的最小跳動單位。"""
    for upper, tick in TICKS:
        if price < upper:
            return tick
    return TICKS[-1][1]


def _round_to_tick(price: float, *, up: bool) -> float:
    """取到合法檔位。漲停往下取、跌停往上取,才不會超出限制。"""
    tick = tick_size(price)
    steps = price / tick
    # 浮點誤差會讓 24.999999 這種值少一檔,先容忍一點點
    steps = steps + 1e-9 if up else steps - 1e-9
    n = int(steps) if up else int(steps) + (0 if steps == int(steps) else 1)
    return round(n * tick, 2)


def limit_up(prev_close: float) -> float:
    """漲停價。取不超過前收盤 ×1.1 的最高合法檔位。"""
    return _round_to_tick(prev_close * (1 + LIMIT_PCT), up=True)


def limit_down(prev_close: float) -> float:
    """跌停價。取不低於前收盤 ×0.9 的最低合法檔位。"""
    return _round_to_tick(prev_close * (1 - LIMIT_PCT), up=False)


def parse_index(payload: dict[str, Any]) -> float | None:
    """從當日行情的回應裡挑出加權指數收盤。"""
    for table in payload.get("tables") or []:
        fields = table.get("fields") or []
        if "指數" not in fields:
            continue
        for row in table.get("data") or []:
            if str(row[0]).strip() == INDEX_NAME:
                return float(str(row[1]).replace(",", ""))
    return None


def index_series(cache_dir: Path) -> dict[date, float]:
    """把快取裡每一天的加權指數收盤整理成一張表。不用重新下載。"""
    out: dict[date, float] = {}
    for path in sorted(cache_dir.glob("mi_index_*.json")):
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            continue  # 非交易日
        day_text = path.stem.removeprefix("mi_index_")
        close = parse_index(json.loads(raw))
        if close is not None:
            out[date(int(day_text[:4]), int(day_text[4:6]), int(day_text[6:]))] = close
    return out


def parse_exrights(payload: dict[str, Any]) -> set[tuple[date, str]]:
    """除權息的 (日期, 股票代號)。

    我們存的是未還原股價,除權息當天會出現斷崖式下跌 ——
    那不是真的跌,拿來算報酬會得到假的暴跌,所以要標出來。
    """
    out: set[tuple[date, str]] = set()
    for row in payload.get("data") or []:
        text = str(row[0]).strip()
        # 「114年01月02日」
        digits = "".join(c if c.isdigit() else " " for c in text).split()
        if len(digits) != DATE_PARTS_ROC:
            continue
        year, month, day = (int(x) for x in digits)
        out.add((date(year + 1911, month, day), str(row[1]).strip()))
    return out


#: 「114年01月02日」拆出來是三段數字
DATE_PARTS_ROC = 3
