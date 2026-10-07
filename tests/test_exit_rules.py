"""停損 / 停利有沒有幫助(#15,事前登記見 issue)。

12 個交易日,處置在 D8 結束 → D9 出關。t−6 = D3 收盤買,t−1 = D8 收盤賣。
收盤後才知道觸發,所以在下一個交易日收盤賣;觸發在 D7(t−2)的話,
下一天就是原定賣出日,不算觸發。
"""

from datetime import date

import pandas as pd
import pytest

from src.disposition_study import exit_rule, pre_release_run
from src.market import limit_down


DAYS = pd.bdate_range("2026-03-02", periods=12)
PUNISH = pd.DataFrame(
    [
        {
            "code": "1111",
            "name": "測試股",
            "nth": 1,
            "measure": "第一次處置",
            "start": date(2026, 3, 2),
            "end": DAYS[8].date(),
        }
    ]
)


def _prices(closes: list[float]) -> pd.DataFrame:
    frames = [
        pd.DataFrame({"day": DAYS, "code": code, "close": series})
        for code, series in (("1111", closes), ("9999", [50.0] * len(DAYS)))
    ]
    out = pd.concat(frames, ignore_index=True)
    return out.assign(open=out.close, high=out.close, low=out.close)


def _run(closes: list[float], **rule: float) -> pd.Series:
    prices = _prices(closes)
    runs = pre_release_run(PUNISH, prices)
    return exit_rule(runs, prices, **rule).iloc[0]


FLAT = [100.0] * 12


def test_沒觸發就跟原本一樣() -> None:
    row = _run(FLAT, stop=0.05)
    assert not row["triggered"]
    assert row["sell_day"] == DAYS[8].date()
    assert row["gross"] == 0.0


def test_停損_收盤跌破_隔天收盤賣() -> None:
    closes = FLAT.copy()
    closes[4], closes[5] = 94.0, 93.0  # D4 收 −6% → D5 收盤賣 93
    row = _run(closes, stop=0.05)
    assert row["triggered"]
    assert row["sell_day"] == DAYS[5].date()
    assert row["gross"] == pytest.approx(-7.0)


def test_停利_收盤漲過_隔天收盤賣() -> None:
    closes = FLAT.copy()
    closes[4], closes[5] = 109.0, 112.0  # D4 收 +9%(<10%)不觸發
    closes[6], closes[7] = 112.0, 115.0  # D5 收 +12% → D6 收盤賣 112
    row = _run(closes, take=0.10)
    assert row["triggered"]
    assert row["sell_day"] == DAYS[6].date()
    assert row["gross"] == pytest.approx(12.0)


def test_t減2才觸發_隔天就是原定賣出日_不算觸發() -> None:
    closes = FLAT.copy()
    closes[7] = 90.0  # D7 = t−2
    row = _run(closes, stop=0.05)
    assert not row["triggered"]
    assert row["sell_day"] == DAYS[8].date()


def test_停損賣出那天跌停_順延() -> None:
    closes = FLAT.copy()
    closes[4] = 94.0
    closes[5] = limit_down(94.0)  # D5 跌停賣不掉 → D6
    closes[6] = 85.0
    row = _run(closes, stop=0.05)
    assert row["sell_day"] == DAYS[6].date()
    assert row["gross"] == pytest.approx(-15.0)


def test_停損和停利不能一次給兩個() -> None:
    prices = _prices(FLAT)
    with pytest.raises(ValueError, match="一次只測一種"):
        exit_rule(pre_release_run(PUNISH, prices), prices, stop=0.05, take=0.1)


def test_輸出的索引跟_runs_一樣_成對比較才對得上() -> None:
    prices = _prices(FLAT)
    runs = pre_release_run(PUNISH, prices)
    runs.index = pd.Index([42])
    assert list(exit_rule(runs, prices, stop=0.05).index) == [42]
