"""事件研究的資料載入。"""

from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING

import pytest

from src.eventdata import available_codes, load_closes, load_weeks
from src.tdcc import BIG_BAND


if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def history(tmp_path: Path) -> Path:
    """兩檔股票、兩週的假集保歷史。故意把週次倒著寫,測排序。"""
    (tmp_path / "9999.json").write_text(
        json.dumps(
            {
                "20260109": {
                    BIG_BAND: {"people": 50, "shares": 1_000, "pct": 50.0},
                    "total": {"people": 100, "shares": 2_000, "pct": 100.0},
                },
                "20260102": {
                    BIG_BAND: {"people": 40, "shares": 800, "pct": 40.0},
                    "total": {"people": 100, "shares": 2_000, "pct": 100.0},
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "8888.json").write_text(json.dumps({}), encoding="utf-8")
    return tmp_path


class TestLoadWeeks:
    def test_讀出週次與級距(self, history: Path) -> None:
        weeks = load_weeks("9999", history)
        assert len(weeks) == 2
        assert weeks[0].big is not None
        assert weeks[0].big.people == 40

    def test_由舊到新排好_不管檔案裡的順序(self, history: Path) -> None:
        # 位置順序是呼叫端對齊報酬和期間的依據,不能靠 JSON 的鍵順序
        days = [w.day for w in load_weeks("9999", history)]
        assert days == [date(2026, 1, 2), date(2026, 1, 9)]

    def test_空的歷史回空清單(self, history: Path) -> None:
        assert load_weeks("8888", history) == []

    def test_檔案不存在要出錯而不是回空清單(self, history: Path) -> None:
        # 回空清單的話,打錯代號會變成「這檔沒有資料」這種看起來合理的結果
        with pytest.raises(FileNotFoundError):
            load_weeks("0000", history)


class TestAvailableCodes:
    def test_列出有歷史的代號並排序(self, history: Path) -> None:
        assert available_codes(history) == ["8888", "9999"]

    def test_空目錄回空清單(self, tmp_path: Path) -> None:
        assert available_codes(tmp_path) == []


@pytest.fixture
def prices(tmp_path: Path) -> Path:
    path = tmp_path / "prices.csv"
    path.write_text(
        "day,code,name,close\n"
        "2025-07-01,1111,舊,10\n"  # 早於 since,要被切掉
        "2025-09-01,1111,甲,100\n"
        "2025-09-02,1111,甲,110\n"
        "2025-09-01,2222,乙,50\n"
        "2025-09-02,2222,乙,\n"  # 缺值
        "2025-09-01,3333,丙,0\n",  # 價格是 0
        encoding="utf-8",
    )
    return path


class TestLoadCloses:
    def test_讀出每檔的收盤序列(self, prices: Path) -> None:
        got = load_closes(prices=prices, since="2025-09-01")
        assert got["1111"] == {
            date(2025, 9, 1): 100.0,
            date(2025, 9, 2): 110.0,
        }

    def test_起始日之前的價格會被切掉(self, prices: Path) -> None:
        got = load_closes(prices=prices, since="2025-09-01")
        assert date(2025, 7, 1) not in got["1111"]

    def test_起始日可以放寬(self, prices: Path) -> None:
        got = load_closes(prices=prices, since="2025-01-01")
        assert date(2025, 7, 1) in got["1111"]

    def test_缺值那天跳過而不是補零(self, prices: Path) -> None:
        # 補 0 會讓那天的報酬變成 -100%
        got = load_closes(prices=prices, since="2025-09-01")
        assert got["2222"] == {date(2025, 9, 1): 50.0}

    def test_價格是零的那天也跳過(self, prices: Path) -> None:
        got = load_closes(prices=prices, since="2025-09-01")
        assert "3333" not in got

    def test_可以只讀指定的幾檔(self, prices: Path) -> None:
        got = load_closes({"2222"}, prices=prices, since="2025-09-01")
        assert set(got) == {"2222"}

    def test_不指定就全部讀_基準要用整個宇集(self, prices: Path) -> None:
        got = load_closes(prices=prices, since="2025-09-01")
        assert set(got) == {"1111", "2222"}

    def test_代號保持字串_不會變成數字(self, prices: Path) -> None:
        # 變成數字的話開頭是 0 的代號會掉一位
        got = load_closes(prices=prices, since="2025-09-01")
        assert all(isinstance(code, str) for code in got)
