"""注意股階段的事件(#3,事前登記見 issue)。

每天收盤後,數這一檔最近 5 個交易日(含當天)被列注意幾次;剛好達到 3 的那天是
事件。只用當天以前公布的公告 —— 不准用「後來有沒有被處置」來篩。同一檔 60 個
交易日內只算第一次。
"""

import pandas as pd

from src.events.notices import third_notice


DAYS = pd.bdate_range("2024-01-01", periods=120)


def _notices(*pairs: tuple[str, int]) -> pd.DataFrame:
    return pd.DataFrame(
        {"code": [c for c, _ in pairs], "day": [DAYS[i] for _, i in pairs]}
    )


def test_五個交易日內第三次就是事件() -> None:
    got = third_notice(_notices(("A", 0), ("A", 2), ("A", 4)), DAYS)
    assert got == [("A", DAYS[4])]


def test_超過五個交易日的不算在同一個窗口() -> None:
    # 第 0、2 天各一次,第 5 天第三次:那時窗口是 1~5,只有 2 次
    assert third_notice(_notices(("A", 0), ("A", 2), ("A", 5)), DAYS) == []


def test_第四次第五次不是新事件() -> None:
    got = third_notice(_notices(("A", 0), ("A", 1), ("A", 2), ("A", 3), ("A", 4)), DAYS)
    assert got == [("A", DAYS[2])]


def test_同一天兩則公告只算一次() -> None:
    got = third_notice(_notices(("A", 0), ("A", 0), ("A", 1), ("A", 3)), DAYS)
    assert got == [("A", DAYS[3])]


def test_60_個交易日內只算第一次() -> None:
    first = [("A", 0), ("A", 1), ("A", 2)]
    again = [("A", 40), ("A", 41), ("A", 42)]
    # 第 42 天那次被丟掉,但條件出現過;要超過 60 個交易日(第 103 天以後)才重新算
    late = [("A", 103), ("A", 104), ("A", 105)]
    assert third_notice(_notices(*first, *again, *late), DAYS) == [
        ("A", DAYS[2]),
        ("A", DAYS[105]),
    ]
