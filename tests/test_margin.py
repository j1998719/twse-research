"""資料列取自 2026-10-06 的真實回應,只留需要的幾列。"""

from datetime import date
from pathlib import Path

import pytest

import src.chips
import src.margin
from src.chips import parse_otc_chips
from src.margin import Margin, cached, parse_otc, parse_twse, qualified_fields


DAY = date(2026, 10, 6)

TWSE = {
    "stat": "OK",
    "tables": [
        {"fields": [], "data": []},
        {
            "title": "115年10月06日 融資融券彙總 (股票)",
            "fields": [
                "代號",
                "名稱",
                "買進",
                "賣出",
                "現金償還",
                "前日餘額",
                "今日餘額",
                "次一營業日限額",
                "買進",
                "賣出",
                "現券償還",
                "前日餘額",
                "今日餘額",
                "次一營業日限額",
                "資券互抵",
                "註記",
            ],
            "groups": [
                {"title": "股票", "span": 2},
                {"title": "融資", "span": 6},
                {"title": "融券", "span": 6},
                {"title": "", "span": 1},
                {"title": "", "span": 1},
            ],
            "data": [
                [
                    "　",
                    "合計",
                    "300,989",
                    "318,416",
                    "2,924",
                    "6,831,725",
                    "6,811,374",
                    "192,706,242",
                    "15,517",
                    "12,179",
                    "2,231",
                    "142,827",
                    "137,258",
                    "192,706,242",
                    "6,205",
                    "　",
                ],
                [
                    "2330",
                    "台積電",
                    "1,125",
                    "740",
                    "20",
                    "30,135",
                    "30,500",
                    "6,483,092",
                    "4",
                    "7",
                    "0",
                    "46",
                    "49",
                    "6,483,092",
                    "0",
                    " ",
                ],
                [
                    "0050",
                    "元大台灣50",
                    "1",
                    "1",
                    "0",
                    "10",
                    "10",
                    "1",
                    "0",
                    "0",
                    "0",
                    "0",
                    "0",
                    "1",
                    "0",
                    " ",
                ],
            ],
        },
    ],
}

OTC = {
    "stat": "ok",
    "tables": [
        {
            "totalCount": 2,
            "fields": [
                "代號",
                "名稱",
                "前資餘額(張)",
                "資買",
                "資賣",
                "現償",
                "資餘額",
                "資屬證金",
                "資使用率(%)",
                "資限額",
                "前券餘額(張)",
                "券賣",
                "券買",
                "券償",
                "券餘額",
                "券屬證金",
                "券使用率(%)",
                "券限額",
                "資券相抵(張)",
                "備註",
            ],
            "data": [
                [
                    "00411A",
                    "主動統一前沿科技",
                    "9,786",
                    "219",
                    "386",
                    "0",
                    "9,619",
                    "77",
                    "9.29",
                    "103,519",
                    "12",
                    "0",
                    "0",
                    "0",
                    "12",
                    "0",
                    "0.01",
                    "103,519",
                    "0",
                    "",
                ],
                [
                    "6488",
                    "環球晶",
                    "17,449",
                    "500",
                    "278",
                    "0",
                    "17,671",
                    "0",
                    "1.0",
                    "100",
                    "715",
                    "10",
                    "55",
                    "0",
                    "670",
                    "0",
                    "0.1",
                    "100",
                    "0",
                    "",
                ],
            ],
        }
    ],
}

OTC_CHIPS = {
    "stat": "ok",
    "tables": [
        {
            "fields": ["代號", "名稱", *["x"] * 22],
            "data": [
                [
                    "6488",
                    "環球晶",
                    "4,567,516",
                    "5,085,863",
                    "-518,347",
                    "0",
                    "0",
                    "0",
                    "4,567,516",
                    "5,085,863",
                    "-518,347",
                    "188,000",
                    "82,000",
                    "106,000",
                    "195,000",
                    "122,800",
                    "72,200",
                    "174,343",
                    "142,876",
                    "31,467",
                    "369,343",
                    "265,676",
                    "103,667",
                    "-308,680",
                ],
            ],
        }
    ],
}


