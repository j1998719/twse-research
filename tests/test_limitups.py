"""漲停的事件與分組(#27,事前登記見 issue)。"""

import pandas as pd
import pytest

from src.events.limitups import limit_up_events
from src.market import limit_up


DAYS = pd.bdate_range("2024-01-01", periods=80)


def _panel(
    closes: list[float],
    *,
    flat_on: set[int] | None = None,
    vols: list[float] | None = None,
) -> pd.DataFrame:
    rows = []
    for i, (day, c) in enumerate(zip(DAYS, closes, strict=False)):
        lo = c if flat_on and i in flat_on else c * 0.97
        rows.append(
            {
                "day": day,
                "code": "A",
                "open": lo,
                "high": c,
                "low": lo,
                "close": c,
                "volume": (vols or [1000.0] * 80)[i],
            }
        )
    return pd.DataFrame(rows)


def _rally(start: float, n: int) -> list[float]:
    out, px = [], start
    for _ in range(n):
        px = limit_up(px)
        out.append(px)
    return out


def test_收在漲停價才算_第幾根要連續算() -> None:
    closes = [100.0] * 65 + _rally(100.0, 3) + [100.0] * 12
    got = limit_up_events(_panel(closes), set())
    assert list(got.day) == [DAYS[65], DAYS[66], DAYS[67]]
    assert list(got.streak) == [1, 2, 3]


def test_一價到底_開高低收都是漲停價() -> None:
    closes = [100.0] * 65 + _rally(100.0, 2) + [100.0] * 13
    got = limit_up_events(_panel(closes, flat_on={66}), set())
    assert list(got.one_price) == [False, True]


def test_量比_跟前_20_日均量比() -> None:
    vols = [1000.0] * 65 + [5000.0] + [1000.0] * 14
    closes = [100.0] * 65 + _rally(100.0, 1) + [100.0] * 14
    got = limit_up_events(_panel(closes, vols=vols), set())
    assert got.vol_ratio.iloc[0] == pytest.approx(5.0)


def test_前_60_日漲幅() -> None:
    closes = [95.0] * 4 + [100.0] * 61 + _rally(100.0, 1) + [100.0] * 14
    got = limit_up_events(_panel(closes), set())
    # 事件前一天收 100、61 個交易日前收 100 → 0%(更早的 95 不在窗口裡)
    assert got.prior60.iloc[0] == pytest.approx(0.0)


def test_除權息日的漲停不算() -> None:
    closes = [100.0] * 65 + _rally(100.0, 1) + [100.0] * 14
    assert limit_up_events(_panel(closes), {("A", DAYS[65])}).empty
