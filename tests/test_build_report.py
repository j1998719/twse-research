import pandas as pd

from src.build_report import _projected_days, _shift, _status


DAYS = pd.DatetimeIndex(
    pd.to_datetime(
        ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]
    )
)


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
            DAYS.max(),
            pd.Timestamp(today),
            self.market_of,
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
            DAYS.max(),
            pd.Timestamp("2026-09-18"),
            self.market_of,
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
            DAYS.max(),
            pd.Timestamp("2026-09-18"),
            self.market_of,
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
            DAYS.max(),
            pd.Timestamp("2026-09-18"),
            self.market_of,
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
