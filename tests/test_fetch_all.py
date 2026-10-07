"""按年分段查處置公告時,跨年的那幾筆兩段都會回來(#59)。"""

from datetime import date

from src.fetch_all import unique_punishes
from src.twse import Punish


def _punish(code: str, announced: date, start: date, end: date, nth: int = 1) -> Punish:
    return Punish(
        announced=announced,
        code=code,
        name="測試",
        nth=nth,
        measure="第一次處置",
        condition="連續三次",
        start=start,
        end=end,
        detail="",
    )


def test_跨年的處置兩段都查到_只留一筆() -> None:
    a = _punish("2038", date(2020, 12, 29), date(2020, 12, 30), date(2021, 1, 13))
    b = _punish("2009", date(2020, 12, 24), date(2020, 12, 25), date(2021, 1, 8))
    got = unique_punishes([a, b, a])
    assert got == [a, b]


def test_同一檔不同期間的處置都留著() -> None:
    a = _punish("3308", date(2023, 4, 14), date(2023, 4, 17), date(2023, 4, 28))
    b = _punish("3308", date(2023, 4, 19), date(2023, 4, 20), date(2023, 5, 4), nth=2)
    assert unique_punishes([a, b]) == [a, b]
