"""資料列取自開源專案裡抓下來的真實回應(jiansoft/stock_crawler 的 testdata、
TechTWC/TWstock 的 fixtures),只留需要的幾列。"""

from datetime import date

import pytest

from src.corpactions import (
    SOURCES,
    Action,
    complete,
    merge,
    parse,
    parse_roc,
)
from src.fetch_actions import windows


BY = {s.kind: s for s in SOURCES}

TWT49U = {
    "stat": "OK",
    "fields": [
        "資料日期",
        "股票代號",
        "股票名稱",
        "除權息前收盤價",
        "除權息參考價",
        "權值+息值",
        "權/息",
        "漲停價格",
        "跌停價格",
        "開盤競價基準",
        "減除股利參考價",
        "詳細資料",
    ],
    "data": [
        # ETF:不是普通股,要濾掉
        [
            "114年01月17日",
            "00730",
            "富邦臺灣優質高息",
            "22.99",
            "22.90",
            "0.086",
            "息",
            "25.19",
            "20.61",
            "22.90",
            "22.90",
            "00730,20250117",
        ],
        [
            "114年07月17日",
            "2330",
            "台積電",
            "1100.00",
            "1095.00",
            "5.0",
            "息",
            "1204.0",
            "986.0",
            "1095.0",
            "1095.00",
            "2330,20250717",
        ],
        # 現金增資除權:除權息參考價扣了認購權價值,減除股利參考價沒有
        [
            "115年08月18日",
            "6225",
            "天瀚",
            "45.00",
            "30.04",
            "14.96",
            "權",
            "33.0",
            "27.1",
            "44.4",
            "45.00",
            "6225,20260818",
        ],
    ],
}

EXDAILYQ = {
    "stat": "ok",
    "tables": [
        {
            "totalCount": 2,
            "fields": [
                "除權息日期",
                "代號",
                "名稱",
                "除權息前收盤價",
                "除權息參考價",
                "權值",
                "息值",
                "權值+息值",
                "權/息",
                "漲停價",
                "跌停價",
                "開始交易基準價",
                "減除股利參考價",
            ],
            "data": [
                [
                    "112/07/20",
                    "4175",
                    "杏一              ",
                    "129.00",
                    "115.16",
                    "11.09",
                    "2.74",
                    "13.83",
                    "除權息",
                    "126.50",
                    "104.00",
                    "115.00",
                    "115.16",
                ],
                [
                    "112/07/03",
                    "1788",
                    "杏昌              ",
                    "147.00",
                    "140.00",
                    "0.0",
                    "7.0",
                    "7.0",
                    "除息",
                    "154.00",
                    "126.00",
                    "140.00",
                    "140.00",
                ],
            ],
        }
    ],
}

TWTAUU = {
    "stat": "OK",
    "fields": [
        "恢復買賣日期",
        "股票代號",
        "名稱",
        "停止買賣前收盤價格",
        "恢復買賣參考價",
        "漲停價格",
        "跌停價格",
        "開盤競價基準",
        "除權參考價",
        "減資原因",
        "詳細資料",
    ],
    "data": [
        # 同一次減資列了三次(不同申報日);後兩列的除權參考價有值 → 用它
        [
            "104/03/20",
            "3536",
            "誠創",
            "6.58",
            "13.33",
            "14.25",
            "12.15",
            "13.35",
            "--",
            "彌補虧損",
            "3536  ,20150107",
        ],
        [
            "104/03/20",
            "3536",
            "誠創",
            "6.58",
            "13.33",
            "14.25",
            "12.15",
            "13.35",
            "13.06",
            "彌補虧損",
            "3536  ,20150113",
        ],
        [
            "111/09/19",
            "2603",
            "長榮",
            "80.80",
            "187.00",
            "205.5",
            "168.5",
            "187.0",
            "--",
            "退還股款",
            "2603  ,20220906",
        ],
        # 已公告、還沒恢復買賣
        [
            "115/10/05",
            "2601",
            "益航",
            "-",
            "-",
            "-",
            "-",
            "-",
            "--",
            "彌補虧損",
            "2601  ,20260917",
        ],
    ],
}

REVIVT = {
    "stat": "ok",
    "tables": [
        {
            "totalCount": 1,
            "fields": [
                "恢復買賣日期",
                "股票代號",
                "名稱",
                "最後交易日之收盤價格",
                "減資恢復買賣開始日參考價格",
                "漲停價格",
                "跌停價格",
                "開始交易基準價",
                "除權參考價",
                "減資原因",
                "詳細資料",
            ],
            # 除權參考價 "0.00" 是「沒有」,不是零元
            "data": [
                [
                    "1150921",
                    "8059",
                    "凱碩",
                    "13.40",
                    "22.33",
                    "24.55",
                    "20.10",
                    "22.35",
                    "0.00",
                    "彌補虧損",
                    "<table></table>",
                ]
            ],
        }
    ],
}


