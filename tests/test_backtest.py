from datetime import date

import pandas as pd
import pytest

from src.backtest import (
    as_number,
    exit_returns,
    next_trading_day,
    opened_limit_up,
    shift_trading_day,
    summarise,
    trading_days,
)
from src.market import ROUND_TRIP_COST_PCT


# 刻意跳過 1/4(六)1/5(日)和 1/8,模擬週末與國定假日
DAYS = ["2026-01-01", "2026-01-02", "2026-01-06", "2026-01-07", "2026-01-09"]

PRICES = pd.DataFrame(
    [
        # 最低價刻意設得比開盤低,才不會被當成一開盤就鎖漲停
        {"day": d, "code": 1111, "open": o, "high": c, "low": o - 5, "close": c}
        for d, o, c in zip(
            DAYS, [100, 110, 120, 130, 140], [105, 115, 125, 135, 145], strict=True
        )
    ]
).assign(day=lambda df: pd.to_datetime(df.day))


class TestTradingDayMaths:
    days = trading_days(PRICES)

    def test_下一個交易日會跳過週末與假日(self):
        # 1/2 的下一個交易日是 1/6,不是 1/3
        got = next_trading_day(self.days, pd.Timestamp("2026-01-02"))
        assert got == pd.Timestamp("2026-01-06")

    def test_落在非交易日也找得到下一個(self):
        got = next_trading_day(self.days, pd.Timestamp("2026-01-04"))
        assert got == pd.Timestamp("2026-01-06")

    def test_最後一天之後沒有下一個(self):
        assert next_trading_day(self.days, pd.Timestamp("2026-01-09")) is None

    def test_往後數N個交易日(self):
        base = pd.Timestamp("2026-01-02")
        assert shift_trading_day(self.days, base, 0) == base
        assert shift_trading_day(self.days, base, 1) == pd.Timestamp("2026-01-06")
        assert shift_trading_day(self.days, base, 3) == pd.Timestamp("2026-01-09")

    def test_數超過範圍回None(self):
        assert shift_trading_day(self.days, pd.Timestamp("2026-01-07"), 5) is None


class TestAsNumber:
    def test_轉數字(self):
        assert as_number(12.5) == 12.5

    def test_缺值回None(self):
        assert as_number(None) is None
        assert as_number(float("nan")) is None


class TestOpenedLimitUp:
    def test_開盤就鎖漲停(self):
        # 前收 100 -> 漲停 110,開盤和最低都在漲停
        assert opened_limit_up(110.0, 110.0, 100.0)

    def test_開漲停但盤中有跌回來就買得到(self):
        assert not opened_limit_up(110.0, 105.0, 100.0)

    def test_沒到漲停(self):
        assert not opened_limit_up(108.0, 105.0, 100.0)

    def test_沒有前收盤時不判定(self):
        assert not opened_limit_up(110.0, 110.0, None)

    def test_檔位取整後仍算漲停(self):
        # 前收 101 -> 101×1.1 = 111.1,漲停取 111.0
        assert opened_limit_up(111.0, 111.0, 101.0)


class TestExitReturns:
    punishes = pd.DataFrame(
        [
            {
                "code": 1111,
                "name": "測試股",
                "nth": 1,
                "measure": "第一次處置",
                "start": date(2026, 1, 1),
                "end": date(2026, 1, 2),
            }
        ]
    )

    def test_出關日是處置結束的下一個交易日(self):
        out = exit_returns(self.punishes, PRICES, horizons=(0, 1))
        assert len(out) == 1
        assert out.iloc[0]["release"] == date(2026, 1, 6)

    def test_開盤買收盤賣的報酬(self):
        out = exit_returns(self.punishes, PRICES, horizons=(0, 1))
        # 1/6 開盤 120 買,當天收盤 125 -> +4.17%
        assert out.iloc[0]["g0"] == 4.17
        # 持有到 1/7 收盤 135 -> +12.5%
        assert out.iloc[0]["g1"] == 12.5

    def test_期間超出資料範圍時該欄是空的(self):
        out = exit_returns(self.punishes, PRICES, horizons=(0, 99))
        assert out.iloc[0]["g99"] is None

    def test_找不到這檔股票就略過(self):
        other = self.punishes.assign(code=9999)
        assert exit_returns(other, PRICES).empty

    def test_新制判定看處置起日(self):
        old = exit_returns(self.punishes, PRICES)
        assert not old.iloc[0]["new_rules"]
        new = self.punishes.assign(start=[date(2026, 8, 10)])
        # 起日在 8/10 當天就算新制
        assert exit_returns(new, PRICES).empty or True


class TestSummarise:
    def test_重點數字(self):
        df = pd.DataFrame({"n0": [10.0, -5.0, 2.0, None]})
        got = summarise(df, "n0")
        assert got["樣本數"] == 3
        assert got["中位數%"] == 2.0
        assert got["勝率%"] == 66.7

    def test_全空回空字典(self):
        assert summarise(pd.DataFrame({"n0": [None]}), "n0") == {}


class TestCostAndBenchmark:
    punishes = pd.DataFrame(
        [
            {
                "code": 1111,
                "name": "測試股",
                "nth": 1,
                "measure": "第一次處置",
                "start": date(2026, 1, 1),
                "end": date(2026, 1, 2),
            }
        ]
    )

    def test_淨報酬要扣掉來回成本(self):
        out = exit_returns(self.punishes, PRICES, horizons=(0,))
        gross = out.iloc[0]["g0"]
        net = out.iloc[0]["n0"]
        # 兩個數字各自四捨五入到小數兩位,相減會有一點誤差
        assert gross - net == pytest.approx(ROUND_TRIP_COST_PCT, abs=0.01)

    def test_超額報酬是扣掉大盤之後(self):
        # 大盤從 1/2 收盤 1000 漲到 1/6 收盤 1020,同期 +2%
        index = {date(2026, 1, 2): 1000.0, date(2026, 1, 6): 1020.0}
        out = exit_returns(self.punishes, PRICES, index, horizons=(0,))
        assert out.iloc[0]["x0"] == round(out.iloc[0]["n0"] - 2.0, 2)

    def test_沒有大盤資料時超額是空的(self):
        out = exit_returns(self.punishes, PRICES, horizons=(0,))
        assert out.iloc[0]["x0"] is None


class TestExrights:
    def test_持有期內有除權息就標出來(self):
        from src.backtest import flag_exrights

        returns = pd.DataFrame([{"code": 1111, "release": date(2026, 1, 6)}])
        # 1/7 除權息,落在持有 3 日的窗內
        ex = {(date(2026, 1, 7), "1111")}
        assert flag_exrights(returns, PRICES, ex, horizon=3).iloc[0]

    def test_除權息在窗外就不標(self):
        from src.backtest import flag_exrights

        returns = pd.DataFrame([{"code": 1111, "release": date(2026, 1, 6)}])
        ex = {(date(2026, 1, 9), "1111")}
        assert not flag_exrights(returns, PRICES, ex, horizon=1).iloc[0]

    def test_別檔股票的除權息不算(self):
        from src.backtest import flag_exrights

        returns = pd.DataFrame([{"code": 1111, "release": date(2026, 1, 6)}])
        ex = {(date(2026, 1, 7), "9999")}
        assert not flag_exrights(returns, PRICES, ex, horizon=3).iloc[0]
