import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.weekly import (
    LABELS,
    LEVELS,
    fields,
    from_history,
    from_snapshot,
    load_weeks,
    week_closes,
)


def _at(values: dict[int, float]) -> list[float]:
    """15 級的清單,只有指定的級距(分級編號)有值。"""
    return [values.get(lv, 0) for lv in LEVELS]


HEADER = "資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\r\n"


def _snapshot(day: str, rows: dict[str, dict[int, tuple[int, float]]]) -> str:
    out = [HEADER]
    for code, levels in rows.items():
        for level, (people, pct) in levels.items():
            out.append(f"{day},{code:<6},{level},{people},1000,{pct}\r\n")
    return "".join(out)


def test_快照_15級照順序_缺的級距是零() -> None:
    got = from_snapshot(
        _snapshot("20261002", {"3105": {1: (900, 2.5), 12: (3, 1.5), 15: (50, 53.46)}})
    )
    assert got["3105"] == (
        _at({1: 2.5, 12: 1.5, 15: 53.46}),
        _at({1: 900, 12: 3, 15: 50}),
    )


def test_單檔歷史_用級距文字對齊同一個順序() -> None:
    bands = {
        LABELS[0]: [900, 1, 2.5],
        LABELS[11]: [3, 1, 1.5],
        LABELS[14]: [48, 1, 49.69],
        "total": [9, 9, 100.0],
    }
    assert from_history({"3105": bands})["3105"] == (
        _at({1: 2.5, 12: 1.5, 15: 49.69}),
        _at({1: 900, 12: 3, 15: 48}),
    )


def test_合併兩種來源_新的在前_快照優先(tmp_path: Path) -> None:
    archive, history = tmp_path / "tdcc", tmp_path / "weeks"
    archive.mkdir()
    history.mkdir()
    (archive / "dispersion_20261002.csv").write_text(
        _snapshot("20261002", {"3105": {15: (50, 53.46)}}), encoding="utf-8"
    )
    for stamp, people in (("20260924", 48), ("20261002", 1)):
        (history / f"{stamp}.json").write_text(
            json.dumps({"3105": {LABELS[14]: [people, 1, 49.0]}}), encoding="utf-8"
        )
    (history / "broken.json").write_text("{", encoding="utf-8")
    days, weeks = load_weeks(archive, history)
    assert days == [date(2026, 10, 2), date(2026, 9, 24)]
    # 同一週兩邊都有:用快照(50 人),不是單檔歷史(1 人)
    assert weeks[date(2026, 10, 2)]["3105"][1][14] == 50
    assert weeks[date(2026, 9, 24)]["3105"][1][14] == 48


def test_最多幾週(tmp_path: Path) -> None:
    for d in range(1, 6):
        (tmp_path / f"202609{d:02d}.json").write_text("{}", encoding="utf-8")
    days, _ = load_weeks(tmp_path / "none", tmp_path, max_weeks=3)
    assert days == [date(2026, 9, 5), date(2026, 9, 4), date(2026, 9, 3)]


def test_週收盤取當天或之前最後一個交易日() -> None:
    adjusted = pd.DataFrame(
        {
            "code": ["3105"] * 3,
            "day": pd.to_datetime(["2026-09-23", "2026-09-24", "2026-10-01"]),
            "adj_close": [500.0, 502.0, 590.0],
        }
    )
    # 10-02 那天沒有成交:用 10-01;09-24 有
    got = week_closes(
        adjusted, [date(2026, 10, 2), date(2026, 9, 24), date(2026, 9, 1)]
    )
    assert got["3105"] == [590.0, 502.0, None]


def test_一檔的週資料_沒有就是_null() -> None:
    days = [date(2026, 10, 2), date(2026, 9, 24)]
    weeks = {days[0]: {"3105": ([1.0, 0.0, 0.0, 53.456], [1, 0, 0, 50])}, days[1]: {}}
    got = fields("3105", days, weeks, {"3105": [591.0, 502.0]})
    assert got["weekPct"] == [[1.0, 0.0, 0.0, 53.46], None]
    assert got["weekPeople"] == [[1, 0, 0, 50], None]
    assert got["weekClose"] == [591.0, 502.0]
    assert fields("9999", days, weeks, {})["weekClose"] == [None, None]


@pytest.mark.parametrize("empty", [pd.DataFrame(), None])
def test_沒有還原價(empty: pd.DataFrame | None) -> None:
    if empty is None:
        assert (
            week_closes(pd.DataFrame({"code": [], "day": [], "adj_close": []}), [])
            == {}
        )
    else:
        assert week_closes(empty, [date(2026, 10, 2)]) == {}
