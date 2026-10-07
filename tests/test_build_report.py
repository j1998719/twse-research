import pandas as pd
import pytest

from src.build_report import _projected_days, _shift, _status
from src.market import ROUND_TRIP_COST_PCT


DAYS = pd.DatetimeIndex(
    pd.to_datetime(
        ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]
    )
)

#: _current 從價格表取最後一個交易日、算模擬進出場。兩檔每天都收 100
PRICES = pd.concat(
    pd.DataFrame({"day": DAYS, "code": code, "close": 100.0})
    for code in ("1111", "2222")
).assign(open=100.0, high=100.0, low=100.0)


class TestProjectedDays:
    def test_已知的日子都留著(self):
        got = _projected_days(DAYS)
        assert got[: len(DAYS)] == list(DAYS)

    def test_往後推的只有平日(self):
        got = _projected_days(DAYS)
        for day in got[len(DAYS) :]:
            assert day.weekday() < 5

    def test_跳過週末(self):
        # 資料最後一天是週五 9/18,下一個推算日應該是週一 9/21
        got = _projected_days(DAYS)
        assert got[len(DAYS)] == pd.Timestamp("2026-09-21")


class TestShift:
    seq = _projected_days(DAYS)

    def test_往後數(self):
        got = _shift(self.seq, pd.Timestamp("2026-09-16"), 2)
        assert got == pd.Timestamp("2026-09-18")

    def test_往前數(self):
        got = _shift(self.seq, pd.Timestamp("2026-09-18"), -2)
        assert got == pd.Timestamp("2026-09-16")

    def test_可以跨到推算的未來(self):
        # 9/18 之後的交易日是推算出來的
        got = _shift(self.seq, pd.Timestamp("2026-09-18"), 1)
        assert got == pd.Timestamp("2026-09-21")

    def test_不在序列上的日子取最接近的(self):
        # 9/19 是週六,最接近的是 9/18
        got = _shift(self.seq, pd.Timestamp("2026-09-19"), 0)
        assert got in (pd.Timestamp("2026-09-18"), pd.Timestamp("2026-09-21"))

    def test_超出範圍回None(self):
        assert _shift(self.seq, pd.Timestamp("2026-09-14"), -5) is None


class TestStatus:
    buy = pd.Timestamp("2026-09-20")
    sell = pd.Timestamp("2026-09-25")

    def test_還沒到買點(self):
        assert _status(pd.Timestamp("2026-09-18"), self.buy, self.sell) == "尚未到買點"

    def test_買點當天就是持有中(self):
        assert _status(self.buy, self.buy, self.sell) == "持有中"

    def test_中間是持有中(self):
        assert _status(pd.Timestamp("2026-09-22"), self.buy, self.sell) == "持有中"

    def test_賣點當天(self):
        assert _status(self.sell, self.buy, self.sell) == "今天賣出"

    def test_過了賣點(self):
        assert _status(pd.Timestamp("2026-09-26"), self.buy, self.sell) == "已過賣點"


class TestCurrent:
    """仍在處置中的個股,要配對到正確的歷史統計。"""

    punishes = pd.DataFrame(
        [
            {
                "code": 1111,
                "name": "第一次的股",
                "measure": "第一次處置",
                "condition": "連續三次",
                "start": pd.Timestamp("2026-09-15"),
                "end": pd.Timestamp("2026-09-25"),
                "nth": 1,
            },
            {
                "code": 2222,
                "name": "第二次的股",
                "measure": "第二次處置",
                "condition": "連續五次",
                "start": pd.Timestamp("2026-09-16"),
                "end": pd.Timestamp("2026-09-24"),
                "nth": 2,
            },
            {
                "code": 3333,
                "name": "早就出關的股",
                "measure": "第一次處置",
                "condition": "連續三次",
                "start": pd.Timestamp("2026-08-01"),
                "end": pd.Timestamp("2026-08-10"),
                "nth": 1,
            },
        ]
    )
    # 歷史事件:第一次的表現差、第二次的表現好。兩個市場各四筆
    runs = pd.DataFrame(
        {
            "code": ["1111", "1111", "2222", "2222"] * 2,
            "nth": [1] * 4 + [2] * 4,
            "excess": [1.0, 2.0, -1.0, 3.0, 8.0, 9.0, -2.0, 10.0],
        }
    )
    #: 1111 是上市、2222 是上櫃
    market_of = {"1111": "twse", "2222": "otc"}

    def _run(self, today="2026-09-18"):
        from src.build_report import _current

        seq = _projected_days(DAYS)
        return _current(
            self.punishes,
            self.runs,
            seq,
            pd.Timestamp(today),
            self.market_of,
            PRICES,
        )

    def test_只列出還沒出關的(self):
        got = self._run()
        assert [row["code"] for row in got] == [2222, 1111]  # 依結束日排序

    def test_第二次處置配到第二次的歷史統計(self):
        got = {row["code"]: row for row in self._run()}
        # 第二次那組的歷史中位數(8, 9, -2, 10)是 8.5
        assert got[2222]["histMedian"] == 8.5
        # 第一次那組(1, 2, -1, 3)是 1.5
        assert got[1111]["histMedian"] == 1.5

    def test_買賣點由出關日往前推(self):
        got = {row["code"]: row for row in self._run()}
        row = got[2222]
        # 處置到 9/24,出關日是下一個交易日,賣點是出關前一日
        assert row["sellDay"] < row["release"]
        assert row["buyDay"] < row["sellDay"]

    def test_出關日超出已知資料就標記為推算(self):
        got = self._run()
        assert all(row["projected"] for row in got)

    def test_狀態會隨今天而改變(self):
        early = {r["code"]: r for r in self._run("2026-09-16")}
        assert early[1111]["status"] == "尚未到買點"


