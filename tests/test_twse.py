from datetime import date

import pytest

from src.twse import (
    Notice,
    is_common_stock,
    parse_notices,
    parse_period,
    parse_punishes,
    roc_to_date,
)


class TestRocDate:
    def test_民國轉西元_點分隔(self):
        assert roc_to_date("115.08.04") == date(2026, 8, 4)

    def test_民國轉西元_斜線分隔(self):
        assert roc_to_date("115/08/21") == date(2026, 8, 21)

    def test_跨年不會算錯(self):
        assert roc_to_date("114/12/31") == date(2025, 12, 31)
        assert roc_to_date("115/01/01") == date(2026, 1, 1)

    def test_前後空白不影響(self):
        assert roc_to_date("  115/03/05  ") == date(2026, 3, 5)

    def test_看不懂的格式要報錯(self):
        with pytest.raises(ValueError, match="看不懂的日期"):
            roc_to_date("2026-08-04")


class TestCommonStock:
    def test_四位數字是普通股(self):
        assert is_common_stock("2330")
        assert is_common_stock("8033")

    def test_權證六位數要排除(self):
        assert not is_common_stock("033945")
        assert not is_common_stock("035348")

    def test_ETF要排除(self):
        # 0050 也是四位數,但 00 開頭的是 ETF 不是普通股
        assert not is_common_stock("0050")
        assert not is_common_stock("0056")

    def test_特別股帶英文要排除(self):
        assert not is_common_stock("2891B")


class TestParsePeriod:
    def test_全形波浪號(self):
        assert parse_period("115/08/24～115/08/28") == (
            date(2026, 8, 24),
            date(2026, 8, 28),
        )

    def test_半形波浪號也要認得(self):
        assert parse_period("115/08/24~115/08/28") == (
            date(2026, 8, 24),
            date(2026, 8, 28),
        )

    def test_只有一天時起迄相同(self):
        assert parse_period("115/08/24") == (date(2026, 8, 24), date(2026, 8, 24))


class TestParseNotices:
    payload = {
        "data": [
            [
                1,
                "033945",
                "國巨統一58購02",
                "1",
                "跌幅異常",
                "115.08.04",
                "11.10",
                "-----",
            ],
            [2, "2330", "台積電", "3", "漲幅異常", "115.08.05", "1200.00", "25.3"],
        ]
    }

    def test_預設只留普通股(self):
        rows = parse_notices(self.payload)
        assert [r.code for r in rows] == ["2330"]

    def test_關掉過濾就全都要(self):
        rows = parse_notices(self.payload, common_only=False)
        assert len(rows) == 2

    def test_欄位對應正確(self):
        row = parse_notices(self.payload)[0]
        assert row == Notice(
            day=date(2026, 8, 5),
            code="2330",
            name="台積電",
            reason="漲幅異常",
            close="1200.00",
            per="25.3",
        )


class TestParsePunishes:
    payload = {
        "data": [
            [
                1,
                "115/08/21",
                "8033",
                "雷虎",
                2,
                "連續三次",
                "115/08/24～115/08/28",
                "第二次處置",
                "處置內容說明",
                "",
            ],
            [
                2,
                "115/08/21",
                "035348",
                "強茂統一59購02",
                1,
                "連續三次",
                "115/08/24～115/08/28",
                "第一次處置",
                "處置內容說明",
                "",
            ],
        ]
    }

    def test_排除權證(self):
        rows = parse_punishes(self.payload)
        assert [r.code for r in rows] == ["8033"]

    def test_起迄與次數(self):
        row = parse_punishes(self.payload)[0]
        assert row.start == date(2026, 8, 24)
        assert row.end == date(2026, 8, 28)
        assert row.measure == "第二次處置"

    def test_第幾次要看處置措施而不是累計欄(self):
        # 「累計」欄(這裡是 2)是相對於查詢區間算的,換個區間就變,不能當第幾次用。
        # 這筆的累計是 2 但措施是第一次處置,正確答案是 1。
        payload = {
            "data": [
                [
                    1,
                    "115/08/21",
                    "8033",
                    "雷虎",
                    8,
                    "連續五次",
                    "115/08/24～115/08/28",
                    "第一次處置",
                    "",
                    "",
                ]
            ]
        }
        assert parse_punishes(payload)[0].nth == 1

    def test_人工管制撮合不編號(self):
        payload = {
            "data": [
                [
                    1,
                    "115/08/21",
                    "8033",
                    "雷虎",
                    1,
                    "連續五次",
                    "115/08/24",
                    "人工管制撮合",
                    "",
                    "",
                ]
            ]
        }
        assert parse_punishes(payload)[0].nth == 0


class TestPrices:
    def test_千分位轉數字(self):
        from src.prices import to_float

        assert to_float("1,234.50") == 1234.5
        assert to_float(" 15.00 ") == 15.0

    def test_沒成交的符號回None(self):
        from src.prices import to_float

        for blank in ["--", "---", "-----", "", "X"]:
            assert to_float(blank) is None

    def test_解析當日行情(self):
        from datetime import date

        from src.prices import parse_day

        payload = {
            "tables": [
                {"fields": ["其他表"], "data": []},
                {
                    "fields": [
                        "證券代號",
                        "證券名稱",
                        "成交股數",
                        "成交筆數",
                        "成交金額",
                        "開盤價",
                        "最高價",
                        "最低價",
                        "收盤價",
                    ],
                    "data": [
                        [
                            "00400A",
                            "主動國泰",
                            "36,138,014",
                            "6,037",
                            "538,660,510",
                            "14.90",
                            "15.01",
                            "14.80",
                            "15.00",
                        ],
                        [
                            "2330",
                            "台積電",
                            "20,000,000",
                            "9,000",
                            "1,000",
                            "1,200.00",
                            "1,210.00",
                            "1,195.00",
                            "1,205.00",
                        ],
                        [
                            "1101",
                            "台泥",
                            "1,000",
                            "10",
                            "1,000",
                            "--",
                            "--",
                            "--",
                            "--",
                        ],
                    ],
                },
            ]
        }
        bars = parse_day(payload, date(2026, 9, 18))
        # 00400A 帶英文字母,不是普通股
        assert [b.code for b in bars] == ["2330", "1101"]
        assert bars[0].close == 1205.0
        assert bars[0].volume == 20000000
        # 當天沒成交:價格是 None 而不是 0,才不會被當成跌到零
        assert bars[1].close is None
        assert bars[1].volume == 1000

    def test_只抓平日(self):
        from datetime import date

        from src.prices import weekdays

        days = weekdays(date(2026, 9, 18), date(2026, 9, 22))  # 五六日一二
        assert days == [date(2026, 9, 18), date(2026, 9, 21), date(2026, 9, 22)]
