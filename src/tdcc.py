"""集保股權分散表:千張大戶的每週人數與持股比例。

級距一律用文字認,不用分級編號 —— 有「差異數調整」那一列的週次,合計是
第 17 級,沒有的週次是第 16 級。寫死編號的話會安靜地把合計當成大戶。

查詢頁的 SYNCHRONIZER_TOKEN 是一次性的,所以每一筆都要重開一個 session。
這也決定了資料量的上限:一檔一週要兩個請求,全市場回溯完全不可行。
"""

from __future__ import annotations

import http.cookiejar
import itertools
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

QRY_URL = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
UA = {"User-Agent": "Mozilla/5.0"}

#: 千張大戶那一級的級距文字(1,000,001 股以上)
BIG_BAND = "1,000,001以上"
#: 合計那一列的級距文字裡會有這個字
TOTAL_MARK = "合"
#: 差異數調整那一列,人數欄是空的,要整列跳過
ADJUST_MARK = "調整"

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_TOKEN = re.compile(r'name="SYNCHRONIZER_TOKEN" value="([^"]*)"')
_DATE_OPTION = re.compile(r'<option[^>]*value="(\d{8})"')

#: 一列資料的欄數:分級、級距、人數、股數、佔比
ROW_CELLS = 5


@dataclass(frozen=True)
class Band:
    """一個持股級距在某一週的人數、股數與佔比。"""

    people: int
    shares: int
    pct: float


@dataclass(frozen=True)
class Week:
    """一檔股票某一週的股權分散情形。"""

    day: date
    code: str
    #: 級距文字 -> 該級距的數字。合計那一列的 key 是 "total"
    bands: dict[str, Band]

    @property
    def big(self) -> Band | None:
        """千張大戶。抓不到就是 None,不要假裝有。"""
        return self.bands.get(BIG_BAND)

    @property
    def holders(self) -> int | None:
        """總股東人數。大戶佔比要跟它一起看才知道是誰在接。"""
        total = self.bands.get("total")
        return None if total is None else total.people


def _text(cell: str) -> str:
    return _TAG.sub("", cell).replace("\xa0", " ").strip()


def _number(text: str) -> int | None:
    stripped = text.replace(",", "")
    return int(stripped) if stripped.lstrip("-").isdigit() else None


def parse_bands(html: str) -> dict[str, Band]:
    """把查詢結果的表格讀成「級距文字 -> 數字」。

    只認五欄、第一欄是分級編號的那些列。編號本身丟掉不用,因為它會隨著
    有沒有「差異數調整」那一列而整體位移。
    """
    bands: dict[str, Band] = {}
    for row in _ROW.findall(html):
        cells = [_text(c) for c in _CELL.findall(row)]
        if len(cells) != ROW_CELLS or not cells[0].isdigit():
            continue
        label = cells[1]
        if ADJUST_MARK in label:
            continue
        people = _number(cells[2])
        shares = _number(cells[3])
        if people is None or shares is None:
            continue
        key = "total" if TOTAL_MARK in label else label
        bands[key] = Band(people=people, shares=shares, pct=float(cells[4]))
    return bands


def available_weeks() -> list[date]:
    """查詢頁目前提供的資料日期。約 52 週,再往前就沒有了。"""
    req = urllib.request.Request(QRY_URL, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as res:  # noqa: S310
        html = res.read().decode("utf-8", "replace")
    return [_as_date(s) for s in _DATE_OPTION.findall(html)]


def _as_date(stamp: str) -> date:
    return date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))


def _stamp(day: date) -> str:
    return f"{day.year:04d}{day.month:02d}{day.day:02d}"


def fetch_week(day: date, code: str) -> Week:
    """抓一檔股票某一週的股權分散表。

    每次都重開 session:SYNCHRONIZER_TOKEN 用過就失效,沿用舊 token 的話
    伺服器會回一張空表,而不是回錯誤 —— 安靜地少掉一整週的資料。
    """
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    with opener.open(urllib.request.Request(QRY_URL, headers=UA), timeout=40) as res:
        html = res.read().decode("utf-8", "replace")
    match = _TOKEN.search(html)
    if match is None:
        msg = "查詢頁上找不到 SYNCHRONIZER_TOKEN,版面可能改了"
        raise ValueError(msg)
    form = {
        "SYNCHRONIZER_TOKEN": match.group(1),
        "SYNCHRONIZER_URI": "/portal/zh/smWeb/qryStock",
        "method": "submit",
        "firDate": "",
        "sqlMethod": "StockNo",
        "stockName": "",
        "scaDate": _stamp(day),
        "stockNo": code,
    }
    request = urllib.request.Request(
        QRY_URL, data=urllib.parse.urlencode(form).encode(), headers=UA
    )
    with opener.open(request, timeout=60) as res:
        body = res.read().decode("utf-8", "replace")
    return Week(day=day, code=code, bands=parse_bands(body))


@dataclass(frozen=True)
class Change:
    """相鄰兩週之間,千張大戶的變化。"""

    day: date
    people: int
    #: 人數比上一週多幾個。可能是負的
    people_delta: int
    pct: float
    #: 持股佔比比上一週多幾個百分點
    pct_delta: float
    holders: int | None


def weekly_changes(weeks: Iterable[Week]) -> list[Change]:
    """把週資料串成變化量。第一週沒有前一週可比,不會出現在結果裡。"""
    usable = [w for w in sorted(weeks, key=lambda w: w.day) if w.big is not None]
    out: list[Change] = []
    for prev, now in itertools.pairwise(usable):
        big = now.big
        before = prev.big
        if big is None or before is None:  # pragma: no cover - 上面已經濾掉
            continue
        out.append(
            Change(
                day=now.day,
                people=big.people,
                people_delta=big.people - before.people,
                pct=big.pct,
                pct_delta=round(big.pct - before.pct, 2),
                holders=now.holders,
            )
        )
    return out


def rising(changes: Sequence[Change], min_people: int = 1) -> list[Change]:
    """人數增加到門檻以上的那些週,也就是「大戶開始變多」的候選事件。"""
    return [c for c in changes if c.people_delta >= min_people]
