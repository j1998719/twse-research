"""可轉債新發行(第一次掛牌)的事件(#62,事前登記見 issue)。

事件 = 一檔債第一次出現在看板上那天。看板第一天就在的債是左設限,排除;
同一檔標的 60 個交易日內有兩檔新債,只算第一檔。
"""

from datetime import date

import pandas as pd

from src.cbboard import Board, Bond
from src.run_cb_issue import issue_events


DAYS = pd.bdate_range("2020-01-02", periods=200)


def _bond(code: str) -> Bond:
    return Bond(
        code=code,
        name="測試",
        conversion_start=None,
        conversion_end=None,
        conversion_price=40.0,
        next_reset=None,
        put_start=None,
        put_end=None,
        put_price=None,
        call_start=None,
        call_end=None,
        call_price=None,
        delisted=None,
        issued=None,
        outstanding=None,
        reference_price=None,
        stock_price=50.0,
    )


def _board(i: int, *codes: str) -> Board:
    return Board(day=DAYS[i].date(), bonds=tuple(_bond(c) for c in codes))


def test_第一次出現就是掛牌_看板第一天就在的排除() -> None:
    boards = [
        _board(0, "11111"),
        _board(1, "11111", "22221"),
        _board(2, "11111", "22221"),
    ]
    assert issue_events(boards, DAYS) == [("2222", DAYS[1])]


def test_同一檔標的_60_個交易日內只算第一檔() -> None:
    boards = [
        _board(0, "99991"),
        _board(3, "99991", "11111"),
        _board(30, "99991", "11111", "11112"),
        _board(100, "99991", "11111", "11112", "11113"),
    ]
    assert issue_events(boards, DAYS) == [("1111", DAYS[3]), ("1111", DAYS[100])]


def test_日期不是交易日的看板不算() -> None:
    boards = [_board(0, "99991"), Board(day=date(2020, 1, 4), bonds=(_bond("11111"),))]
    assert issue_events(boards, DAYS) == []
