import json
from datetime import date
from pathlib import Path

import pytest

import src.fetch_tdcc_history as fh
from src.tdcc import Band, Week


W1, W2 = date(2026, 9, 18), date(2026, 9, 24)


def test_還缺的最新週在前_已經有的跳過(tmp_path: Path) -> None:
    fh.save(tmp_path / "20260924.json", {"2330": {"total": [1, 1, 100.0]}})
    got = fh.todo([W1, W2], ["1101", "2330"], tmp_path)
    assert got == [(W2, "1101"), (W1, "1101"), (W1, "2330")]


def test_壞掉的檔案當成沒有(tmp_path: Path) -> None:
    (tmp_path / "20260924.json").write_text("{not json", encoding="utf-8")
    assert fh.load(tmp_path / "20260924.json") == {}


def test_要補的股票用大戶頁列出的(tmp_path: Path) -> None:
    page = tmp_path / "bigholders.json"
    page.write_text(json.dumps({"rows": [{"code": "2330"}, {"code": "1101"}]}))
    assert fh.universe(tmp_path, page) == ["1101", "2330"]


def test_沒有大戶頁就用快照裡的普通股(tmp_path: Path) -> None:
    (tmp_path / "dispersion_20261002.csv").write_text(
        "資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n"
        "20261002,2330  ,15,1,1,1\n20261002,0050  ,15,1,1,1\n",
        encoding="utf-8",
    )
    assert fh.universe(tmp_path, tmp_path / "missing.json") == ["2330"]


def test_補到的存起來_空表和失敗不記錄_下次再查(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(day: date, code: str) -> Week:
        if code == "9999":
            msg = "connection reset"
            raise OSError(msg)
        bands = {} if code == "8888" else {"1,000,001以上": Band(48, 210, 49.69)}
        return Week(day=day, code=code, bands=bands)

    monkeypatch.setattr(fh, "fetch_week", fake)
    missing = [(W2, "3105"), (W2, "8888"), (W2, "9999"), (W1, "3105")]
    assert fh.backfill(missing, tmp_path, minutes=1, pause=0) == (2, 1, 1)
    assert fh.load(tmp_path / "20260924.json") == {
        "3105": {"1,000,001以上": [48, 210, 49.69]}
    }
    assert set(fh.load(tmp_path / "20260918.json")) == {"3105"}
    # 空表和失敗的那兩筆還在待補清單裡
    assert fh.todo([W2], ["3105", "8888", "9999"], tmp_path) == [
        (W2, "8888"),
        (W2, "9999"),
    ]


def test_時間到就停_已經補的有存(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        fh, "fetch_week", lambda d, c: Week(d, c, {"total": Band(1, 1, 100.0)})
    )
    assert fh.backfill([(W2, "3105")], tmp_path, minutes=0, pause=0) == (0, 0, 0)
    assert fh.backfill([(W2, "3105")], tmp_path, minutes=1, pause=0) == (1, 0, 0)
