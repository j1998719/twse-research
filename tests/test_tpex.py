"""櫃買中心的行情與處置公告。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from src.tpex import (
    cached_quotes,
    is_common_stock,
    parse_disposals,
    parse_quotes,
    roc,
)


if TYPE_CHECKING:
    from pathlib import Path


def _quote_row(code: str, close: str = "497.00") -> list[str]:
    """一列行情。給快取的測試用,不必造一整個 class。"""
    return [code, "某檔", close, "+1.0", "507.00", "518.00", "486.50", "26998000", "1"]


class TestIsCommonStock:
    def test_四碼數字是普通股(self) -> None:
        assert is_common_stock("3105") is True

    def test_零零開頭的_ETF_不是(self) -> None:
        # 這個來源第一列就是 00679B 元大美債
        assert is_common_stock("0050") is False
        assert is_common_stock("00679B") is False

    def test_五碼的轉換公司債不是(self) -> None:
        # 36053 宏致三、22211 大甲一 都會出現在處置公告裡
        assert is_common_stock("36053") is False
        assert is_common_stock("22211") is False

    def test_帶字母的不是(self) -> None:
        assert is_common_stock("00411A") is False

    def test_前後空白會去掉(self) -> None:
        assert is_common_stock(" 3105 ") is True

    def test_太短的不是(self) -> None:
        assert is_common_stock("310") is False
        assert is_common_stock("") is False


class TestRoc:
    def test_西元轉民國(self) -> None:
        assert roc(date(2026, 9, 23)) == "115/09/23"

    def test_月日補零(self) -> None:
        assert roc(date(2020, 1, 2)) == "109/01/02"

    def test_民國元年的邊界(self) -> None:
        assert roc(date(1912, 1, 1)) == "1/01/01"


def _payload(fields: list[str], data: list[list[str]]) -> dict:
    return {"tables": [{"fields": fields, "data": data}]}


QUOTE_FIELDS = [
    "代號",
    "名稱",
    "收盤 ",
    "漲跌",
    "開盤 ",
    "最高 ",
    "最低",
    "成交股數  ",
    " 成交金額(元)",
]


class TestParseQuotes:
    day = date(2026, 9, 23)

    def _row(self, code: str, close: str = "497.00") -> list[str]:
        return [
            code,
            "某檔",
            close,
            "+1.0",
            "507.00",
            "518.00",
            "486.50",
            "26998000",
            "1",
        ]

    def test_讀出一檔的開高低收(self) -> None:
        got = parse_quotes(_payload(QUOTE_FIELDS, [self._row("3105")]), self.day)
        assert len(got) == 1
        assert (got[0].open, got[0].high, got[0].low, got[0].close) == (
            507.0,
            518.0,
            486.5,
            497.0,
        )

    def test_欄名帶空白也認得出來(self) -> None:
        # 這個來源真的長這樣:「收盤 」、「 成交金額(元)」。不 strip 就全部讀不到
        got = parse_quotes(_payload(QUOTE_FIELDS, [self._row("3105")]), self.day)
        assert got[0].close == 497.0

    def test_非普通股會被濾掉(self) -> None:
        rows = [self._row("00679B"), self._row("3105"), self._row("36053")]
        got = parse_quotes(_payload(QUOTE_FIELDS, rows), self.day)
        assert [q.code for q in got] == ["3105"]

    def test_讀不到的價格是_None_而不是零(self) -> None:
        # 補 0 會讓報酬變成 -100%
        row = self._row("3105", close="--")
        got = parse_quotes(_payload(QUOTE_FIELDS, [row]), self.day)
        assert got[0].close is None

    def test_千分位逗號讀得掉(self) -> None:
        row = self._row("3105", close="1,234.50")
        got = parse_quotes(_payload(QUOTE_FIELDS, [row]), self.day)
        assert got[0].close == 1234.5

    def test_非交易日回空清單而不是丟例外(self) -> None:
        assert parse_quotes(_payload(QUOTE_FIELDS, []), self.day) == []

    def test_完全沒有表也回空清單(self) -> None:
        assert parse_quotes({"tables": []}, self.day) == []

    def test_欄位變了要出錯而不是安靜取到錯的欄(self) -> None:
        # 寫死索引的話欄位順序一改就會安靜地取錯,所以缺欄位一定要吵
        with pytest.raises(ValueError, match="欄位變了"):
            parse_quotes(_payload(["代號", "名稱"], [["3105", "穩懋"]]), self.day)

    def test_日期會掛在每一筆上(self) -> None:
        got = parse_quotes(_payload(QUOTE_FIELDS, [self._row("3105")]), self.day)
        assert got[0].day == self.day


DISPOSAL_FIELDS = [
    "編號",
    "公布日期",
    "證券代號",
    "證券名稱",
    "累計",
    "處置起訖時間",
    "處置原因",
    "處置內容",
    "收盤價",
    "本益比",
]


class TestParseDisposals:
    def _row(self, code: str, cumulative: str = "6") -> list[str]:
        return [
            "1",
            "115/09/23",
            code,
            "某檔",
            cumulative,
            "115/09/24~115/10/06",
            "連續3個營業日",
            "因連續3個營業日達本中心作業要點第四條第一項第一款",
            "100.0",
            "15.0",
        ]

    def test_讀出一列(self) -> None:
        got = list(parse_disposals(_payload(DISPOSAL_FIELDS, [self._row("6218")])))
        assert len(got) == 1
        assert got[0]["證券代號"] == "6218"

    def test_累計和處置內容都原樣保留(self) -> None:
        # 「累計」不是第幾次處置 —— [#8] 把它當次數,算出 70% 的第二次處置率
        # (真值 34%)。兩欄都留著,判斷次數交給上層
        (got,) = list(parse_disposals(_payload(DISPOSAL_FIELDS, [self._row("6218")])))
        assert got["累計"] == "6"
        assert "第四條第一項第一款" in got["處置內容"]

    def test_轉換公司債和_ETF_濾掉(self) -> None:
        rows = [self._row("36053"), self._row("6218"), self._row("00679B")]
        got = list(parse_disposals(_payload(DISPOSAL_FIELDS, rows)))
        assert [r["證券代號"] for r in got] == ["6218"]

    def test_沒有資料回空(self) -> None:
        assert list(parse_disposals(_payload(DISPOSAL_FIELDS, []))) == []

    def test_完全沒有表回空(self) -> None:
        assert list(parse_disposals({"tables": []})) == []

    def test_欄位變了要出錯(self) -> None:
        with pytest.raises(ValueError, match="欄位變了"):
            list(parse_disposals(_payload(["編號", "公布日期"], [["1", "115/09/23"]])))


class TestCachedQuotes:
    """抓過的日子要跳過,非交易日也算抓過。"""

    def test_第一次會抓並存檔(self, tmp_path: Path, monkeypatch) -> None:
        calls = []

        def fake(day: date) -> dict:
            calls.append(day)
            return _payload(QUOTE_FIELDS, [_quote_row("3105")])

        monkeypatch.setattr("src.tpex.fetch_quotes", fake)
        got = cached_quotes(date(2026, 9, 23), tmp_path, pause=0)
        assert got is not None
        assert calls == [date(2026, 9, 23)]
        assert (tmp_path / "otc_20260923.json").exists()

    def test_第二次讀快取不再抓(self, tmp_path: Path, monkeypatch) -> None:
        calls = []

        def fake(day: date) -> dict:
            calls.append(day)
            return _payload(QUOTE_FIELDS, [_quote_row("3105")])

        monkeypatch.setattr("src.tpex.fetch_quotes", fake)
        cached_quotes(date(2026, 9, 23), tmp_path, pause=0)
        cached_quotes(date(2026, 9, 23), tmp_path, pause=0)
        assert len(calls) == 1

    def test_非交易日回_None_但留一個空檔案(self, tmp_path: Path, monkeypatch) -> None:
        # 不留空檔案的話,每次重跑都會再問一次那些永遠沒資料的日子 ——
        # 七年下來是幾百個白費的請求
        monkeypatch.setattr(
            "src.tpex.fetch_quotes", lambda _: _payload(QUOTE_FIELDS, [])
        )
        got = cached_quotes(date(2026, 9, 27), tmp_path, pause=0)
        assert got is None
        assert (tmp_path / "otc_20260927.json").read_text(encoding="utf-8") == ""

    def test_快取到的非交易日不會再抓(self, tmp_path: Path, monkeypatch) -> None:
        calls = []

        def fake(day: date) -> dict:
            calls.append(day)
            return _payload(QUOTE_FIELDS, [])

        monkeypatch.setattr("src.tpex.fetch_quotes", fake)
        cached_quotes(date(2026, 9, 27), tmp_path, pause=0)
        cached_quotes(date(2026, 9, 27), tmp_path, pause=0)
        assert len(calls) == 1

    def test_快取的內容讀回來和抓到的一樣(self, tmp_path: Path, monkeypatch) -> None:
        payload = _payload(QUOTE_FIELDS, [_quote_row("3105")])
        monkeypatch.setattr("src.tpex.fetch_quotes", lambda _: payload)
        first = cached_quotes(date(2026, 9, 23), tmp_path, pause=0)
        monkeypatch.setattr("src.tpex.fetch_quotes", lambda _: {"tables": []})
        second = cached_quotes(date(2026, 9, 23), tmp_path, pause=0)
        assert first == second
