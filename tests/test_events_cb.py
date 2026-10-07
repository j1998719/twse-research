"""可轉債的事件建構:point-in-time 的賣回事件與轉換起日事件(#26)。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from src.cbboard import Board, Bond
from src.events.cb import (
    FORMATION_LAST_YEAR,
    Ledger,
    conversion_starts,
    events,
    issue_year,
    sample,
    sightings,
    tally,
)


def bond(code: str = "53887", **kw: object) -> Bond:
    base = Bond(
        code=code,
        name="測試",
        conversion_start=date(2024, 3, 7),
        conversion_end=None,
        conversion_price=100.0,
        next_reset=date(2024, 3, 7),
        put_start=None,
        put_end=None,
        put_price=None,
        call_start=None,
        call_end=None,
        call_price=None,
        delisted=None,
        issued=1_000_000_000,
        outstanding=1_000_000_000,
        reference_price=None,
        stock_price=None,
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def board(day: date, *bonds: Bond) -> Board:
    return Board(day=day, bonds=bonds)


PUT = date(2026, 10, 28)

#: 賣回日 2026-10-28 在 09-29 第一次出現(第四輪實測的那一檔)
BOARDS = [
    board(date(2026, 9, 1), bond(), bond("11011", put_start=date(2026, 9, 1))),
    board(date(2026, 9, 28), bond()),
    board(date(2026, 9, 29), bond(put_start=PUT)),
    board(date(2026, 10, 27), bond(put_start=PUT)),
    board(date(2026, 10, 28), bond(put_start=PUT)),
]


class TestSightings:
    def test_第一次出現就是_knowable(self) -> None:
        got = {(s.bond, s.anchor): s for s in sightings(BOARDS, "put_start")}
        seen = got["53887", PUT]
        assert seen.first_seen == date(2026, 9, 29)
        assert seen.on_eve is True

    def test_前一份看板上沒有就不算_on_eve(self) -> None:
        # 賣回日當天才第一次出現 —— 那一天之前沒人看得到
        boards = [
            board(date(2026, 10, 27), bond()),
            board(date(2026, 10, 28), bond(put_start=PUT)),
        ]
        (seen,) = sightings(boards, "put_start")
        assert seen.first_seen == PUT
        assert seen.on_eve is False

    def test_前一份看板上是別的賣回日也不算(self) -> None:
        boards = [
            board(date(2026, 9, 29), bond(put_start=PUT)),
            board(date(2026, 10, 27), bond(put_start=date(2026, 11, 3))),
            board(date(2026, 10, 28), bond(put_start=PUT)),
        ]
        got = {s.anchor: s for s in sightings(boards, "put_start")}
        assert got[PUT].on_eve is False

    def test_空白不是事件(self) -> None:
        got = sightings(BOARDS, "put_start")
        assert all(s.anchor is not None for s in got)
        assert {s.bond for s in got} == {"53887", "11011"}


class TestTally:
    def test_分層計數(self) -> None:
        got = tally(sightings(BOARDS, "put_start"), BOARDS)
        # 11011 那一對的錨點就是檔案庫第一天,算在期間內但左設限
        assert got.pairs == 2
        assert got.within == 2
        assert got.left_censored == 1
        assert got.on_eve == 1
        assert got.late == 1


class TestEvents:
    def test_事件的原點與_knowable(self) -> None:
        (event,) = events(sightings(BOARDS, "put_start"), BOARDS)
        assert event.code == "5388"
        assert event.happened == PUT
        assert event.knowable == date(2026, 9, 29)
        assert event.tags["bond"] == "53887"
        assert event.tags["issue_year"] == 2023

    def test_錨點在檔案庫之後的不算(self) -> None:
        boards = [board(date(2026, 9, 29), bond(put_start=PUT))]
        assert events(sightings(boards, "put_start"), boards) == []


class TestIssueYear:
    @pytest.mark.parametrize(
        ("start", "year"),
        [
            (date(2022, 3, 31), 2021),
            (date(2022, 4, 1), 2022),
            (date(2022, 1, 5), 2021),
            (date(2021, 12, 31), 2021),
        ],
    )
    def test_轉換起日往前推三個月(self, start: date, year: int) -> None:
        assert issue_year(start) == year

    def test_沒有轉換起日(self) -> None:
        assert issue_year(None) is None

    def test_形成組與驗證組(self) -> None:
        assert FORMATION_LAST_YEAR == 2021
        assert sample(2016) == "formation"
        assert sample(2021) == "formation"
        assert sample(2022) == "validation"
        assert sample(None) is None


def test_轉換起日取第一次看到的那個() -> None:
    boards = [
        board(date(2020, 1, 2), bond("1", conversion_start=date(2020, 4, 1))),
        board(date(2020, 1, 3), bond("1", conversion_start=date(2020, 4, 2))),
    ]
    assert conversion_starts(boards) == {"1": date(2020, 4, 1)}


class TestLedger:
    """GLOSS 註2:看板的轉換價格是「下次轉換價格生效日」之後的價格。"""

    BOARDS = (
        board(
            date(2026, 6, 1), bond(conversion_price=50.0, next_reset=date(2025, 7, 1))
        ),
        # 6/10 公告重設,6/20 生效:6/10–6/19 看板上的 45 還沒生效
        board(
            date(2026, 6, 10), bond(conversion_price=45.0, next_reset=date(2026, 6, 20))
        ),
        board(
            date(2026, 6, 19), bond(conversion_price=45.0, next_reset=date(2026, 6, 20))
        ),
        board(
            date(2026, 6, 22), bond(conversion_price=45.0, next_reset=date(2026, 6, 20))
        ),
    )

    def test_生效日還沒到就用前一個價格(self) -> None:
        ledger = Ledger(self.BOARDS)
        assert ledger.conversion_price("53887", date(2026, 6, 10)) == 50.0
        assert ledger.conversion_price("53887", date(2026, 6, 19)) == 50.0

    def test_生效之後用新價格(self) -> None:
        ledger = Ledger(self.BOARDS)
        assert ledger.conversion_price("53887", date(2026, 6, 20)) == 45.0
        assert ledger.conversion_price("53887", date(2026, 6, 22)) == 45.0

    def test_看板之前沒有資料(self) -> None:
        ledger = Ledger(self.BOARDS)
        assert ledger.conversion_price("53887", date(2026, 5, 1)) is None
        assert ledger.as_of("53887", date(2026, 5, 1)) is None
        assert ledger.as_of("99999", date(2026, 6, 1)) is None

    def test_沒有生效日就當成已經生效(self) -> None:
        ledger = Ledger([board(date(2026, 6, 1), bond(next_reset=None))])
        assert ledger.conversion_price("53887", date(2026, 6, 1)) == 100.0

    def test_只有未生效的價格就回_None(self) -> None:
        ledger = Ledger([board(date(2026, 6, 1), bond(next_reset=date(2026, 7, 1)))])
        assert ledger.conversion_price("53887", date(2026, 6, 1)) is None

    def test_當天或之前最近一份(self) -> None:
        ledger = Ledger(self.BOARDS)
        got = ledger.as_of("53887", date(2026, 6, 15))
        assert got is not None
        assert got.conversion_price == 45.0
