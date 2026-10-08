from datetime import date

import pandas as pd

from src.clauses import (
    classify,
    clauses_in,
    dominant_family,
    family_of,
    triggering_notices,
    window_for,
)


DAYS = pd.DatetimeIndex(pd.bdate_range("2026-09-01", "2026-09-30"))


class TestClausesIn:
    def test_抓出單一款次(self):
        assert clauses_in("最近六個營業日累積收盤價漲幅達35.01%。﹝第一款﹞") == {1}

    def test_一則可以踩到多款(self):
        text = "漲幅異常﹝第一款﹞。且週轉率過高﹝第十款﹞。"
        assert clauses_in(text) == {1, 10}

    def test_兩位數的款次(self):
        assert clauses_in("當沖比過高﹝第十三款﹞") == {13}
        assert clauses_in("借券﹝第十二款﹞") == {12}

    def test_沒有標記就回空集合(self):
        assert clauses_in("本公司監視業務督導會報決議") == set()

    def test_認不得的數字不會當掉(self):
        assert clauses_in("﹝第二十款﹞") == set()


class TestWindowFor:
    def test_條件對應的回看長度(self):
        assert window_for("連續三次") == 3
        assert window_for("連續五次") == 5
        assert window_for("最近十個營業日已有六次") == 10
        assert window_for("最近三十個營業日已有十二次") == 30

    def test_當沖是附加條件不影響長度(self):
        assert window_for("連續三次及當日沖銷標準") == 3
        assert window_for("連續五次及當日沖銷標準") == 5

    def test_上櫃的寫法(self):
        assert window_for("連續3個營業日") == 3
        assert window_for("連續5個營業日及沖銷標準") == 5
        assert window_for("最近10個營業日內有6個營業日") == 10
        assert window_for("最近30個營業日內有12個營業日") == 30

    def test_認不得的條件用最長的回看期間(self):
        # 寧可多看一些,也不要漏掉真正觸發它的注意
        assert window_for("監視業務督導會報決議") == 30
        assert window_for("") == 30


class TestFamilyOf:
    def test_三組的歸屬(self):
        assert family_of(6) == "估值"
        assert family_of(1) == "價格動能"
        assert family_of(13) == "籌碼"

    def test_沒歸類的款次歸其他(self):
        assert family_of(7) == "其他"
        assert family_of(99) == "其他"


class TestDominantFamily:
    def test_最多的那一組(self):
        assert dominant_family({"價格動能": 5, "籌碼": 2}) == "價格動能"

    def test_平手時不硬選(self):
        # 硬選一個會讓分組結果取決於字典順序,那是假的訊號
        assert dominant_family({"價格動能": 3, "籌碼": 3}) is None

    def test_空的回None(self):
        assert dominant_family({}) is None


class TestTriggeringNotices:
    notices = pd.DataFrame(
        {
            "code": [1111] * 5 + [2222],
            "day": pd.to_datetime(
                [
                    "2026-09-08",
                    "2026-09-09",
                    "2026-09-10",
                    "2026-09-01",
                    "2026-09-11",
                    "2026-09-10",
                ]
            ),
            "reason": ["x"] * 6,
        }
    )

    def test_只取窗口內的(self):
        # 公告日 9/10,往前三個營業日 = 9/8、9/9、9/10
        got = triggering_notices(
            self.notices, DAYS, 1111, pd.Timestamp("2026-09-10"), 3
        )
        assert set(got.day.dt.strftime("%Y-%m-%d")) == {
            "2026-09-08",
            "2026-09-09",
            "2026-09-10",
        }

    def test_含公告日當天(self):
        # 最後一次注意常常跟處置公告同一天
        got = triggering_notices(
            self.notices, DAYS, 1111, pd.Timestamp("2026-09-10"), 1
        )
        assert list(got.day.dt.strftime("%Y-%m-%d")) == ["2026-09-10"]

    def test_窗口外的不算(self):
        got = triggering_notices(
            self.notices, DAYS, 1111, pd.Timestamp("2026-09-10"), 3
        )
        assert "2026-09-01" not in set(got.day.dt.strftime("%Y-%m-%d"))

    def test_別檔股票的不算(self):
        got = triggering_notices(
            self.notices, DAYS, 1111, pd.Timestamp("2026-09-10"), 30
        )
        assert set(got.code) == {1111}

    def test_窗口比資料還長也不會爆(self):
        got = triggering_notices(
            self.notices, DAYS, 1111, pd.Timestamp("2026-09-02"), 99
        )
        assert len(got) >= 1


class TestClassify:
    punishes = pd.DataFrame(
        [
            {
                "code": 1111,
                "condition": "連續三次",
                "announced": date(2026, 9, 10),
            }
        ]
    )
    notices = pd.DataFrame(
        {
            "code": [1111, 1111, 1111],
            "day": pd.to_datetime(["2026-09-08", "2026-09-09", "2026-09-10"]),
            "reason": [
                "漲幅﹝第一款﹞",
                "漲幅﹝第一款﹞。週轉率﹝第十款﹞",
                "估值﹝第六款﹞",
            ],
        }
    )

    def test_收集到所有款次(self):
        got = classify(self.punishes, self.notices, DAYS)
        assert got.iloc[0]["clauses"] == (1, 6, 10)

    def test_依出現次數決定主導組(self):
        got = classify(self.punishes, self.notices, DAYS)
        # 價格動能 2 次(兩則第一款)、籌碼 1 次、估值 1 次
        assert got.iloc[0]["family"] == "價格動能"
        assert got.iloc[0]["families"] == {"價格動能": 2, "籌碼": 1, "估值": 1}

    def test_記下找到幾則注意(self):
        got = classify(self.punishes, self.notices, DAYS)
        assert got.iloc[0]["notice_count"] == 3

    def test_找不到注意時不歸類(self):
        lonely = self.punishes.assign(code=[9999])
        got = classify(lonely, self.notices, DAYS)
        assert got.iloc[0]["family"] is None
        assert got.iloc[0]["clauses"] == ()

    def test_原本的欄位保留著(self):
        got = classify(self.punishes, self.notices, DAYS)
        assert got.iloc[0]["code"] == 1111
        assert got.iloc[0]["condition"] == "連續三次"
