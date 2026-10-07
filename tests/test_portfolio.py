"""組合層級的權益曲線(#33)。事件研究算不出來的那一半:每天評價、資金排擠、MDD。"""

import pandas as pd
import pytest

from src.market import ROUND_TRIP_COST_PCT
from src.portfolio import drawdown, losing_streak, simulate, underwater_days


DAYS = pd.bdate_range("2026-01-05", periods=6)
COST = ROUND_TRIP_COST_PCT / 100


def _closes(**series: list[float | None]) -> pd.DataFrame:
    return pd.DataFrame(series, index=DAYS, dtype=float)


def _trades(*rows: tuple[str, int, int, float, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"code": c, "buy_day": DAYS[b], "sell_day": DAYS[s], "buy": bp, "sell": sp}
            for c, b, s, bp, sp in rows
        ]
    )


def test_一筆交易_每天照收盤評價() -> None:
    closes = _closes(A=[100, 100, 110, 120, 120, 120])
    out = simulate(_trades(("A", 1, 3, 100.0, 120.0)), closes, capital=1_000_000)
    eq = out.equity
    assert eq.iloc[0] == 1_000_000
    assert eq.iloc[1] == 1_000_000  # 收盤買進:現金換成等值的股票
    assert eq.iloc[2] == 1_010_000  # 持有中,用當天收盤 110 評價
    # 賣出那天扣來回成本
    assert eq.iloc[3] == pytest.approx(900_000 + 120_000 * (1 - COST))
    assert eq.iloc[-1] == eq.iloc[3]
    assert out.taken == 1
    assert out.skipped == 0


def test_錢不夠買一張就跳過() -> None:
    closes = _closes(A=[100] * 6, B=[100] * 6)
    trades = _trades(("A", 1, 4, 100.0, 100.0), ("B", 2, 4, 100.0, 100.0))
    out = simulate(trades, closes, capital=150_000)
    assert (out.taken, out.skipped) == (1, 1)


def test_同一天先賣再買_賣掉的錢當天就能用() -> None:
    closes = _closes(A=[100] * 6, B=[100] * 6)
    trades = _trades(("A", 1, 3, 100.0, 100.0), ("B", 3, 5, 100.0, 100.0))
    out = simulate(trades, closes, capital=110_000)
    assert out.taken == 2


def test_停牌那天用最後一個收盤評價() -> None:
    closes = _closes(A=[100, 100, None, 130, 130, 130])
    out = simulate(_trades(("A", 1, 4, 100.0, 130.0)), closes, capital=1_000_000)
    assert out.equity.iloc[2] == 1_000_000  # 沒有收盤 → 還是 100
    assert out.equity.iloc[3] == 1_030_000


def test_同時最多幾檔() -> None:
    closes = _closes(A=[100] * 6, B=[100] * 6, C=[100] * 6)
    trades = _trades(
        ("A", 0, 2, 100.0, 100.0), ("B", 1, 3, 100.0, 100.0), ("C", 3, 4, 100.0, 100.0)
    )
    # B 在 D3 收盤賣、C 在 D3 收盤買:先賣再買,同時最多 2 檔
    assert simulate(trades, closes, capital=1_000_000).max_concurrent == 2


def test_最大回檔_高點_低點_回復日() -> None:
    eq = pd.Series([100.0, 120.0, 90.0, 95.0, 130.0, 125.0], index=DAYS)
    dd = drawdown(eq)
    assert dd.pct == pytest.approx(-25.0)
    assert (dd.peak, dd.trough, dd.recovered) == (DAYS[1], DAYS[2], DAYS[4])


def test_最大回檔_還沒回復() -> None:
    eq = pd.Series([100.0, 120.0, 90.0, 95.0, 100.0, 110.0], index=DAYS)
    assert drawdown(eq).recovered is None


