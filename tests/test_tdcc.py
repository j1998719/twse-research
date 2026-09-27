"""集保股權分散表的解析與事件定義。"""

from __future__ import annotations

from datetime import date

from src.tdcc import (
    BIG_BAND,
    Band,
    Week,
    parse_bands,
    rising,
    weekly_changes,
)


def _row(level: int, label: str, people: str, shares: str, pct: str) -> str:
    return (
        f"<tr><td>{level}</td><td>{label}</td>"
        f"<td>{people}</td><td>{shares}</td><td>{pct}</td></tr>"
    )


#: 沒有「差異數調整」的週次:合計是第 16 級
PLAIN = (
    "<table>"
    + "".join(
        [
            _row(1, "1-999", "74,808", "11,246,994", "2.65"),
            _row(15, BIG_BAND, "48", "210,689,943", "49.69"),
            _row(16, "合　計", "125,535", "423,940,384", "100.00"),
        ]
    )
    + "</table>"
)

#: 有「差異數調整」的週次:合計變成第 17 級,而且調整那一列人數是空的
WITH_ADJUST = (
    "<table>"
    + "".join(
        [
            _row(1, "1-999", "49,113", "6,965,129", "1.64"),
            _row(15, BIG_BAND, "64", "232,340,954", "54.80"),
            _row(16, "差異數調整（說明4）", "", "-31,000", "-0.00"),
            _row(17, "合　計", "87,284", "423,940,384", "100.00"),
        ]
    )
    + "</table>"
)


class TestParseBands:
    def test_千張大戶讀得出來(self) -> None:
        bands = parse_bands(PLAIN)
        assert bands[BIG_BAND] == Band(people=48, shares=210_689_943, pct=49.69)

    def test_合計不管在第幾級都認得出來(self) -> None:
        # 這是重點:同一檔股票,有沒有「差異數調整」那一列會讓合計從 16 變成 17。
        # 照分級編號抓的話,有調整的那幾週會把合計當成別的東西。
        assert parse_bands(PLAIN)["total"].people == 125_535
        assert parse_bands(WITH_ADJUST)["total"].people == 87_284

    def test_差異數調整那一列整列跳過(self) -> None:
        bands = parse_bands(WITH_ADJUST)
        assert not any("調整" in key for key in bands)

    def test_有調整的週次千張大戶還是讀得對(self) -> None:
        assert parse_bands(WITH_ADJUST)[BIG_BAND].people == 64

    def test_人數是空的就跳過而不是當成零(self) -> None:
        # 空字串當成 0 會讓「大戶人數歸零」這種假事件冒出來
        html = "<table>" + _row(16, "某一列", "", "-31,000", "-0.00") + "</table>"
        assert parse_bands(html) == {}

    def test_不是五欄的列不理它(self) -> None:
        html = "<table><tr><td>證券代號</td><td>請輸入證券代號</td></tr></table>"
        assert parse_bands(html) == {}

    def test_表頭那種第一欄不是數字的列不理它(self) -> None:
        html = (
            "<table>"
            + _row(0, "x", "1", "2", "3").replace("<td>0</td>", "<td>分級</td>")
            + "</table>"
        )
        assert parse_bands(html) == {}

    def test_空表回空的字典而不是丟例外(self) -> None:
        assert parse_bands("<table></table>") == {}


def _week(day: date, people: int, pct: float, holders: int = 100_000) -> Week:
    return Week(
        day=day,
        code="3105",
        bands={
            BIG_BAND: Band(people=people, shares=people * 1_500_000, pct=pct),
            "total": Band(people=holders, shares=423_940_384, pct=100.0),
        },
    )


class TestWeek:
    def test_抓不到千張大戶時回_None_而不是零(self) -> None:
        assert Week(day=date(2026, 9, 24), code="3105", bands={}).big is None

    def test_總股東人數讀得出來(self) -> None:
        assert _week(date(2026, 9, 24), 48, 49.69, holders=125_535).holders == 125_535

    def test_沒有合計那一列時總股東是_None(self) -> None:
        bare = Week(
            day=date(2026, 9, 24),
            code="3105",
            bands={BIG_BAND: Band(people=48, shares=1, pct=49.69)},
        )
        assert bare.holders is None


class TestWeeklyChanges:
    def test_算出人數與佔比的週變化(self) -> None:
        weeks = [
            _week(date(2026, 1, 2), 48, 47.92),
            _week(date(2026, 1, 9), 54, 49.82),
        ]
        (change,) = weekly_changes(weeks)
        assert change.people_delta == 6
        assert change.pct_delta == 1.9

    def test_第一週不會出現在結果裡(self) -> None:
        weeks = [_week(date(2026, 1, 2), 48, 47.92), _week(date(2026, 1, 9), 54, 49.82)]
        assert [c.day for c in weekly_changes(weeks)] == [date(2026, 1, 9)]

    def test_人數減少是負的(self) -> None:
        weeks = [
            _week(date(2026, 4, 17), 64, 54.80),
            _week(date(2026, 4, 24), 61, 52.98),
        ]
        (change,) = weekly_changes(weeks)
        assert change.people_delta == -3
        assert change.pct_delta == -1.82

    def test_順序亂掉也會先排好(self) -> None:
        weeks = [
            _week(date(2026, 1, 9), 54, 49.82),
            _week(date(2026, 1, 2), 48, 47.92),
        ]
        (change,) = weekly_changes(weeks)
        assert change.day == date(2026, 1, 9)
        assert change.people_delta == 6

    def test_讀不到大戶的那幾週跳過(self) -> None:
        weeks = [
            _week(date(2026, 1, 2), 48, 47.92),
            Week(day=date(2026, 1, 9), code="3105", bands={}),
            _week(date(2026, 1, 16), 52, 49.06),
        ]
        (change,) = weekly_changes(weeks)
        # 跳過中間那一週之後,變化是頭尾相比,不是憑空補一個零
        assert change.people_delta == 4

    def test_只有一週時沒有變化可算(self) -> None:
        assert weekly_changes([_week(date(2026, 1, 2), 48, 47.92)]) == []

    def test_佔比差會四捨五入到兩位(self) -> None:
        weeks = [
            _week(date(2026, 1, 2), 48, 47.92),
            _week(date(2026, 1, 9), 48, 49.82),
        ]
        (change,) = weekly_changes(weeks)
        assert change.pct_delta == 1.9


class TestRising:
    def test_只留人數增加的那幾週(self) -> None:
        weeks = [
            _week(date(2026, 1, 2), 48, 47.0),
            _week(date(2026, 1, 9), 54, 49.0),
            _week(date(2026, 1, 16), 52, 48.0),
        ]
        events = rising(weekly_changes(weeks))
        assert [e.day for e in events] == [date(2026, 1, 9)]

    def test_門檻可以調高(self) -> None:
        weeks = [
            _week(date(2026, 1, 2), 48, 47.0),
            _week(date(2026, 1, 9), 49, 48.0),
        ]
        assert rising(weekly_changes(weeks), min_people=3) == []

    def test_持平不算增加(self) -> None:
        weeks = [
            _week(date(2026, 1, 2), 48, 47.0),
            _week(date(2026, 1, 9), 48, 47.0),
        ]
        assert rising(weekly_changes(weeks)) == []