def test_分組展開成完整欄名() -> None:
    fields = qualified_fields(TWSE["tables"][1])
    assert fields[:3] == ["股票/代號", "股票/名稱", "融資/買進"]
    assert fields[6] == "融資/今日餘額"
    assert fields[12] == "融券/今日餘額"
    # 沒有標題的分組照原本的欄名
    assert fields[-1] == "註記"


def test_分組寬度對不上就報錯() -> None:
    broken = {**TWSE["tables"][1], "groups": [{"title": "股票", "span": 3}]}
    with pytest.raises(ValueError, match="對不上"):
        qualified_fields(broken)


def test_上市_融資融券分得開_濾掉合計和_ETF() -> None:
    assert parse_twse(TWSE, DAY) == [Margin(DAY, "2330", "twse", 30500, 49)]


def test_上市_欄位變了就報錯() -> None:
    table = {**TWSE["tables"][1], "groups": None}
    with pytest.raises(ValueError, match="欄位變了"):
        parse_twse({"tables": [table]}, DAY)


def test_上櫃_用欄名找() -> None:
    assert parse_otc(OTC, DAY) == [Margin(DAY, "6488", "otc", 17671, 670)]


def test_上櫃_沒有資料是空的() -> None:
    assert parse_otc({"tables": [{"data": []}]}, DAY) == []
    assert parse_twse({"tables": []}, DAY) == []


def test_上櫃三大法人_照位置讀而且驗算合計() -> None:
    (row,) = parse_otc_chips(OTC_CHIPS, DAY)
    assert (row.foreign, row.trust, row.dealer) == (-518347, 106000, 103667)
    assert row.total == -308680


def test_上櫃三大法人_欄位順序變了就報錯() -> None:
    shifted = [OTC_CHIPS["tables"][0]["data"][0][:]]
    shifted[0][13], shifted[0][16] = shifted[0][16], shifted[0][13]
    with pytest.raises(ValueError, match="順序變了"):
        parse_otc_chips({"tables": [{"data": shifted}]}, DAY)


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None


@pytest.mark.parametrize(
    ("day", "remembered"),
    [(date(2026, 10, 3), True), (date(2026, 9, 28), False)],
)
def test_沒有資料_只有週末記成空檔案(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, day: date, remembered: bool
) -> None:
    # 10-03 是週六;09-28 是週一(教師節),平日沒資料可能是限流,不能記住
    monkeypatch.setattr(
        src.margin.urllib.request,
        "urlopen",
        lambda *_a, **_k: _Response(b'{"stat": "ok", "tables": [{"data": []}]}'),
    )
    assert cached(day, tmp_path, otc=True, pause=0) is None
    assert (tmp_path / f"otc_{day:%Y%m%d}.json").exists() is remembered


def test_有資料就存_下次讀快取(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    calls: list[str] = []

    def fake(request: object, **_: object) -> _Response:
        calls.append(str(getattr(request, "full_url", "")))
        return _Response(json.dumps(OTC).encode())

    monkeypatch.setattr(src.margin.urllib.request, "urlopen", fake)
    assert cached(DAY, tmp_path, otc=True, pause=0) == OTC
    assert cached(DAY, tmp_path, otc=True, pause=0) == OTC
    assert len(calls) == 1
    assert "date=2026/10/06" in calls[0]


def test_上櫃三大法人_平日沒資料不記住(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        src.chips.urllib.request,
        "urlopen",
        lambda *_a, **_k: _Response(b'{"stat": "ok", "tables": []}'),
    )
    assert src.chips.fetch_otc_chips(date(2026, 9, 28), tmp_path, pause=0) is None
    assert not list(tmp_path.iterdir())