def test_最長多久沒創新高_日曆天() -> None:
    # 高點在 D1(週二),D4(週五)才再創新高 → 3 天;之後 D4 到最後一天(下週一)也沒新高 → 3 天
    eq = pd.Series([100.0, 120.0, 90.0, 95.0, 130.0, 125.0], index=DAYS)
    assert underwater_days(eq) == 3
    # 一路沒回來的話,從高點算到最後一天
    eq = pd.Series([100.0, 120.0, 90.0, 95.0, 100.0, 110.0], index=DAYS)
    assert underwater_days(eq) == (DAYS[5] - DAYS[1]).days


def test_最長連續虧損筆數() -> None:
    assert losing_streak([1.0, -1.0, -2.0, -3.0, 2.0, -1.0]) == 3
    assert losing_streak([]) == 0
    # 剛好 0 不算虧
    assert losing_streak([-1.0, 0.0, -1.0]) == 1


# ---- 部位大小的三種 mode(#33,Jordan 2026-10-07)----


def test_fixed_每筆本金的_10_趴_允許零股() -> None:
    closes = _closes(A=[300] * 6)
    out = simulate(
        _trades(("A", 1, 3, 300.0, 330.0)), closes, capital=1_000_000, sizing="fixed"
    )
    # 10 萬 / 300 元 = 333 股(零股);賺 10%
    shares = 333
    assert out.equity.iloc[2] == 1_000_000  # 持有中、價格沒動
    assert out.equity.iloc[3] == pytest.approx(
        1_000_000 - shares * 300 + shares * 330 * (1 - COST)
    )


def test_fixed_不隨淨值變() -> None:
    closes = _closes(A=[100] * 6, B=[100] * 6)
    trades = _trades(("A", 0, 1, 100.0, 200.0), ("B", 2, 4, 100.0, 100.0))
    out = simulate(trades, closes, capital=1_000_000, sizing="fixed")
    # A 賺了一倍,B 還是只買 10 萬 = 1,000 股(本金的 10%),不是淨值的 10%:
    # B 價格沒動,賣掉時淨值只少了這 1,000 股的成本
    assert out.equity.iloc[4] == pytest.approx(out.equity.iloc[3] - 1000 * 100 * COST)
    assert out.taken == 2


def test_fraction_用前一天淨值的_10_趴() -> None:
    closes = _closes(A=[100, 200, 200, 200, 200, 200], B=[100] * 6)
    trades = _trades(("A", 0, 1, 100.0, 200.0), ("B", 3, 5, 100.0, 110.0))
    out = simulate(trades, closes, capital=1_000_000, sizing="fraction")
    # A:10 萬買 1,000 股,翻倍賣掉;D2 收盤淨值 = 90 萬 + 20 萬 × (1 − 成本)
    nav = 900_000 + 200_000 * (1 - COST)
    shares = int(nav * 0.10 // 100)
    assert out.equity.iloc[-1] == pytest.approx(
        nav - shares * 100 + shares * 110 * (1 - COST)
    )


def test_現金不夠買足目標金額就跳過() -> None:
    closes = _closes(**{c: [100] * 6 for c in "ABCDEFGHIJKL"})
    trades = _trades(*[(c, 1, 4, 100.0, 100.0) for c in "ABCDEFGHIJKL"])
    out = simulate(trades, closes, capital=1_000_000, sizing="fixed")
    # 每筆 10 萬,100 萬只買得起 10 筆;成本在賣出時才扣,所以剛好 10 筆
    assert (out.taken, out.skipped) == (10, 2)


def test_lot_是預設() -> None:
    closes = _closes(A=[100] * 6)
    out = simulate(_trades(("A", 1, 3, 100.0, 100.0)), closes, capital=1_000_000)
    assert out.equity.iloc[2] == 1_000_000
    assert out.max_concurrent == 1


def test_不認得的_mode_報錯() -> None:
    with pytest.raises(ValueError, match="sizing"):
        simulate(_trades(), _closes(A=[100] * 6), capital=1, sizing="half")  # type: ignore[arg-type]
