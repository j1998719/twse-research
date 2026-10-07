"""可轉債條款看板(RSdrs001)的解析(#26)。"""

from __future__ import annotations

import gzip
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.cbboard import (
    Board,
    BoardError,
    board_path,
    link_to_prices,
    load_boards,
    months,
    parse,
    parse_listing,
)


FIXTURES = Path(__file__).parent / "fixtures" / "cbboard"
#: 22 欄、日期寫成 YYYYMMDD、空白寫成 "0" 的舊格式
OLD = FIXTURES / "RSdrs001.20170117-C.csv.gz"
#: 20 欄、日期寫成 YYYY/MM/DD、空白就是空白的新格式
NEW = FIXTURES / "RSdrs001.20260930-C.csv.gz"

HEAD = (
    "TITLE,轉換公司債資訊看板\r\nDATADATE,日期:115年09月30日\r\n"
    "HEADER,債券代碼,債券簡稱,轉換起日,轉換迄日,轉換價格,下次轉換價格生效日期,"
    "最近賣回權起日,最近賣回權迄日,最近賣回權價格,強制贖回起日,強制贖回迄日,"
    "強制贖回價格,終止櫃檯買賣日,原始發行總額,上月底發行餘額,轉債參考價格,"
    "轉換標的股票價格,停止交易起日,停止交易迄日,票面利率\r\n"
)
ROW = (
    'BODY,"53887","中磊七    ","2024/03/07","2028/12/06","130.3000  ",'
    '"2026/04/17","2026/10/28","2026/12/06","100.0000 ","        ","        ",'
    '"0.0000   ","        ","3,000,000,000","3,000,000,000","99.95  ","71.50  ",'
    '"        ","        ","0.00000  "\r\n'
)


def _raw(text: str) -> bytes:
    return text.encode("cp950")


class TestParseRealBoards:
    """兩份真的看板,一份舊格式、一份新格式。"""

    def test_新格式(self) -> None:
        board = parse(gzip.decompress(NEW.read_bytes()))
        assert board.day == date(2026, 9, 30)
        assert len(board.bonds) == 380
        taini = board.bond("11011")
        assert taini is not None
        assert taini.underlying == "1101"
        assert taini.name == "台泥一永"
        assert taini.conversion_price == 34.0
        assert taini.conversion_start == date(2025, 3, 11)
        assert taini.next_reset == date(2026, 7, 7)
        assert taini.outstanding == 8_000_000_000
        assert taini.put_start is None

    def test_新格式的賣回日(self) -> None:
        # 第四輪拿來定案 T−20 的那一檔:2026-09-29 第一次出現
        board = parse(gzip.decompress(NEW.read_bytes()))
        bond = board.bond("53887")
        assert bond is not None
        assert bond.put_start == date(2026, 10, 28)
        assert bond.put_end == date(2026, 12, 6)
        assert bond.put_price == 100.0
        assert bond.outstanding == 3_000_000_000
        assert bond.stock_price == 71.5

    def test_舊格式(self) -> None:
        # 2017 是 22 欄(多了最近停止轉換起迄日),欄位靠名稱查所以不受影響
        board = parse(gzip.decompress(OLD.read_bytes()))
        assert board.day == date(2017, 1, 17)
        assert len(board.bonds) == 294
        bond = board.bond("13162")
        assert bond is not None
        assert bond.conversion_start == date(2015, 1, 24)
        assert bond.conversion_price == 11.6
        assert bond.put_start == date(2016, 11, 24)
        assert bond.put_price == 102.01
        assert bond.issued == 200_000_000
        assert bond.outstanding == 200_000_000

    def test_舊格式的空白是_0(self) -> None:
        board = parse(gzip.decompress(OLD.read_bytes()))
        bond = board.bond("12581")
        assert bond is not None
        assert bond.put_start is None
        # 0.0000 是這個來源的「沒有」,不是價格 0
        assert bond.put_price is None
        assert bond.call_price is None

    def test_舊格式的_19110000_也是空白(self) -> None:
        # 民國 0 年 0 月 0 日直接加 1911。當成日期解的話整份看板會報錯
        board = parse(gzip.decompress(OLD.read_bytes()))
        bond = board.bond("25151")
        assert bond is not None
        assert bond.call_start is None
        assert bond.delisted == date(2017, 3, 1)

    def test_cp950_沒有解不出的字(self) -> None:
        # big5 有 9 個字解不出來(全在債券簡稱),cp950 是 0 個
        for path in (OLD, NEW):
            board = parse(gzip.decompress(path.read_bytes()))
            assert not any("�" in b.name for b in board.bonds)

    def test_兩位序號的標的取前四碼(self) -> None:
        board = parse(_raw(HEAD + ROW.replace('"53887"', '"811211"')))
        assert board.bonds[0].underlying == "8112"