class TestCurrentByMarket:
    """同類統計要用同市場的樣本 —— 上櫃的流動性和滑價和上市不同。"""

    punishes = pd.DataFrame(
        {
            "code": ["1111", "2222"],
            "name": ["上市股", "上櫃股"],
            "measure": ["第一次處置", "第一次處置"],
            "condition": ["連續三次", "連續三次"],
            "start": pd.to_datetime(["2026-09-14", "2026-09-14"]),
            "end": pd.to_datetime(["2026-09-25", "2026-09-25"]),
        }
    )
    # 上市中位數 +1、上櫃 +9。各留一筆負的 —— win_loss 要有賺有賠才算得出
    # 期望值,而那正是真實資料的樣子
    runs = pd.DataFrame(
        {
            "code": ["1111"] * 4 + ["2222"] * 4,
            "nth": [1] * 8,
            "excess": [1.0, 1.0, 1.0, -1.0, 9.0, 9.0, 9.0, -1.0],
        }
    )
    market_of = {"1111": "twse", "2222": "otc"}

    def _run(self):
        from src.build_report import _current

        return _current(
            self.punishes,
            self.runs,
            _projected_days(DAYS),
            pd.Timestamp("2026-09-18"),
            self.market_of,
            PRICES,
        )

    def test_每一檔用自己市場的統計(self):
        got = {row["code"]: row for row in self._run()}
        # 混合的話兩張卡片都會是 5.0
        assert got[1111]["histMedian"] == 1.0
        assert got[2222]["histMedian"] == 9.0

    def test_市場標在卡片上(self):
        got = {row["code"]: row for row in self._run()}
        assert got[1111]["market"] == "twse"
        assert got[2222]["market"] == "otc"

    def test_同市場樣本足夠時不算混合(self):
        assert all(row["histPooled"] is False for row in self._run())

    def test_同市場樣本太少時退回混合並標明(self):
        from src.build_report import _current

        # 只留上市的四筆。上櫃一筆同類都沒有 -> 退回混合。
        # 保留一正一負,不然 win_loss 連混合後也算不出期望值
        thin = self.runs[self.runs.code == "1111"]
        got = _current(
            self.punishes,
            thin,
            _projected_days(DAYS),
            pd.Timestamp("2026-09-18"),
            self.market_of,
            PRICES,
        )
        # 上櫃一筆同類都沒有 -> 退回混合,而且要講出來
        otc = next(row for row in got if row["code"] == 2222)
        assert otc["histPooled"] is True

    def test_不編號的措施不上板(self):
        from src.build_report import _current

        odd = self.punishes.assign(measure=["人工管制撮合", "第一次處置"])
        got = _current(
            odd,
            self.runs,
            _projected_days(DAYS),
            pd.Timestamp("2026-09-18"),
            self.market_of,
            PRICES,
        )
        # 它不在研究樣本裡,掛第一次處置的統計會誤導
        assert [row["code"] for row in got] == [2222]


class TestBinomial:
    """宣稱「全部為正」之前要真的檢查符號。"""

    def test_全部為正時算得出機率(self):
        from src.build_report import _binomial

        years = [{"median": 1.0}, {"median": 2.0}, {"median": 0.5}]
        assert _binomial(years) == 0.125

    def test_有一個為負就回_None(self):
        from src.build_report import _binomial

        # 原本直接 0.5 ** len(years),從來沒檢查過符號 —— 那會讓頁面印
        # 「全部為正」而上面的表格擺著一個負數
        years = [{"median": 1.0}, {"median": -0.1}, {"median": 2.0}]
        assert _binomial(years) is None

    def test_剛好是零也不算正(self):
        from src.build_report import _binomial

        assert _binomial([{"median": 1.0}, {"median": 0.0}]) is None

    def test_沒有期間時回_None(self):
        from src.build_report import _binomial

        assert _binomial([]) is None


