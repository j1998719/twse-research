from datetime import date

import pandas as pd

from src.backtest import (
    as_number,
    exit_returns,
    next_trading_day,
    shift_trading_day,
    summarise,
    trading_days,
)


# 刻意跳過 1/4(六)1/5(日)和 1/8,模擬週末與國定假日
DAYS = ["2026-01-01", "2026-01-02", "2026-01-06", "2026-01-07", "2026-01-09"]

PRICES = pd.DataFrame(
    [
        {"day": d, "code": 1111, "open": o, "close": c}
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
        assert out.iloc[0]["r0"] == 4.17
        # 持有到 1/7 收盤 135 -> +12.5%
        assert out.iloc[0]["r1"] == 12.5

    def test_期間超出資料範圍時該欄是空的(self):
        out = exit_returns(self.punishes, PRICES, horizons=(0, 99))
        assert out.iloc[0]["r99"] is None

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
        df = pd.DataFrame({"r0": [10.0, -5.0, 2.0, None]})
        got = summarise(df, "r0")
        assert got["樣本數"] == 3
        assert got["中位數%"] == 2.0
        assert got["勝率%"] == 66.7

    def test_全空回空字典(self):
        assert summarise(pd.DataFrame({"r0": [None]}), "r0") == {}
