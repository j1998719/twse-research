from datetime import date
from pathlib import Path

import pytest

import src.holidays as hol


PAYLOAD = {
    "stat": "ok",
    "fields": ["日期", "名稱", "說明"],
    "data": [
        ["2026-01-01", "中華民國開國紀念日", "依規定放假1日。"],
        ["2026-01-02", "國曆新年開始交易日", "國曆新年開始交易。"],
        ["2026-02-11", "農曆春節前最後交易日", "農曆春節前最後交易。"],
        ["2026-02-12", "市場無交易,僅辦理結算交割作業", ""],
        ["2026-10-09", "國慶日", "國慶日為10月10日適逢星期六,於10月9日(星期五)補假。"],
        ["not a date", "壞掉的列", ""],
    ],
}


def test_開始交易和最後交易那種是交易日_不算休市() -> None:
    got = hol.parse(PAYLOAD)
    assert got == {date(2026, 1, 1), date(2026, 2, 12), date(2026, 10, 9)}


def test_欄位不對就是空的() -> None:
    assert hol.parse({"fields": ["x"], "data": [["2026-01-01"]]}) == set()


def test_抓到就存_抓不到就用快取(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hol, "_fetch", lambda _year: PAYLOAD)
    today = date(2026, 10, 7)
    assert date(2026, 10, 9) in hol.load([2026], tmp_path, today=today)
    assert (tmp_path / "holidays_2026.json").exists()

    def down(_year: int) -> dict:
        raise OSError

    monkeypatch.setattr(hol, "_fetch", down)
    # 抓不到的時候用手上的快取
    assert date(2026, 10, 9) in hol.load([2026], tmp_path, today=date(2027, 6, 1))
    # 明年還沒公告也沒有快取,回空集合而不是壞掉
    assert hol.load([2027], tmp_path, today=today) == set()