class TestTrade:
    """卡片上的模擬進出場,跟回測同一套漲跌停順延規則(#44、#45)。"""

    days = pd.bdate_range("2026-02-02", periods=6)

    def _close(self, closes: list[float | None]) -> pd.DataFrame:
        return pd.DataFrame({"1111": closes}, index=self.days)

    def _trade(self, closes, buy: int, sell: int, *, last: int | None = None):
        from src.build_report import _trade

        days = self.days if last is None else self.days[: last + 1]
        close = self._close(closes).loc[days]
        return _trade("1111", self.days[buy], self.days[sell], days, close)

    def test_還沒到買點只有收盤價(self):
        got = self._trade([100, 101, 102, 103, 104, 105], buy=4, sell=5, last=2)
        assert (got["close"], got["closeDay"]) == (102, "2026-02-04")
        assert got["entryPrice"] is None
        assert got["tradeState"] == "尚未到買點"

    def test_持有中用最新收盤算未實現報酬(self):
        got = self._trade([100, 100, 110, 121, 121, 121], buy=1, sell=5, last=3)
        assert got["entryPrice"] == 100
        assert got["tradeState"] == "持有中"
        assert got["tradeReturn"] == pytest.approx(21 - ROUND_TRIP_COST_PCT, abs=0.01)

    def test_已賣出用出場價算實現報酬(self):
        got = self._trade([100, 100, 105, 105, 110, 200], buy=1, sell=4)
        assert (got["exitPrice"], got["exitDay"]) == (110, "2026-02-06")
        assert got["tradeState"] == "已賣出"
        assert got["tradeReturn"] == pytest.approx(10 - ROUND_TRIP_COST_PCT, abs=0.01)

    def test_買進日漲停順延(self):
        got = self._trade([100, 110, 112, 112, 112, 112], buy=1, sell=4)
        assert (got["entryDay"], got["entryDeferred"]) == ("2026-02-04", 1)

    def test_賣出日跌停順延到最新一天還賣不掉(self):
        got = self._trade([100, 100, 100, 90, 81, 72.9], buy=1, sell=3)
        assert got["exitPrice"] is None
        assert got["tradeState"] == "跌停賣不掉,順延中"
        # 還沒賣掉,所以報酬用最新收盤算
        assert got["tradeReturn"] == pytest.approx(
            -27.1 - ROUND_TRIP_COST_PCT, abs=0.01
        )

    def test_漲停一路到賣出日都買不到(self):
        got = self._trade([100, 110, 121, 133, 140, 140], buy=1, sell=3)
        assert got["entryPrice"] is None
        assert got["tradeState"] == "漲停買不到,沒進場"

    def test_沒有這一檔的價格(self):
        from src.build_report import _trade

        got = _trade(
            "9999", self.days[1], self.days[3], self.days, self._close([1] * 6)
        )
        assert got["close"] is None


def test_推算的交易日跳過休市日() -> None:
    from datetime import date

    days = pd.DatetimeIndex(pd.to_datetime(["2026-10-05", "2026-10-06"]))
    got = _projected_days(days, {date(2026, 10, 9)})
    future = [d.date().isoformat() for d in got[2:5]]
    # 10/07、10/08,跳過 10/09(國慶補假)、10/10、10/11,下一個是 10/12
    assert future == ["2026-10-07", "2026-10-08", "2026-10-12"]


def test_進場就在最新收盤_報酬留空_不顯示負的成本() -> None:
    from src.build_report import _trade

    days = pd.bdate_range("2026-10-01", periods=4)
    close = pd.DataFrame({"1111": [100.0, 100.0, 100.0, 101.0]}, index=days)
    got = _trade("1111", days[3], days[3] + pd.Timedelta(days=7), days, close)
    assert got["entryPrice"] == 101.0
    assert got["tradeState"] == "剛進場"
    assert got["tradeReturn"] is None


def test_大盤報酬只算研究期間_不是整個指數快取() -> None:
    # 指數快取從 2016 年開始,研究期間從 2020 開始。以前拿 2016 的點數當起點,
    # 再用研究期間的天數去年化,大盤被灌成 +514%、年化 30.8%(實際 +311.7%、23.3%)
    from datetime import date

    from src.build_report import market_return

    index = {
        date(2016, 1, 4): 8000.0,
        date(2020, 1, 2): 10000.0,
        date(2026, 10, 6): 40000.0,
    }
    days = pd.DatetimeIndex(pd.to_datetime(["2020-01-02", "2026-10-06"]))
    assert market_return(index, days) == pytest.approx(300.0)
