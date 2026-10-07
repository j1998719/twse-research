"""可轉債條款研究的分組量測與檢定(#26)。"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from src.cbboard import Board
from src.cbstudy import (
    H1_WINDOWS,
    H3_WINDOWS,
    Result,
    adjusted,
    close_on_or_before,
    horizon,
    moneyness,
    one_sample_test,
    pressure,
    score,
    table,
    traded_value,
    two_group,
    verdict,
)
from src.events.cb import Ledger
from src.study import Event, Window, resolve_window
from tests.test_events_cb import bond


DAYS = [date(2026, 1, 1) + timedelta(days=i) for i in range(80)]


def _flat(n: int = 6) -> dict[str, dict[date, float]]:
    """n 檔一路持平的股票,當基準。"""
    return {f"B{i}": dict.fromkeys(DAYS, 10.0) for i in range(n)}


def test_登記的窗口() -> None:
    # 第五輪定稿:T−20 撤掉
    assert (Window(-10, -1), Window(-5, -1)) == H1_WINDOWS
    assert (Window(1, 5), Window(1, 10), Window(1, 20)) == H3_WINDOWS
    assert horizon(Window(-10, -1)) == 9
    assert horizon(Window(0, 0)) == 1


class TestTradedValue:
    def test_上市期間內沒有列的日子是零_上市前是空的(self) -> None:
        days = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"])
        prices = pd.DataFrame(
            {
                "day": [days[0], days[2], days[1], days[2]],
                "code": ["A", "A", "B", "B"],
                "close": [10.0, 10.0, 5.0, 5.0],
                "volume": [100.0, 100.0, 10.0, 10.0],
            }
        )
        value = traded_value(prices)
        # A 在 1/6 沒成交(長表裡沒有這一列):那是 0,不是還沒上市
        assert value.at[days[1], "A"] == 0
        # B 在 1/5 還沒上市:留空,不能當成 0 拉低中位數
        assert pd.isna(value.at[days[0], "B"])


def test_當天或之前最近的收盤() -> None:
    series = {date(2026, 1, 2): 10.0, date(2026, 1, 5): 11.0}
    assert close_on_or_before(series, date(2026, 1, 5)) == 11.0
    assert close_on_or_before(series, date(2026, 1, 4)) == 10.0
    assert close_on_or_before(series, date(2026, 1, 1)) is None
    assert close_on_or_before(None, date(2026, 1, 1)) is None


class TestMeasures:
    BOARDS = (
        Board(
            date(2026, 1, 5),
            (bond(conversion_price=50.0, next_reset=None, outstanding=600_000),),
        ),
        # 1/8 的看板掛了一個 1/20 才生效的新價格
        Board(
            date(2026, 1, 8),
            (
                bond(
                    conversion_price=40.0,
                    next_reset=date(2026, 1, 20),
                    outstanding=300_000,
                ),
            ),
        ),
    )
    EVENT = Event("5388", date(2026, 2, 1), date(2026, 1, 5), tags={"bond": "53887"})

    def test_moneyness_用進場日有效的轉換價(self) -> None:
        raw = {"5388": {date(2026, 1, 9): 45.0}}
        ledger = Ledger(self.BOARDS)
        # 1/10 有效的還是 50(40 要 1/20 才生效),收盤用 1/9 那一筆
        assert moneyness(ledger, raw, self.EVENT, date(2026, 1, 10)) == 0.9
        # 1/20 起是 40
        assert moneyness(ledger, raw, self.EVENT, date(2026, 1, 20)) == 45.0 / 40.0

    def test_moneyness_缺資料(self) -> None:
        ledger = Ledger(self.BOARDS)
        assert moneyness(ledger, {}, self.EVENT, date(2026, 1, 10)) is None
        raw = {"5388": {date(2026, 1, 9): 45.0}}
        assert moneyness(ledger, raw, self.EVENT, date(2026, 1, 1)) is None

    def test_壓力是進場日看板的餘額除以前_20_日成交金額中位數(self) -> None:
        index = pd.bdate_range("2025-12-01", "2026-01-31")
        value = pd.DataFrame({"5388": 100_000.0}, index=index)
        ledger = Ledger(self.BOARDS)
        got = pressure(ledger, value, self.EVENT, date(2026, 1, 9))
        # 1/9 看得到的是 1/8 那份:30 萬 ÷ 10 萬
        assert got == pytest.approx(3.0)

    def test_壓力_成交金額是零或算不出來(self) -> None:
        index = pd.bdate_range("2025-12-01", "2026-01-31")
        ledger = Ledger(self.BOARDS)
        zero = pd.DataFrame({"5388": 0.0}, index=index)
        assert pressure(ledger, zero, self.EVENT, date(2026, 1, 9)) is None
        short = pd.DataFrame({"5388": 1.0}, index=index[-5:])
        assert pressure(ledger, short, self.EVENT, date(2026, 1, 9)) is None
        assert pressure(ledger, zero, self.EVENT, date(2026, 1, 1)) is None


class TestScore:
    def test_進場不晚於_knowable_的丟掉(self) -> None:
        closes = _flat()
        closes["X"] = {d: 10.0 + i * 0.1 for i, d in enumerate(DAYS)}
        fine = Event("X", DAYS[40], DAYS[20])
        late = Event("X", DAYS[40], DAYS[35])
        got = score([fine, late], DAYS, Window(-10, -1), closes)
        assert [s.event for s in got] == [fine]
        assert got[0].entry == DAYS[30]
        assert got[0].exit == DAYS[39]
        assert got[0].excess > 0
        # 同期:進場前 20 個交易日的超額報酬(不扣成本)。基準是 7 檔等權,
        # X 自己也在裡面
        own = (13.0 / 11.0 - 1) * 100
        assert got[0].before == pytest.approx(own - own / 7)

    def test_沒有股價的丟掉(self) -> None:
        got = score([Event("Z", DAYS[40], DAYS[1])], DAYS, Window(-10, -1), _flat())
        assert got == []

    def test_進場前不滿_20_天就沒有同期報酬(self) -> None:
        closes = _flat()
        closes["X"] = dict.fromkeys(DAYS, 10.0)
        (got,) = score([Event("X", DAYS[12], DAYS[0])], DAYS, Window(1, 5), closes)
        assert got.before is None


def _scored(values: list[tuple[str, int, float, float]]) -> list[object]:
    """(代號, 錨點位置, 超額報酬, 同期報酬) → Scored。"""
    from src.cbstudy import Scored

    return [
        Scored(
            event=Event(code, DAYS[at], DAYS[0], tags={"x": x}),
            entry=DAYS[at],
            exit=DAYS[at + 1],
            excess=x,
            before=b,
        )
        for code, at, x, b in values
    ]


class TestTwoGroup:
    def test_事件組明顯比較高(self) -> None:
        rows = [(f"E{i}", 5 + i * 2, 5.0 + i * 0.1, i % 3) for i in range(12)]
        rows += [(f"C{i}", 5 + i * 2, -5.0 - i * 0.1, i % 4) for i in range(12)]
        got = two_group(
            "t", "H1", _scored(rows), lambda s: s.event.code.startswith("E"), 1, DAYS
        )
        assert got is not None
        assert got.n_event == 12
        assert got.n_control == 12
        assert got.effect > 9
        assert got.p < 0.01
        assert got.raw_p < 0.01

    def test_同一檔重疊的窗口只留一筆(self) -> None:
        rows = [("E", 5, 1.0, 0.0), ("E", 6, 9.0, 1.0)]
        rows += [(f"E{i}", 5, 1.0, i) for i in range(4)]
        rows += [(f"C{i}", 5, -1.0, -i) for i in range(4)]
        got = two_group(
            "t", "H1", _scored(rows), lambda s: s.event.code.startswith("E"), 5, DAYS
        )
        assert got is not None
        assert got.n_event == 5

    def test_分不出組的不參加(self) -> None:
        rows = [(f"E{i}", 5, 1.0, 0.0) for i in range(4)]
        got = two_group("t", "H1", _scored(rows), lambda _s: None, 1, DAYS)
        assert got is None

    def test_同期強而領先弱是鏡像(self) -> None:
        # 分組跟進場前的報酬幾乎一樣,跟之後的報酬無關
        rows = [(f"E{i}", 5 + i, (-1) ** i * 1.0, 10.0 + i) for i in range(10)]
        rows += [(f"C{i}", 5 + i, (-1) ** i * 1.0, -10.0 - i) for i in range(10)]
        got = two_group(
            "t", "H1", _scored(rows), lambda s: s.event.code.startswith("E"), 1, DAYS
        )
        assert got is not None
        assert got.same_period is not None
        assert got.same_period[0] > 0.8
        assert got.mirrors is True


class TestOneSample:
    def test_全部是負的(self) -> None:
        rows = [(f"S{i}", 5, -1.0 - i, 0.0) for i in range(10)]
        got = one_sample_test("t", "H3", _scored(rows), 1, DAYS)
        assert got is not None
        assert got.n_control is None
        assert got.effect < 0
        assert got.p < 0.01
        # 錨點是發行時就定好的日期,不是由價格導出來的:沒有鏡像的問題
        assert got.same_period is None
        assert got.mirrors is False

    def test_樣本太少(self) -> None:
        assert (
            one_sample_test("t", "H3", _scored([("S", 5, 1.0, 0.0)]), 1, DAYS) is None
        )


def _result(
    name: str, hyp: str, effect: float, p: float, *, mirror: bool = False
) -> Result:
    return Result(
        name=name,
        hypothesis=hyp,
        n_event=10,
        n_control=10,
        median_event=effect,
        median_control=0.0,
        effect=effect,
        raw_p=p,
        p=p,
        months=5,
        same_period=(0.9, 0.001) if mirror else (0.0, 1.0),
        lead=(0.1, 0.5),
    )


class TestVerdict:
    def test_校正後顯著且不是鏡像就是找到了(self) -> None:
        results = [_result("a", "H1", 1.0, 0.001), _result("b", "H1", 1.0, 0.9)]
        got, which = verdict(results, adjusted(results))
        assert got == "找到了"
        assert which == ["a"]

    def test_顯著但是鏡像不算(self) -> None:
        results = [_result("a", "H1", 1.0, 0.001, mirror=True)]
        got, _ = verdict(results, adjusted(results))
        assert got != "找到了"

    def test_都不顯著但方向一致是線索(self) -> None:
        results = [
            _result("a", "H1", 1.0, 0.3),
            _result("b", "H1", 2.0, 0.4),
            _result("c", "H2", 1.0, 0.3),
            _result("d", "H2", -2.0, 0.4),
        ]
        got, which = verdict(results, adjusted(results))
        assert got == "線索"
        assert which == ["H1"]

    def test_方向不一致就收掉(self) -> None:
        results = [_result("a", "H1", 1.0, 0.3), _result("b", "H1", -2.0, 0.4)]
        got, which = verdict(results, adjusted(results))
        assert got == "收掉"
        assert which == []

    def test_BH(self) -> None:
        results = [_result("a", "H1", 1.0, 0.01), _result("b", "H1", 1.0, 0.04)]
        assert adjusted(results) == pytest.approx([0.02, 0.04])


def test_結果表() -> None:
    results = [_result("H1 價外/T-10", "H1", 1.0, 0.01)]
    text = table(results, adjusted(results))
    assert "H1 價外/T-10" in text
    assert "0.010" in text


def test_賣回的兩個分組() -> None:
    from src.cbstudy import Scored, put_groups

    def scored(bond_code: str, entry: date) -> Scored:
        event = Event(
            "5388", date(2026, 2, 1), date(2026, 1, 1), tags={"bond": bond_code}
        )
        return Scored(event, entry, entry, 0.0, None)

    boards = [
        Board(
            date(2026, 1, 5),
            (
                bond("53881", conversion_price=50.0, next_reset=None, outstanding=100),
                bond("53882", conversion_price=40.0, next_reset=None, outstanding=300),
                bond("53883", conversion_price=40.0, next_reset=None, outstanding=None),
            ),
        )
    ]
    index = pd.bdate_range("2025-12-01", "2026-01-31")
    value = pd.DataFrame({"5388": 10.0}, index=index)
    raw = {"5388": {date(2026, 1, 9): 45.0}}
    rows = [scored(code, date(2026, 1, 9)) for code in ("53881", "53882", "53883")]
    got = put_groups(rows, Ledger(boards), raw, value)
    # 45/50 價外、45/40 價內
    assert [got.out_of_money(s) for s in rows] == [True, False, False]
    # 壓力 10 天、30 天、算不出來;中位數 20
    assert got.cut == 20
    assert [got.high_pressure(s) for s in rows] == [False, True, None]
    assert (got.priced, got.loaded) == (3, 2)


def test_前置期() -> None:
    from src.cbstudy import lead_time

    # 原點 DAYS[40]、第一次看到 DAYS[30]:最早 DAYS[31] 進場,也就是原點前 9 天
    event = Event("X", DAYS[40], DAYS[30])
    assert lead_time(event, DAYS) == 9
    assert resolve_window(event, DAYS, Window(-9, -1)) is not None
    assert resolve_window(event, DAYS, Window(-10, -1)) is None
    # 原點當天才看得到
    assert lead_time(Event("X", DAYS[40], DAYS[40]), DAYS) == -1
    assert lead_time(Event("X", DAYS[-1] + timedelta(days=1), DAYS[0]), DAYS) is None
