"""櫃買中心的行情與處置公告。"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import TYPE_CHECKING

import pytest

from src.prices import TAIPEI
from src.tpex import (
    cached_quotes,
    clean_text,
    is_common_stock,
    normalise,
    parse_disposals,
    parse_quotes,
    roc,
    roc_to_date,
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
        with pytest.raises(ValueError, match="缺欄位"):
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

    def test_當天寫的空檔案要重抓(self, tmp_path: Path, monkeypatch) -> None:
        # 10-07 00:58 問 10-07 還沒收盤,存了空檔 —— 那不代表 10-07 沒交易(#37)
        empty = tmp_path / "otc_20261007.json"
        empty.write_text("", encoding="utf-8")
        same_day = datetime(2026, 10, 7, 0, 58, tzinfo=TAIPEI).timestamp()
        os.utime(empty, (same_day, same_day))
        monkeypatch.setattr(
            "src.tpex.fetch_quotes",
            lambda _: _payload(QUOTE_FIELDS, [_quote_row("3105")]),
        )
        assert cached_quotes(date(2026, 10, 7), tmp_path, pause=0) is not None

    def test_隔天之後寫的空檔案才算非交易日(self, tmp_path: Path, monkeypatch) -> None:
        empty = tmp_path / "otc_20261010.json"
        empty.write_text("", encoding="utf-8")
        next_day = datetime(2026, 10, 11, 8, 0, tzinfo=TAIPEI).timestamp()
        os.utime(empty, (next_day, next_day))
        monkeypatch.setattr("src.tpex.fetch_quotes", lambda _: pytest.fail("不該再抓"))
        assert cached_quotes(date(2026, 10, 10), tmp_path, pause=0) is None

    def test_快取的內容讀回來和抓到的一樣(self, tmp_path: Path, monkeypatch) -> None:
        payload = _payload(QUOTE_FIELDS, [_quote_row("3105")])
        monkeypatch.setattr("src.tpex.fetch_quotes", lambda _: payload)
        first = cached_quotes(date(2026, 9, 23), tmp_path, pause=0)
        monkeypatch.setattr("src.tpex.fetch_quotes", lambda _: {"tables": []})
        second = cached_quotes(date(2026, 9, 23), tmp_path, pause=0)
        assert first == second


class TestCleanText:
    """這個來源的文字欄位會夾帶相對連結,不清掉欄位一樣長不出錯。"""

    def test_去掉夾帶的相對連結(self) -> None:
        raw = "豪勉(../../mainboard/listed/company-detail.html?code=6218)"
        assert clean_text(raw) == "豪勉"

    def test_處置原因裡的連結也清掉(self) -> None:
        raw = "因連續3個營業日達本中心作業要點第四條第一項第一款(./attention.html)"
        assert clean_text(raw).endswith("第一款")

    def test_正常的括號不會被誤刪(self) -> None:
        # 只清「以 . 或 / 開頭」的括號內容 —— 公告文字本身有很多正常括號
        raw = "豪勉科技股份有限公司股票(代號:6218)"
        assert clean_text(raw) == raw

    def test_前後空白一起去掉(self) -> None:
        assert clean_text("  豪勉  ") == "豪勉"

    def test_空值不會炸(self) -> None:
        assert clean_text("") == ""


class TestRocToDate:
    def test_民國轉西元(self) -> None:
        assert roc_to_date("115/09/23") == date(2026, 9, 23)

    def test_前後空白可以(self) -> None:
        assert roc_to_date(" 109/01/02 ") == date(2020, 1, 2)

    def test_西元年被當民國年要擋掉(self) -> None:
        # 不擋的話 2026+1911=3937,而且完全不會報錯 —— [#13] 踩過這個
        assert roc_to_date("2026/09/23") is None

    def test_欄位數不對回_None(self) -> None:
        assert roc_to_date("115/09") is None
        assert roc_to_date("") is None

    def test_不是數字回_None(self) -> None:
        assert roc_to_date("一一五/09/23") is None

    def test_不存在的日期回_None(self) -> None:
        assert roc_to_date("115/02/30") is None


class TestNormalise:
    def _row(self, **over: str) -> dict[str, str]:
        base = {
            "公布日期": "115/09/22",
            "證券代號": "6218",
            "證券名稱": "豪勉(../../x.html?code=6218)",
            "處置起訖時間": "115/09/23~115/10/05",
            "處置原因": "連續3個營業日",
            "處置內容": "因連續3個營業日達本中心作業要點第四條第一項第一款",
            "累計": "6",
        }
        base.update(over)
        return base

    def test_轉成和上市一樣的欄位(self) -> None:
        got = normalise(self._row())
        assert got is not None
        assert got["code"] == "6218"
        assert got["name"] == "豪勉"
        assert got["start"] == date(2026, 9, 23)
        assert got["end"] == date(2026, 10, 5)
        assert got["announced"] == date(2026, 9, 22)
        assert got["market"] == "otc"

    def test_帶重複處置字樣的算第二次(self) -> None:
        # 上櫃沒有「處置措施」欄,重複處置寫在內容的文字裡。實測 36.8% 帶
        # 這句話,和上市的 34% 第二次處置率互相印證
        got = normalise(
            self._row(處置內容="最近30個營業日內曾發布處置,又因連續3個營業日")
        )
        assert got is not None
        assert got["nth"] == 2
        assert got["measure"] == "第二次處置"

    def test_沒有那句話的算第一次(self) -> None:
        got = normalise(self._row())
        assert got is not None
        assert got["nth"] == 1

    def test_累計那一欄不會被當成次數(self) -> None:
        # 累計是相對查詢區間算的,換個區間就變。[#8] 把它當次數,算出 70%
        # 的第二次處置率(真值 34%)
        got = normalise(self._row(累計="12"))
        assert got is not None
        assert got["nth"] == 1

    def test_期間格式不對回_None(self) -> None:
        # 猜一個日期比少一筆事件糟得多
        assert normalise(self._row(處置起訖時間="115/09/23")) is None

    def test_日期解不出來回_None(self) -> None:
        assert normalise(self._row(公布日期="爛資料")) is None
        assert normalise(self._row(處置起訖時間="爛~資料")) is None

    def test_結束早於開始回_None(self) -> None:
        assert normalise(self._row(處置起訖時間="115/10/05~115/09/23")) is None

    def test_同一天開始結束可以(self) -> None:
        got = normalise(self._row(處置起訖時間="115/09/23~115/09/23"))
        assert got is not None
        assert got["start"] == got["end"]


class TestUnnumberedMeasure:
    """不編號的措施要給 nth=0,和上市一致 —— 研究用 nth > 0 篩掉它們。"""

    def _detail(self, *, unnumbered: bool, repeat: bool = False) -> str:
        head = "最近30個營業日內曾發布處置," if repeat else ""
        tail = (
            "另依本中心業務規則第12條規定:各證券商於投資人每日委託買賣"
            if unnumbered
            else "單筆委託"
        )
        return f"{head}因連續3個營業日改以人工管制之撮合終端機執行撮合作業,{tail}"

    def _row(self, detail: str) -> dict[str, str]:
        return {
            "公布日期": "115/09/22",
            "證券代號": "3664",
            "證券名稱": "安瑞",
            "處置起訖時間": "115/09/04~115/09/10",
            "處置原因": "連續3個營業日",
            "處置內容": detail,
        }

    def test_引用業務規則第12條的給零(self) -> None:
        # 上市把這類寫成「人工管制撮合」並給 nth=0。上櫃沒有措施欄,但這個
        # 條文引用把兩群分得乾乾淨淨:187 列全部有、另外 1632 列全部沒有
        got = normalise(self._row(self._detail(unnumbered=True)))
        assert got is not None
        assert got["nth"] == 0
        assert got["measure"] == "人工管制撮合"

    def test_沒有引用的照舊編號(self) -> None:
        got = normalise(self._row(self._detail(unnumbered=False)))
        assert got is not None
        assert got["nth"] == 1

    def test_不編號優先於重複處置的判斷(self) -> None:
        # 兩個字樣同時出現時,不編號要贏 —— 不然它會被當成第二次處置收進樣本
        got = normalise(self._row(self._detail(unnumbered=True, repeat=True)))
        assert got is not None
        assert got["nth"] == 0

    def test_這一類進不了樣本(self) -> None:
        # 研究篩 nth > 0。實測這 187 列裡有 106 筆會通過其他篩選,而它們
        # 沒有訊號(中位數 +0.50%、勝率 52.8%、p=0.60)—— 收進來等於自我稀釋
        rows = [
            self._row(self._detail(unnumbered=True)),
            self._row(self._detail(unnumbered=False)),
        ]
        got = [normalise(r) for r in rows]
        kept = [x for x in got if x and int(str(x["nth"])) > 0]
        assert len(kept) == 1


class TestDisposalFieldValidation:
    """每個下游會用到的欄位都要檢查,不能只驗證證券代號。"""

    def _fields(self, drop: str) -> list[str]:
        return [f for f in DISPOSAL_FIELDS if f != drop]

    def test_少了處置內容要出錯(self) -> None:
        # 這是後果最嚴重的一個:detail 變空字串 -> 每一筆都判成第一次處置,
        # 列數不變、不報錯,第二次處置的分組安靜消失
        with pytest.raises(ValueError, match="缺欄位"):
            list(parse_disposals(_payload(self._fields("處置內容"), [["x"] * 9])))

    def test_少了處置起訖時間要出錯(self) -> None:
        with pytest.raises(ValueError, match="缺欄位"):
            list(parse_disposals(_payload(self._fields("處置起訖時間"), [["x"] * 9])))

    def test_少了公布日期要出錯(self) -> None:
        with pytest.raises(ValueError, match="缺欄位"):
            list(parse_disposals(_payload(self._fields("公布日期"), [["x"] * 9])))

    def test_欄位齊全就不會出錯(self) -> None:
        row = [
            "1",
            "115/09/22",
            "6218",
            "豪勉",
            "6",
            "115/09/23~115/10/05",
            "連續3個營業日",
            "因連續3個營業日",
            "100",
            "15",
        ]
        assert len(list(parse_disposals(_payload(DISPOSAL_FIELDS, [row])))) == 1