class TestBoardError:
    """「解不出來」跟「那天沒資料」長得一模一樣,所以一律拋例外。"""

    def test_空檔案(self) -> None:
        with pytest.raises(BoardError, match="空"):
            parse(b"")

    def test_夠大但沒有_DATADATE_也沒有_BODY(self) -> None:
        # 302 導向的錯誤頁:好幾 KB,過得了大小門檻
        page = "<html><body>" + "請稍後再試" * 2000 + "</body></html>"
        with pytest.raises(BoardError):
            parse(page.encode("utf-8"))

    def test_DATADATE_解不出來(self) -> None:
        with pytest.raises(BoardError, match="DATADATE"):
            parse(_raw(HEAD.replace("115年09月30日", "某一天") + ROW))

    def test_沒有資料列(self) -> None:
        with pytest.raises(BoardError, match="BODY"):
            parse(_raw(HEAD))

    def test_表頭欄位名變了(self) -> None:
        with pytest.raises(BoardError, match="上月底發行餘額"):
            parse(_raw(HEAD.replace("上月底發行餘額", "發行餘額") + ROW))

    def test_1911_00_00_是空白(self) -> None:
        # 2017-05 起的看板用斜線寫民國 0 年
        board = parse(_raw(HEAD + ROW.replace("2026/10/28", "1911/00/00")))
        assert board.bonds[0].put_start is None

    def test_日期欄位格式看不懂(self) -> None:
        with pytest.raises(BoardError, match="2024-03-07"):
            parse(_raw(HEAD + ROW.replace("2024/03/07", "2024-03-07")))

    def test_九碼日期不收(self) -> None:
        with pytest.raises(BoardError):
            parse(_raw(HEAD + ROW.replace("2024/03/07", "202403071")))

    def test_民國一百年以前的六碼年份(self) -> None:
        board = parse(_raw(HEAD.replace("115年09月30日", "99年01月05日") + ROW))
        assert board.day == date(2010, 1, 5)


class TestListing:
    PAYLOAD = {
        "date": "20170131",
        "tables": [
            {
                "fields": ["資料日期", "檔案下載"],
                "data": [
                    [
                        "106/01/18",
                        "/storage/bond_zone/tradeinfo/cb/2017/201701/RSdrs001.20170118-C.csv",
                        "/storage/x.xls",
                    ],
                    [
                        "106/01/17",
                        "/storage/bond_zone/tradeinfo/cb/2017/201701/RSdrs001.20170117-C.csv",
                        "/storage/y.xls",
                    ],
                ],
            }
        ],
    }

    def test_由舊到新(self) -> None:
        got = parse_listing(self.PAYLOAD)
        assert [d for d, _ in got] == [date(2017, 1, 17), date(2017, 1, 18)]
        assert got[0][1].endswith("RSdrs001.20170117-C.csv")

    def test_沒有表就是空的(self) -> None:
        assert parse_listing({"tables": []}) == []

    def test_日期跟檔名對不上要報錯(self) -> None:
        bad = {
            "tables": [
                {
                    "fields": ["資料日期", "檔案下載"],
                    "data": [["106/01/18", "/a/RSdrs001.20170117-C.csv", ""]],
                }
            ]
        }
        with pytest.raises(BoardError, match="20170117"):
            parse_listing(bad)


def test_月份() -> None:
    assert months(date(2016, 11, 20), date(2017, 2, 3)) == [
        date(2016, 11, 1),
        date(2016, 12, 1),
        date(2017, 1, 1),
        date(2017, 2, 1),
    ]


def test_存檔路徑() -> None:
    assert board_path(Path("r"), date(2017, 1, 17)) == Path(
        "r/2017/RSdrs001.20170117-C.csv.gz"
    )


def test_讀回存檔(tmp_path: Path) -> None:
    for src in (OLD, NEW):
        day = parse(gzip.decompress(src.read_bytes())).day
        dest = board_path(tmp_path, day)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
    boards = load_boards(tmp_path)
    assert [b.day for b in boards] == [date(2017, 1, 17), date(2026, 9, 30)]
    assert all(isinstance(b, Board) for b in boards)


def test_讀回存檔_壞掉的檔案要報錯(tmp_path: Path) -> None:
    dest = board_path(tmp_path, date(2017, 1, 18))
    dest.parent.mkdir(parents=True)
    dest.write_bytes(gzip.compress(b""))
    with pytest.raises(BoardError):
        load_boards(tmp_path)


def test_接到股價() -> None:
    boards = [
        parse(gzip.decompress(OLD.read_bytes())),
        parse(gzip.decompress(NEW.read_bytes())),
    ]
    prices = pd.DataFrame({"code": ["1101", "5388"], "day": ["2026-09-30"] * 2})
    linked = link_to_prices(boards, prices)
    assert linked.bonds == len({b.code for x in boards for b in x.bonds})
    assert linked.underlyings == len({b.underlying for x in boards for b in x.bonds})
    assert set(linked.priced) == {"1101", "5388"}
    assert "1258" in linked.missing
    assert linked.bonds_priced == sum(
        1
        for code in {b.code for x in boards for b in x.bonds}
        if code[:4] in {"1101", "5388"}
    )
