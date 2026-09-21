import pytest

from src.market import (
    ROUND_TRIP_COST_PCT,
    limit_down,
    limit_up,
    parse_index,
    tick_size,
)


class TestTickSize:
    @pytest.mark.parametrize(
        ("price", "tick"),
        [
            (9.99, 0.01),
            (10, 0.05),
            (49.95, 0.05),
            (50, 0.1),
            (99.9, 0.1),
            (100, 0.5),
            (499.5, 0.5),
            (500, 1.0),
            (999, 1.0),
            (1000, 5.0),
            (2405, 5.0),
        ],
    )
    def test_各價位的檔位(self, price, tick):
        assert tick_size(price) == tick


class TestLimits:
    def test_十元股票(self):
        # 10 × 1.1 = 11.0,檔位 0.05
        assert limit_up(10.0) == 11.0
        assert limit_down(10.0) == 9.0

    def test_檔位會讓漲停低於剛好的一成(self):
        # 100 × 1.1 = 110,但 110 的檔位是 0.5 -> 剛好落在檔位上
        assert limit_up(100.0) == 110.0
        # 101 × 1.1 = 111.1,要往下取到 111.0
        assert limit_up(101.0) == 111.0

    def test_跌停往上取才不會跌超過(self):
        # 101 × 0.9 = 90.9,檔位 0.1 -> 90.9 剛好
        assert limit_down(101.0) == 90.9
        # 1007 × 0.9 = 906.3,檔位 1 -> 往上取 907
        assert limit_down(1007.0) == 907.0

    def test_高價股用五元檔位(self):
        # 2405 × 1.1 = 2645.5 -> 往下取到 2645
        assert limit_up(2405.0) == 2645.0

    def test_低價股(self):
        # 9 × 1.1 = 9.9,檔位 0.01
        assert limit_up(9.0) == 9.9
        assert limit_down(9.0) == 8.1


class TestParseIndex:
    def test_挑出加權指數(self):
        payload = {
            "tables": [
                {"fields": ["證券代號"], "data": [["2330", "台積電"]]},
                {
                    "fields": ["指數", "收盤指數"],
                    "data": [
                        ["寶島股價指數", "52,357.52"],
                        ["發行量加權股價指數", "47,180.75"],
                    ],
                },
            ]
        }
        assert parse_index(payload) == 47180.75

    def test_找不到回None(self):
        assert parse_index({"tables": []}) is None


def test_來回成本():
    # 手續費 0.1425% 買 + 0.1425% 賣 + 證交稅 0.3% 賣
    assert pytest.approx(0.585) == ROUND_TRIP_COST_PCT
