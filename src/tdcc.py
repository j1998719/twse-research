"""集保股權分散表:千張大戶的每週人數與持股比例。

級距一律用文字認,不用分級編號 —— 有「差異數調整」那一列的週次,合計是
第 17 級,沒有的週次是第 16 級。寫死編號的話會安靜地把合計當成大戶。

查詢頁的 SYNCHRONIZER_TOKEN 是一次性的,所以每一筆都要重開一個 session。
這也決定了資料量的上限:一檔一週要兩個請求,全市場回溯完全不可行。
"""

from __future__ import annotations

import csv
import http.cookiejar
import io
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
#: 全市場快照。一個請求就拿到所有股票,但只有最新一週
SNAPSHOT_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
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


# --- 集中度 ---
#
# 千張這個門檻跨股不可比:同樣持有 1,000 張,在台積電是股本的 0.0039%,
# 在中位數的公司是 1.285%,差 83 倍(5%-95% 區間)。集中度指標只吃比例,
# 所以尺度無關。
#
# 但沒有個人層級的持股資料,只有級距,所以得假設同一級距內每個人持股相同。


def _holdings(week: Week) -> list[tuple[int, float]]:
    """每個級距的 (人數, 佔全體的比例)。合計那一列和空級距都排除。"""
    return [
        (band.people, band.pct / 100)
        for key, band in week.bands.items()
        if key != "total" and band.people > 0 and band.pct > 0
    ]


def herfindahl(week: Week) -> float | None:
    """股權集中度(HHI)。抓不到任何級距時回 None。

    假設同一級距內每個人持股相同,所以每人佔比是「該級佔比 / 該級人數」:

        HHI = Σ 該級人數 × (該級佔比 / 該級人數)² = Σ (該級佔比)² / 該級人數

    級距內均分會讓平方和最小(Jensen),所以這是真實 HHI 的**下界** ——
    是個保守估計。

    注意這個數字會被最高的級距主導(穩懋是 97.4% 來自千張以上那一級),
    所以它擺脫了「張數」這個絕對量,但沒有完全擺脫級距邊界。要看整條
    分布的話用 gini()。
    """
    parts = _holdings(week)
    if not parts:
        return None
    return sum(pct * pct / people for people, pct in parts)


def effective_holders(week: Week) -> float | None:
    """等效持有人數 = 1 / HHI。

    「如果股權由 N 個人平分,集中度會一樣」的那個 N。比 HHI 好讀:
    穩懋有 125,535 個股東,但等效持有人數只有 189 人。
    """
    hhi = herfindahl(week)
    if hhi is None or hhi <= 0:
        return None
    return 1 / hhi


def gini(week: Week) -> float | None:
    """股權分配的 Gini 係數,0 是完全平均、1 是完全集中。

    用級距的 Lorenz 曲線梯形法算。跟 HHI 不同,權重分布在整條曲線上,
    不會被單一級距吃掉 —— 所以對級距邊界的敏感度低得多。

    級距要由小排到大,用「該級平均每人持股」排序,而不是用級距編號 ——
    編號的順序在兩個來源之間不一致(見檔頭)。
    """
    parts = _holdings(week)
    if not parts:
        return None
    parts.sort(key=lambda x: x[1] / x[0])
    total_people = sum(people for people, _ in parts)
    if total_people == 0:
        return None
    cum_people = 0.0
    cum_share = 0.0
    area = 0.0
    for people, pct in parts:
        next_people = cum_people + people / total_people
        next_share = cum_share + pct
        # 梯形面積:寬 × 兩邊高的平均
        area += (next_people - cum_people) * (next_share + cum_share)
        cum_people, cum_share = next_people, next_share
    # cum_share 理論上是 1,但集保的佔比是四捨五入過的,所以正規化一次
    return 1 - area / cum_share if cum_share > 0 else None


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


# --- 全市場快照 ---
#
# 這個 feed 跟上面的查詢頁是兩套格式,不要混用假設:
#  * 分級編號在這裡是固定的 —— 每一檔都剛好 17 列,16 永遠是差異數調整
#    (沒有調整時就是 0),17 永遠是合計。查詢頁則是沒有調整那一列時合計變 16。
#  * 證券代號有空白補齊("3105  "),不 strip 的話查不到任何一檔。
#  * 涵蓋上市與上櫃(約 4,000 檔),比我們的價格資料(僅上市 1,127 檔)寬。

#: 全市場快照裡,千張大戶固定是這一級
SNAPSHOT_BIG_LEVEL = 15
#: 合計固定是這一級
SNAPSHOT_TOTAL_LEVEL = 17


def parse_snapshot(text: str) -> dict[str, dict[int, Band]]:
    """把全市場快照的 CSV 讀成「證券代號 -> 分級 -> 數字」。

    代號會去掉補齊的空白。
    """
    out: dict[str, dict[int, Band]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        code = (row.get("證券代號") or "").strip()
        level = _number(row.get("持股分級") or "")
        people = _number(row.get("人數") or "")
        shares = _number(row.get("股數") or "")
        if not code or level is None or people is None or shares is None:
            continue
        pct = row.get("占集保庫存數比例%") or "0"
        out.setdefault(code, {})[level] = Band(
            people=people, shares=shares, pct=float(pct)
        )
    return out


def snapshot_day(text: str) -> date | None:
    """快照的資料日期。空檔案回 None。"""
    for row in csv.DictReader(io.StringIO(text)):
        stamp = (row.get("資料日期") or "").strip()
        if len(stamp) == len("20260924") and stamp.isdigit():
            return _as_date(stamp)
    return None


def fetch_snapshot() -> str:
    """抓全市場快照的原始 CSV。一週一次就夠,只有最新一週。"""
    req = urllib.request.Request(SNAPSHOT_URL, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as res:  # noqa: S310
        body: bytes = res.read()
    return body.decode("utf-8-sig", "replace")
