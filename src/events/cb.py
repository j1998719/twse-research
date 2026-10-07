"""可轉債條款的事件來源(#26):賣回事件(H1、H2)與轉換起日事件(H3)。

一個事件 = 看板上的一對 (債券, 錨點日期)。錨點是 `最近賣回權起日`(賣回事件)
或 `轉換起日`(轉換事件),原點 happened 就是那個日期。

**knowable = 這一對第一次出現在看板上的那一天。** 嚴格說條款在發行時就寫在
「發行及轉換辦法」裡公告了,所以真正可知的日子更早;但看板只掛「最近一次」
的賣回權(第三輪),第一次出現是這份資料唯一證得出來的東西。用它會讓框架的
守衛(進場必須嚴格晚於 knowable)更嚴 —— 保守的方向。

**事件存在性是 point-in-time 的**(第三輪登記的定義):錨點 T 之前最後一份
看板上,這檔債必須已經掛著同一個錨點。不用最新一份看板回頭判斷哪些債存在過,
也不收「T 當天或之後才第一次出現」的那種 —— 那時候已經沒人來得及進場。

標的股代號 = 債券代碼前四碼(`Bond.underlying`)。

樣本外切法(第七輪,跑之前定案):發行年份的代理 = 轉換起日往前推三個月的
年份;代理年份 ≤ 2021(含 2017 以前發行的)是形成組,2022 起是驗證組。
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from src.study import Event


if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from src.cbboard import Board, Bond

#: 錨點欄位:賣回權起日或轉換起日
Anchor = Literal["put_start", "conversion_start"]
#: 形成組的最後一個代理發行年份(第七輪)
FORMATION_LAST_YEAR = 2021
#: 轉換起日通常在發行後三個月:一到三月的轉換起日,發行是在前一年
LAG_MONTHS = 3


@dataclass(frozen=True)
class Sighting:
    """一對 (債券, 錨點) 在看板上被看到的情形。"""

    bond: str
    anchor: date
    first_seen: date
    #: 錨點之前最後一份看板上,這檔債掛著同一個錨點
    on_eve: bool


def sightings(boards: Sequence[Board], field: Anchor) -> list[Sighting]:
    """每一對 (債券, 錨點) 第一次出現的日子,以及錨點前夕是否看得到。

    boards 要由舊到新排好。
    """
    first: dict[tuple[str, date], date] = {}
    present: list[set[tuple[str, date]]] = []
    for board in boards:
        today: set[tuple[str, date]] = set()
        for b in board.bonds:
            anchor = getattr(b, field)
            if anchor is not None:
                today.add((b.code, anchor))
                first.setdefault((b.code, anchor), board.day)
        present.append(today)
    days = [board.day for board in boards]
    out = []
    for (code, anchor), seen in first.items():
        eve = bisect.bisect_left(days, anchor) - 1
        out.append(
            Sighting(
                bond=code,
                anchor=anchor,
                first_seen=seen,
                on_eve=eve >= 0 and (code, anchor) in present[eve],
            )
        )
    return sorted(out, key=lambda s: (s.anchor, s.bond))


@dataclass(frozen=True)
class Tally:
    """事件配對的分層計數,跟第六輪的表同一套定義。"""

    #: 所有出現過的 (債, 錨點) 配對
    pairs: int
    #: 錨點落在檔案庫期間內(第一份到最後一份看板之間,含)
    within: int
    #: 期間內、但第一次看到就是檔案庫第一天(真正第一次出現的日子不知道)
    left_censored: int
    #: 期間內、而且錨點前一份看板上就看得到 —— 事件的定義
    on_eve: int
    #: 期間內、但錨點當天或之後才第一次出現(前置期 ≤ 0)
    late: int


def tally(found: Sequence[Sighting], boards: Sequence[Board]) -> Tally:
    """分層數一數。"""
    lo, hi = boards[0].day, boards[-1].day
    within = [s for s in found if lo <= s.anchor <= hi]
    return Tally(
        pairs=len(found),
        within=len(within),
        left_censored=sum(1 for s in within if s.first_seen == lo),
        on_eve=sum(1 for s in within if s.on_eve),
        late=sum(1 for s in within if s.first_seen >= s.anchor),
    )


def conversion_starts(boards: Sequence[Board]) -> dict[str, date]:
    """每檔債的轉換起日,取第一次看到的那個值(point-in-time)。"""
    out: dict[str, date] = {}
    for board in boards:
        for b in board.bonds:
            if b.conversion_start is not None:
                out.setdefault(b.code, b.conversion_start)
    return out


def issue_year(conversion_start: date | None) -> int | None:
    """發行年份的代理:轉換起日往前推三個月的年份(第七輪)。"""
    if conversion_start is None:
        return None
    if conversion_start.month <= LAG_MONTHS:
        return conversion_start.year - 1
    return conversion_start.year


def sample(year: int | None) -> str | None:
    """代理年份 → 形成組或驗證組。沒有轉換起日的債不歸任何一組。"""
    if year is None:
        return None
    return "formation" if year <= FORMATION_LAST_YEAR else "validation"


def events(found: Sequence[Sighting], boards: Sequence[Board]) -> list[Event]:
    """錨點在檔案庫期間內、而且前夕看得到的配對 → Event。

    原點是錨點日期,knowable 是第一次出現的那份看板的日期。
    """
    lo, hi = boards[0].day, boards[-1].day
    starts = conversion_starts(boards)
    out = []
    for s in found:
        if not (lo <= s.anchor <= hi and s.on_eve):
            continue
        year = issue_year(starts.get(s.bond))
        out.append(
            Event(
                code=s.bond[:4],
                happened=s.anchor,
                knowable=s.first_seen,
                tags={"bond": s.bond, "issue_year": year, "sample": sample(year)},
            )
        )
    return out


class Ledger:
    """每檔債逐日的看板列,用來查「某一天看得到的條款」。"""

    def __init__(self, boards: Sequence[Board]) -> None:
        """Boards 要由舊到新排好。"""
        self._days: dict[str, list[date]] = {}
        self._rows: dict[str, list[Bond]] = {}
        for board in boards:
            for b in board.bonds:
                self._days.setdefault(b.code, []).append(board.day)
                self._rows.setdefault(b.code, []).append(b)

    def _upto(self, code: str, day: date) -> int:
        """當天或之前最近一份看板的位置 + 1(0 代表沒有)。"""
        return bisect.bisect_right(self._days.get(code, []), day)

    def as_of(self, code: str, day: date) -> Bond | None:
        """當天或之前最近一份看板上的這檔債。"""
        at = self._upto(code, day)
        return self._rows[code][at - 1] if at else None

    def conversion_price(self, code: str, day: date) -> float | None:
        """那一天**實際有效**的轉換價格。

        看板 GLOSS 註2:「轉換價格係指下次轉換價格生效日後之轉換價格,不是為
        目前之轉換價格」。所以重設公告之後、生效之前,看板上掛的是還沒生效的
        新價格。往回找最近一份「生效日不晚於這一天」的看板,用它的價格。

        生效日空白的當成已經生效。找不到就回 None —— 不拿未生效的價格湊數。
        """
        rows = self._rows.get(code, [])
        for i in range(self._upto(code, day) - 1, -1, -1):
            row = rows[i]
            if row.next_reset is None or row.next_reset <= day:
                return row.conversion_price
        return None
