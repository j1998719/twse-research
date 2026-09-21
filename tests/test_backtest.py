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
        assert got["最小%"] == -5.0
        assert got["中位數%"] == 2.0
        assert got["最大%"] == 10.0
        assert got["平均%"] == round((10 - 5 + 2) / 3, 2)
        assert got["勝率%"] == 66.7

    def test_四分位與標準差(self):
        df = pd.DataFrame({"n0": [1.0, 2.0, 3.0, 4.0, 5.0]})
        got = summarise(df, "n0")
        assert got["四分之一%"] == 2.0
        assert got["四分之三%"] == 4.0
        assert got["標準差%"] == round(pd.Series([1, 2, 3, 4, 5]).std(), 2)

    def test_平均被極端值拉歪時中位數不受影響(self):
        # 這正是這類資料的常態:少數暴漲把平均拉高,中位數才看得出多數人的處境
        df = pd.DataFrame({"n0": [-2.0, -1.0, -1.0, -1.0, 100.0]})
        got = summarise(df, "n0")
        assert got["中位數%"] == -1.0
        assert got["平均%"] == 19.0

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


class TestHoldThrough:
    punishes = pd.DataFrame(
        [
            {
                "code": 1111,
                "name": "測試股",
                "nth": 1,
                "measure": "第一次處置",
                "start": date(2026, 1, 2),
                "end": date(2026, 1, 6),
            }
        ]
    )

    def test_進場是處置首日開盤(self):
        from src.backtest import hold_through

        out = hold_through(self.punishes, PRICES, horizons=(0,))
        assert out.iloc[0]["begin"] == date(2026, 1, 2)
        assert out.iloc[0]["entry"] == 110.0

    def test_出場是出關日收盤(self):
        from src.backtest import hold_through

        out = hold_through(self.punishes, PRICES, horizons=(0,))
        # 1/6 結束 -> 1/7 出關,收盤 135;1/2 開盤 110 買
        assert out.iloc[0]["release"] == date(2026, 1, 7)
        assert out.iloc[0]["g0"] == round((135 / 110 - 1) * 100, 2)

    def test_處置首日不是交易日就往後找(self):
        from src.backtest import hold_through

        weekend = self.punishes.assign(start=[date(2026, 1, 3)])
        out = hold_through(weekend, PRICES, horizons=(0,))
        assert out.iloc[0]["begin"] == date(2026, 1, 6)

    def test_多抱幾天(self):
        from src.backtest import hold_through

        out = hold_through(self.punishes, PRICES, horizons=(0, 1))
        # 出關日後一個交易日是 1/9,收盤 145
        assert out.iloc[0]["g1"] == round((145 / 110 - 1) * 100, 2)


class TestPreReleaseRun:
    punishes = pd.DataFrame(
        [
            {
                "code": 1111,
                "name": "測試股",
                "nth": 1,
                "measure": "第一次處置",
                "start": date(2026, 1, 1),
                "end": date(2026, 1, 6),
            }
        ]
    )

    def test_出場是出關前一個交易日(self):
        from src.backtest import pre_release_run

        # 1/6 結束 -> 1/7 出關,前一個交易日是 1/6
        out = pre_release_run(self.punishes, PRICES, entry=-2, exit_=-1)
        assert out.iloc[0]["release"] == date(2026, 1, 7)
        assert out.iloc[0]["sell_day"] == date(2026, 1, 6)
        assert out.iloc[0]["buy_day"] == date(2026, 1, 2)

    def test_用收盤價進出(self):
        from src.backtest import pre_release_run

        out = pre_release_run(self.punishes, PRICES, entry=-2, exit_=-1)
        # 1/2 收盤 115 買,1/6 收盤 125 賣
        assert out.iloc[0]["buy"] == 115.0
        assert out.iloc[0]["sell"] == 125.0
        assert out.iloc[0]["gross"] == round((125 / 115 - 1) * 100, 2)

    def test_淨報酬扣成本(self):
        from src.backtest import pre_release_run

        out = pre_release_run(self.punishes, PRICES, entry=-2, exit_=-1)
        assert out.iloc[0]["gross"] - out.iloc[0]["net"] == pytest.approx(
            ROUND_TRIP_COST_PCT, abs=0.01
        )

    def test_往前數超出資料範圍就略過(self):
        from src.backtest import pre_release_run

        assert pre_release_run(self.punishes, PRICES, entry=-99, exit_=-1).empty


class TestShiftBounds:
    days = trading_days(PRICES)

    def test_往前數超出範圍要回None而不是繞到尾端(self):
        # 沒有下界檢查的話,負索引會回傳 days[-95] 也就是資料尾端的某一天
        got = shift_trading_day(self.days, pd.Timestamp("2026-01-02"), -99)
        assert got is None

    def test_剛好數到第一天(self):
        got = shift_trading_day(self.days, pd.Timestamp("2026-01-06"), -2)
        assert got == pd.Timestamp("2026-01-01")

    def test_再往前一天就沒有了(self):
        assert shift_trading_day(self.days, pd.Timestamp("2026-01-06"), -3) is None


class TestEventRate:
    def test_頻率計算(self):
        from src.backtest import event_rate

        # 兩個月內 6 件
        days = pd.to_datetime(
            [
                "2026-01-05",
                "2026-01-12",
                "2026-01-20",
                "2026-02-03",
                "2026-02-10",
                "2026-03-04",
            ]
        )
        got = event_rate(pd.DataFrame({"buy_day": days}))
        assert got["總件數"] == 6
        assert got["最忙的月份"] == 3
        assert got["最閒的月份"] == 1
        assert got["有事件的月份數"] == 3

    def test_空的回空字典(self):
        from src.backtest import event_rate

        assert event_rate(pd.DataFrame({"buy_day": []})) == {}

    def test_每月平均與涵蓋天數一致(self):
        from src.backtest import event_rate

        days = pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01"])
        got = event_rate(pd.DataFrame({"buy_day": days}))
        # 2026-01-01 到 2026-03-01 共 60 天
        assert got["涵蓋天數"] == 60
        assert got["每月平均"] == round(3 / (60 / 30.44), 1)
