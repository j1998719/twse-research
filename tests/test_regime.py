from datetime import date
from itertools import pairwise

import pandas as pd

from src.regime import MARKET_REGIMES, Period, microstructure_era, slice_by


class TestMicrostructureEra:
    def test_逐筆交易上路前(self):
        assert microstructure_era(date(2020, 3, 22)) == "集合競價時代"

    def test_上路當天就算新制(self):
        assert microstructure_era(date(2020, 3, 23)) == "逐筆交易"

    def test_處置新制(self):
        assert microstructure_era(date(2026, 8, 10)) == "處置新制"
        assert microstructure_era(date(2026, 8, 9)) == "逐筆交易"


class TestSliceBy:
    events = pd.DataFrame(
        {
            "buy_day": pd.to_datetime(
                ["2021-06-01", "2022-03-15", "2022-12-31", "2023-01-01"]
            )
        }
    )

    def test_只取期間內的(self):
        got = slice_by(
            self.events, Period("空頭", date(2022, 1, 1), date(2022, 12, 31))
        )
        assert len(got) == 2

    def test_頭尾那天要含進去(self):
        got = slice_by(
            self.events, Period("一天", date(2022, 12, 31), date(2022, 12, 31))
        )
        assert len(got) == 1

    def test_沒有落在期間內就是空的(self):
        got = slice_by(self.events, Period("空", date(2019, 1, 1), date(2019, 12, 31)))
        assert got.empty


def test_期間彼此不重疊且連續():
    for a, b in pairwise(MARKET_REGIMES):
        assert a.end < b.start
        assert (b.start - a.end).days == 1
