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
import re
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from src.net import TLS
from src.prices import TAIPEI, to_float


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

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
    with urllib.request.urlopen(request, timeout=60, context=TLS) as res:  # noqa: S310
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


def cached_quotes(
    day: date, cache_dir: Path, *, pause: float = 1.0
) -> dict[str, Any] | None:
    """抓一天並存快取。非交易日回 None,而且**空檔案也會留下**。

    留空檔案是為了讓非交易日也算「處理過」—— 不留的話每次重跑都會再問一次
    那些永遠沒有資料的日子,七年下來是幾百個白費的請求。

    但空檔案只有在**那一天過完之後**寫的才可信:當天(或更早)問的時候還沒收盤,
    回應本來就是空的。2026-10-07 00:58 就這樣存了一個空檔,10-07 的上櫃行情
    之後永遠不會再抓(#37)。所以當天寫的空檔案當作沒抓過,重抓。
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"otc_{day:%Y%m%d}.json"
    if cached.exists():
        raw = cached.read_text(encoding="utf-8")
        if raw.strip():
            hit: dict[str, Any] = json.loads(raw)
            return hit
        written = datetime.fromtimestamp(cached.stat().st_mtime, tz=TAIPEI).date()
        if written > day:
            return None

    payload = fetch_quotes(day)
    _fields, data = _rows(payload)
    if not data:
        cached.write_text("", encoding="utf-8")
        time.sleep(pause)
        return None
    cached.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    time.sleep(pause)
    return payload


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
    # 每一個下游會用到的欄位都要檢查。原本只驗證證券代號,而「處置內容」
    # 被改名的話後果最嚴重:detail 變空字串,每一筆都被判成第一次處置,
    # 列數不變、也不會報錯,第二次處置的分組就這樣安靜消失
    needed = (
        "公布日期",
        "證券代號",
        "證券名稱",
        "處置起訖時間",
        "處置原因",
        "處置內容",
    )
    missing = [name for name in needed if name not in at]
    if missing:
        msg = f"上櫃處置公告缺欄位 {missing}:{fields}"
        raise ValueError(msg)
    for row in data:
        code = str(row[at["證券代號"]]).strip()
        if not is_common_stock(code):
            continue
        yield {name: str(row[i]).strip() for name, i in at.items() if name}


# --- 正規化成和上市同一個形狀 ---
#
# 兩個市場的公告格式不一樣,但研究要把它們放在一起,所以上櫃要轉成 twse.Punish
# 的欄位。差別最大的是「第幾次處置」:
#
# * 上市:寫在「處置措施」欄,文字就是「第一次處置」「第二次處置」
# * 上櫃:沒有那個欄位。重複處置寫在處置內容的文字裡 ——
#   「最近30個營業日內曾發布處置」
#
# 實測上櫃有 36.8% 帶那句話,和上市的 34% 第二次處置率很接近,互相印證。
#
# **「累計」那一欄兩邊都不能當次數。** 它是相對查詢區間算的,換個區間就變。

#: 上櫃版的「第二次(含)以上」。上市是在處置措施欄寫「第二次處置」
REPEAT_MARK = "最近30個營業日內曾發布處置"
#: 不編號的措施。上市把這類寫成「人工管制撮合」並給 nth=0,研究會排除它們;
#: 上櫃沒有措施欄,但這個條文引用把兩群分得乾乾淨淨 —— 實測 187 列全部有、
#: 另外 1,632 列全部沒有(撮合間隔也跟著分開:10/25/45/60 分鐘 vs 5/20/2)。
#:
#: 這一類本身沒有訊號(n=106、中位數 +0.50%、勝率 52.8%、p=0.60),所以把它
#: 當成第一次處置收進來,等於用 106 筆雜訊稀釋自己的發現。而且更糟的是:
#: 上市對應的 102 列因為 nth=0 被排除,兩邊的納入規則會不一樣。
UNNUMBERED_MARK = "業務規則第12條"
#: 處置期間的格式:115/09/23~115/10/05
PERIOD_SEP = "~"
#: 這個來源的文字欄位會夾帶相對連結,例如
#: 「豪勉(../../mainboard/listed/company-detail.html?code=6218)」。
#: 不清掉的話股票名稱會帶著一串路徑,而且欄位一樣長不出錯
_LINK = re.compile(r"\s*\([./][^)]*\)")


def clean_text(value: str) -> str:
    """去掉夾帶的相對連結與前後空白。"""
    return _LINK.sub("", value or "").strip()


def roc_to_date(stamp: str) -> date | None:
    """民國日期轉西元。格式不對回 None。

    年份上限要檢查:西元年份被當成民國會算出 2026+1911=3937 這種值,
    而且完全不會報錯([#13] 踩過)。
    """
    parts = stamp.strip().split("/")
    if len(parts) != ROC_PARTS:
        return None
    try:
        year, month, day = (int(p) for p in parts)
    except ValueError:
        return None
    if not 1 <= year <= ROC_YEAR_MAX:
        return None
    try:
        return date(year + 1911, month, day)
    except ValueError:
        return None


#: 民國日期的欄位數:年/月/日
ROC_PARTS = 3
#: 民國年的合理上限。超過就是有人把西元年當民國年傳進來了
ROC_YEAR_MAX = 200


def normalise(row: dict[str, str]) -> dict[str, object] | None:
    """一列上櫃處置公告轉成和上市 Punish 一樣的欄位。

    解不出日期就回 None —— 猜一個日期比少一筆事件糟得多。
    """
    period = row.get("處置起訖時間", "")
    if PERIOD_SEP not in period:
        return None
    head, tail = period.split(PERIOD_SEP, 1)
    start, end = roc_to_date(head), roc_to_date(tail)
    announced = roc_to_date(row.get("公布日期", ""))
    if start is None or end is None or announced is None or end < start:
        return None
    detail = clean_text(row.get("處置內容", ""))
    return {
        "announced": announced,
        "code": clean_text(row.get("證券代號", "")),
        "name": clean_text(row.get("證券名稱", "")),
        # 上櫃沒有「第幾次處置」欄,次數要從文字認。不編號的措施給 0,
        # 跟上市一致 —— 研究會用 nth > 0 篩掉它們
        "nth": _nth_of(detail),
        "measure": _measure_of(detail),
        "condition": clean_text(row.get("處置原因", "")),
        "start": start,
        "end": end,
        "detail": detail,
        "market": "otc",
    }


def _nth_of(detail: str) -> int:
    """從處置內容的文字判斷第幾次處置。不編號的措施回 0。"""
    if UNNUMBERED_MARK in detail:
        return 0
    return 2 if REPEAT_MARK in detail else 1


def _measure_of(detail: str) -> str:
    """對應上市「處置措施」欄的文字。"""
    if UNNUMBERED_MARK in detail:
        return "人工管制撮合"
    return "第二次處置" if REPEAT_MARK in detail else "第一次處置"
