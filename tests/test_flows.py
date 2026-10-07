from pathlib import Path

import pandas as pd
import pytest

from src.flows import FLOW_KEYS, institutional, load_flows, margin_summary


def _chips(rows: list[tuple[str, str, int, int, int]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["day", "code", "foreign", "trust", "dealer"])
    frame["day"] = pd.to_datetime(frame["day"])
    return frame


def _margin(rows: list[tuple[str, str, int, int]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["day", "code", "margin", "short"])
    frame["day"] = pd.to_datetime(frame["day"])
    return frame


DAYS = [f"2026-09-{d:02d}" for d in (21, 22, 23, 24, 25, 29)] + ["2026-10-01"]


def test_近五日用全市場的最後五天_缺的那天算零() -> None:
    rows = [(d, "2330", 1000, 0, 0) for d in DAYS]
    # 冷門股只在最早那天有進出:不在最後 5 天裡,不能往前湊
    rows.append((DAYS[0], "9999", 5_000_000, 0, 0))
    rows.append((DAYS[-1], "9999", 0, 2000, -1000))
    got = institutional(_chips(rows))
    assert got["2330"]["foreign5"] == 5  # 5 天 × 1,000 股 = 5 張
    assert got["9999"]["foreign5"] == 0
    assert (got["9999"]["trust5"], got["9999"]["dealer5"]) == (2, -1)
    # 20 日窗口包含了最早那天
    assert got["9999"]["inst20"] == 5001


def test_融資融券_五日增減與券資比() -> None:
    rows = [(d, "2330", 100 + i, 10) for i, d in enumerate(DAYS)]
    rows.append((DAYS[-1], "6488", 0, 5))  # 融資是 0:券資比算不出來
    got = margin_summary(_margin(rows))
    # 最新(第 7 天)對 5 個交易日前(第 2 天)
    assert got["2330"]["margin"] == 106
    assert got["2330"]["marginChg5"] == 5
    assert got["2330"]["shortChg5"] == 0
    assert got["2330"]["shortRatio"] == pytest.approx(10 / 106 * 100, abs=0.01)
    assert got["6488"]["shortRatio"] is None
    # 6488 五天前沒有資料:增減不知道,不是 0
    assert got["6488"]["marginChg5"] is None


def test_資料不到六天_算不出增減() -> None:
    got = margin_summary(_margin([(DAYS[0], "2330", 1, 1), (DAYS[1], "2330", 2, 1)]))
    assert got["2330"]["marginChg5"] is None


def test_空資料() -> None:
    assert institutional(pd.DataFrame()) == {}
    assert margin_summary(pd.DataFrame()) == {}


def test_合併兩種來源_缺的欄位是_None(tmp_path: Path) -> None:
    chips = tmp_path / "chips.csv"
    chips.write_text(
        "day,code,name,foreign,trust,dealer\n2026-10-01,2330,台積電,3000,0,0\n"
    )
    margin = tmp_path / "margin.csv"
    margin.write_text("day,code,market,margin,short\n2026-10-01,6488,otc,10,1\n")
    got = load_flows([chips, tmp_path / "missing.csv"], margin)
    assert got is not None
    assert set(got["2330"]) == set(FLOW_KEYS)
    assert got["2330"]["foreign5"] == 3
    assert got["2330"]["margin"] is None
    assert got["6488"]["foreign5"] is None
    assert got["6488"]["short"] == 1


def test_什麼都沒有就回_None(tmp_path: Path) -> None:
    assert load_flows([tmp_path / "a.csv"], tmp_path / "b.csv") is None
