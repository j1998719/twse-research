"""可轉債每日行情(rsta0113,#64)。真實的一份(節錄)在 fixtures/cbquote/。"""

from datetime import date
from pathlib import Path

import pytest

from src.cbquote import QuoteError, parse_quotes


FIXTURE = Path(__file__).parent / "fixtures" / "cbquote" / "RSta0113.20260930-C.csv.txt"


def _raw() -> bytes:
    return FIXTURE.read_text(encoding="utf-8").encode("cp950")


def test_解出日期和每一檔_議價列跳過() -> None:
    day = parse_quotes(_raw())
    assert day.day == date(2026, 9, 30)
    assert [q.code for q in day.quotes] == ["11011", "12561"]
    first = day.quotes[0]
    assert (first.close, first.units, first.amount, first.reference) == (
        102.40,
        91,
        9_290_300,
        102.40,
    )


def test_沒成交的收市是空的_參考價還在() -> None:
    q = parse_quotes(_raw()).quotes[1]
    assert q.close is None
    assert q.units is None
    assert q.reference == 101.95


@pytest.mark.parametrize("raw", [b"", "<html>錯誤頁</html>".encode("cp950") * 200])
def test_解不出來就報錯_不是安靜地回空的(raw: bytes) -> None:
    with pytest.raises(QuoteError):
        parse_quotes(raw)


def test_日行情的月份列表也解得出來() -> None:
    # 列表解析器原本寫死只認看板的檔名(RSdrs001),日行情是 RSta0113
    from src.cbboard import parse_listing

    payload = {
        "tables": [
            {
                "fields": ["資料日期", "檔案下載"],
                "data": [
                    [
                        "106/01/26",
                        "/storage/bond_zone/tradeinfo/cb/2017/201701/RSta0113.20170126-C.csv",
                    ]
                ],
            }
        ]
    }
    assert parse_listing(payload) == [
        (
            date(2017, 1, 26),
            "/storage/bond_zone/tradeinfo/cb/2017/201701/RSta0113.20170126-C.csv",
        )
    ]