class TestParseRoc:
    @pytest.mark.parametrize(
        ("text", "want"),
        [
            ("114年01月17日", date(2025, 1, 17)),
            ("112/07/20", date(2023, 7, 20)),
            ("1150921", date(2026, 9, 21)),
            (" 104/03/20 ", date(2015, 3, 20)),
        ],
    )
    def test_三種寫法(self, text: str, want: date) -> None:
        assert parse_roc(text) == want

    @pytest.mark.parametrize("text", ["2025-01-17", "", "-", "114/13/01"])
    def test_認不出來回_None(self, text: str) -> None:
        assert parse_roc(text) is None


def test_上市除權息_濾掉_ETF_用減除股利參考價() -> None:
    got = {a.code: a for a in parse(TWT49U, BY["twse_dividend"])}
    assert set(got) == {"2330", "6225"}
    assert got["2330"].day == date(2025, 7, 17)
    assert got["2330"].factor == pytest.approx(1095 / 1100)
    # 現增除權:減除股利參考價 = 前收,不製造一個假的 33% 跳空
    assert got["6225"].factor == pytest.approx(1.0)


def test_上櫃除權息_名稱有補空白也沒關係() -> None:
    got = {a.code: a for a in parse(EXDAILYQ, BY["otc_dividend"])}
    assert got["4175"].factor == pytest.approx(115.16 / 129)
    assert got["1788"].day == date(2023, 7, 3)


def test_上市減資_除權參考價有值就用它_還沒恢復的跳過() -> None:
    got = parse(TWTAUU, BY["twse_reduction"])
    assert {a.code for a in got} == {"3536", "2603"}
    # 同一次減資列了好幾次 → 只留一筆,而且是除權參考價有值的那一列
    (chuang,) = (a for a in got if a.code == "3536")
    assert chuang.factor == pytest.approx(13.06 / 6.58)
    # 2603 退還股款:(80.8 - 6) / 0.4 = 187
    (evergreen,) = (a for a in got if a.code == "2603")
    assert evergreen.factor == pytest.approx(187 / 80.8)


def test_上櫃減資_七碼日期_除權參考價零是沒有() -> None:
    (action,) = parse(REVIVT, BY["otc_reduction"])
    assert action.day == date(2026, 9, 21)
    assert action.factor == pytest.approx(22.33 / 13.40)


def test_欄位變了就報錯_不要安靜地回空的() -> None:
    broken = {"fields": ["日期", "代號"], "data": [["114年01月17日", "2330"]]}
    with pytest.raises(ValueError, match="欄位變了"):
        parse(broken, BY["twse_dividend"])


def test_空的回應是空的() -> None:
    assert parse({"stat": "OK", "data": []}, BY["twse_dividend"]) == []


def test_離譜的因子當成資料錯誤() -> None:
    payload = {
        **TWT49U,
        "data": [
            [
                *TWT49U["data"][1][:3],
                "1100",
                "1095",
                *TWT49U["data"][1][5:10],
                "1.0",
                "x",
            ]
        ],
    }
    assert parse(payload, BY["twse_dividend"]) == []


def test_同一天兩個來源只留一個_減資優先() -> None:
    day = date(2015, 3, 20)
    dividend = Action("3536", day, 0.9, "twse_dividend")
    reduction = Action("3536", day, 2.0, "twse_reduction")
    other = Action("2330", day, 0.99, "twse_dividend")
    got = merge(
        [
            (BY["twse_dividend"], [dividend, other]),
            (BY["twse_reduction"], [reduction]),
        ]
    )
    assert got == [other, reduction]


def test_被截斷的回應認得出來() -> None:
    assert complete(EXDAILYQ)
    assert complete(TWT49U)
    cut = {"tables": [{**EXDAILYQ["tables"][0], "totalCount": 150}]}
    assert not complete(cut)


def test_上市按年查_上櫃按月查() -> None:
    start, end = date(2025, 11, 15), date(2026, 2, 3)
    assert windows(BY["twse_dividend"], start, end) == [
        (date(2025, 11, 15), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 2, 3)),
    ]
    assert windows(BY["otc_dividend"], start, end) == [
        (date(2025, 11, 15), date(2025, 11, 30)),
        (date(2025, 12, 1), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 3)),
    ]


#: 5314 世紀 2025-03-31 面額 10 元 → 0.5 元(一股換二十股)。櫃買 pvChgRslt 的真實一列
PV_CHG = {
    "tables": [
        {
            "fields": [
                "恢復買賣日期",
                "證券代號",
                "證券名稱",
                "最後交易日之收盤價格",
                "恢復買賣開始參考價",
                "漲停價格",
                "跌停價格",
                "開始交易基準價",
                "詳細資料",
            ],
            "data": [
                [
                    "1140331",
                    "5314",
                    "世紀*",
                    "1390.00",
                    "69.50",
                    "76.40",
                    "62.60",
                    "69.50",
                    "",
                ]
            ],
            "totalCount": 1,
        }
    ]
}


def test_面額變更一次二十倍是真的_不是資料錯誤() -> None:
    # 以前除權息的合理範圍 (0.05, 20) 是開區間,剛好 0.05 的這筆被丟掉,
    # 頭條樣本裡就多了一筆假的 −89%(#59)
    (action,) = parse(PV_CHG, BY["otc_par"])
    assert action.day == date(2025, 3, 31)
    assert action.factor == pytest.approx(69.5 / 1390)
