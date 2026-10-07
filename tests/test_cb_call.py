"""可轉債強制贖回的事件(#61,事前登記見 issue)。

事件 = 一檔債的贖回欄位第一次出現在看板上那天,只取價內的(標的股價 ≥ 轉換價)。
看板第一天就已經在贖回期的排除(左設限);同一檔標的 60 個交易日內只算第一次。
"""

from datetime import date

import pandas as pd

from src.cbboard import Board, Bond
from src.run_cb_call import call_events


DAYS = pd.bdate_range("2020-01-02", periods=200)


def _bond(code: str, *, call: bool, stock: float = 50.0, conv: float = 40.0) -> Bond:
    return Bond(
        code=code,
        name="測試",
        conversion_start=None,
        conversion_end=None,
        conversion_price=conv,
        next_reset=None,
        put_start=None,
        put_end=None,
        put_price=None,
        call_start=date(2020, 3, 2) if call else None,
        call_end=date(2020, 4, 1) if call else None,
        call_price=100.0 if call else None,
        delisted=None,
        issued=None,
        outstanding=None,
        reference_price=None,
        stock_price=stock,
    )


def _board(i: int, *bonds: Bond) -> Board:
    return Board(day=DAYS[i].date(), bonds=tuple(bonds))


def test_贖回欄位第一次出現那天_價內才算() -> None:
    boards = [
        _board(0, _bond("11111", call=False), _bond("22221", call=False)),
        _board(1, _bond("11111", call=False), _bond("22221", call=False)),
        _board(2, _bond("11111", call=True), _bond("22221", call=True, stock=30.0)),
        _board(3, _bond("11111", call=True), _bond("22221", call=True, stock=30.0)),
    ]
    itm, otm = call_events(boards, DAYS)
    assert itm == [("1111", DAYS[2])]
    assert otm == [("2222", DAYS[2])]


def test_看板第一天就在贖回期的是左設限() -> None:
    boards = [
        _board(0, _bond("11111", call=True)),
        _board(1, _bond("11111", call=True)),
    ]
    assert call_events(boards, DAYS) == ([], [])


def test_同一檔標的_60_個交易日內只算第一次() -> None:
    boards = [
        _board(0, _bond("11111", call=False), _bond("11112", call=False)),
        _board(5, _bond("11111", call=True), _bond("11112", call=False)),
        _board(10, _bond("11111", call=True), _bond("11112", call=True)),
    ]
    itm, _ = call_events(boards, DAYS)
    assert itm == [("1111", DAYS[5])]
