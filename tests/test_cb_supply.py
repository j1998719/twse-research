"""可轉債的稀釋 / 新股供給事件(#63,事前登記見 issue)。

D 重設:轉換價下降 ≥ 5%,而且對不上前後 60 天內任何除權息因子(±1 個百分點)。
E 大量轉換:月底餘額比上一次少 ≥ 20%,不在強制贖回期、不在賣回日前後 45 天。
"""

from dataclasses import replace
from datetime import date

import pandas as pd

from src.cbboard import Board, Bond
from src.run_cb_supply import conversion_events, reset_events


DAYS = pd.bdate_range("2020-01-02", periods=200)
BASE = Bond(
    code="11111",
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
    outstanding=1_000_000,
    reference_price=None,
    stock_price=50.0,
)


def _board(i: int, **change: object) -> Board:
    return Board(day=DAYS[i].date(), bonds=(replace(BASE, **change),))


def _actions(*rows: tuple[str, date, float]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["code", "day", "factor"])


def test_重設_降_5_趴以上而且對不上除權息() -> None:
    boards = [_board(0), _board(1), _board(2, conversion_price=36.0)]  # −10%
    assert reset_events(boards, DAYS, _actions()) == [("1111", DAYS[2])]


def test_除權息的反稀釋調整不算重設() -> None:
    boards = [_board(0), _board(1), _board(2, conversion_price=36.0)]
    actions = _actions(("1111", DAYS[20].date(), 0.9))  # 20 天後除息,因子 0.9 = −10%
    assert reset_events(boards, DAYS, actions) == []


def test_降不到_5_趴不算() -> None:
    boards = [_board(0), _board(1), _board(2, conversion_price=39.0)]
    assert reset_events(boards, DAYS, _actions()) == []


def test_大量轉換_餘額少_20_趴以上() -> None:
    boards = [_board(0), _board(1), _board(2, outstanding=700_000)]
    assert conversion_events(boards, DAYS) == [("1111", DAYS[2])]


def test_贖回期間或賣回日附近的不算轉換() -> None:
    call = [
        _board(0),
        _board(1),
        _board(2, outstanding=700_000, call_start=date(2020, 1, 6)),
    ]
    assert conversion_events(call, DAYS) == []
    put = [
        _board(0),
        _board(1),
        _board(2, outstanding=700_000, put_start=DAYS[10].date()),
    ]
    assert conversion_events(put, DAYS) == []
