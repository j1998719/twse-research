"""除權息研究的事件與同日安慰劑(#28,事前登記見 issue)。"""

import pandas as pd

from src.run_dividends import same_day_placebo, shifted


DAYS = pd.bdate_range("2020-06-01", periods=100)


def test_事件日往前移幾個交易日_超出範圍就丟掉() -> None:
    hits = [("A", DAYS[10]), ("B", DAYS[2])]
    assert shifted(hits, DAYS, -6) == [("A", DAYS[4])]
    assert shifted(hits, DAYS, -1) == [("A", DAYS[9]), ("B", DAYS[1])]


def test_安慰劑跟事件同一天_挑前後_20_天沒有除權息的股票() -> None:
    hits = [("A", DAYS[50])]
    actions = {"A": [DAYS[50]], "B": [DAYS[60]], "C": [DAYS[5]]}
    pool = ["A", "B", "C", "D"]
    got = same_day_placebo(hits, pool, actions, DAYS, per_event=20, seed=1)
    assert {d for _, d in got} == {DAYS[50]}
    # A 是事件本身、B 在 10 天內有除息 → 都不能當安慰劑;C(45 天前)、D 可以
    assert {c for c, _ in got} <= {"C", "D"}
    assert len(got) == 20


def test_安慰劑可以重現() -> None:
    hits = [("A", DAYS[50]), ("A", DAYS[70])]
    pool = ["B", "C", "D", "E"]
    a = same_day_placebo(hits, pool, {}, DAYS, per_event=3, seed=7)
    assert a == same_day_placebo(hits, pool, {}, DAYS, per_event=3, seed=7)
