"""大戶指標的橫斷面研究(#25,事前登記見 issue)。"""

from datetime import date

import pandas as pd

from src.run_crosssection import entry_after, weekly_changes
from src.weekly import LEVELS


def _week(top: float, mid: float) -> tuple[list[float], list[int]]:
    pct = [0.0] * len(LEVELS)
    pct[11] = mid  # 400–600 張
    pct[14] = top  # 1000+
    return pct, [0] * len(LEVELS)


def test_週變化_新的一週減上一週_從某一級往上加總() -> None:
    w1, w2 = date(2026, 9, 18), date(2026, 9, 25)
    weeks = {
        w1: {"A": _week(50.0, 2.0)},
        w2: {"A": _week(52.0, 1.0), "B": _week(10.0, 0.0)},
    }
    got = weekly_changes(weeks, level=14)
    assert got == {w2: {"A": 2.0}}  # B 上一週沒資料,不算
    assert weekly_changes(weeks, level=11) == {
        w2: {"A": 1.0}
    }  # 400+ = 1000+ 加 400–600


def test_進場是資料日期加_5_天之後的第一個交易日() -> None:
    days = pd.bdate_range("2026-09-21", periods=15)
    # 資料日期 9/25(週五)+ 5 天 = 9/30(週三);進場要嚴格晚於它 → 10/1(週四)
    assert entry_after(date(2026, 9, 25), days) == pd.Timestamp("2026-10-01")
    assert entry_after(date(2026, 10, 20), days) is None
