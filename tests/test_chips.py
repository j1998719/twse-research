from datetime import date

from src.chips import Chips, parse_chips


# 真實欄位名稱,取自 2026 年的回應
FIELDS_2026 = [
    "證券代號",
    "證券名稱",
    "外陸資買進股數(不含外資自營商)",
    "外陸資賣出股數(不含外資自營商)",
    "外陸資買賣超股數(不含外資自營商)",
    "外資自營商買進股數",
    "外資自營商賣出股數",
    "外資自營商買賣超股數",
    "投信買進股數",
    "投信賣出股數",
    "投信買賣超股數",
    "自營商買賣超股數",
    "自營商買進股數(自行買賣)",
    "自營商賣出股數(自行買賣)",
    "自營商買賣超股數(自行買賣)",
    "自營商買進股數(避險)",
    "自營商賣出股數(避險)",
    "自營商買賣超股數(避險)",
    "三大法人買賣超股數",
]


def payload(rows):
    return {"fields": FIELDS_2026, "data": rows}


DAY = date(2026, 9, 18)


class TestParseChips:
    row_2330 = [
        "2330",
        "台積電",
        "10,000",
        "4,000",
        "6,000",  # 外陸資
        "500",
        "200",
        "300",  # 外資自營商
        "2,000",
        "500",
        "1,500",  # 投信
        "800",  # 自營商合計
        "900",
        "400",
        "500",  # 自營商(自行買賣)
        "600",
        "300",
        "300",  # 自營商(避險)
        "8,600",  # 三大法人
    ]

    def test_外資要把兩欄加起來(self):
        got = parse_chips(payload([self.row_2330]), DAY)[0]
        assert got.foreign == 6000 + 300

    def test_投信(self):
        assert parse_chips(payload([self.row_2330]), DAY)[0].trust == 1500

    def test_自營商只取合計不重複計算細項(self):
        # 自行買賣 500 + 避險 300 = 800,若把三欄都加起來會變成 1600
        assert parse_chips(payload([self.row_2330]), DAY)[0].dealer == 800

    def test_三大法人合計與公告一致(self):
        got = parse_chips(payload([self.row_2330]), DAY)[0]
        assert got.total == 8600

    def test_賣超是負數(self):
        row = list(self.row_2330)
        row[4] = "-6,000"
        row[7] = "-300"
        got = parse_chips(payload([row]), DAY)[0]
        assert got.foreign == -6300

    def test_排除權證與ETF(self):
        rows = [
            self.row_2330,
            ["00403A", "主動統一"] + ["0"] * 17,
            ["0050", "元大台灣50"] + ["0"] * 17,
        ]
        got = parse_chips(payload(rows), DAY)
        assert [c.code for c in got] == ["2330"]

    def test_關掉過濾就全都要(self):
        rows = [self.row_2330, ["00403A", "主動統一"] + ["0"] * 17]
        assert len(parse_chips(payload(rows), DAY, common_only=False)) == 2


class TestFieldRobustness:
    """欄位名稱用比對的,順序或用詞微調都要撐得住。"""

    def test_欄位順序不同也認得(self):
        fields = [
            "證券代號",
            "證券名稱",
            "投信買賣超股數",
            "外資買賣超股數",
            "自營商買賣超股數",
        ]
        got = parse_chips(
            {"fields": fields, "data": [["2330", "台積電", "1,000", "5,000", "200"]]},
            DAY,
        )[0]
        assert (got.foreign, got.trust, got.dealer) == (5000, 1000, 200)

    def test_欄名有空白也認得(self):
        fields = [
            "證券代號",
            "證券名稱",
            "外資買賣超 股數",
            "投信買賣超股數",
            "自營商買賣超股數",
        ]
        got = parse_chips(
            {"fields": fields, "data": [["2330", "台積電", "5,000", "0", "0"]]}, DAY
        )[0]
        assert got.foreign == 5000

    def test_沒有欄位定義就回空的(self):
        assert parse_chips({"data": [["2330", "台積電"]]}, DAY) == []

    def test_缺某一類法人時當成零(self):
        fields = ["證券代號", "證券名稱", "外資買賣超股數"]
        got = parse_chips(
            {"fields": fields, "data": [["2330", "台積電", "5,000"]]}, DAY
        )[0]
        assert got.trust == 0
        assert got.dealer == 0
        assert got.total == 5000


def test_Chips_是不可變的():
    c = Chips(day=DAY, code="2330", name="台積電", foreign=1, trust=2, dealer=3)
    assert c.total == 6
