"""處置前的流動性水位(#29、#31、#30)。

W1:這一次處置開始前 20 個交易日的成交金額中位數。
W2:整串的**第一次**處置開始前 20 個交易日。第二次處置的 W1 窗口有一半落在
第一次處置期間(#31),W2 才是真正處置前的流動性。
「整串」:同一檔,這次公告日「含當天往前 30 個營業日」內有上一次公告,就是同一串
(#16)。換成交易日位置就是差 ≤ 29;#16 量過,嚴格夾在中間的營業日 ≤ 28 是唯一的
誤判極小值。nth = 0(督導會報決議)不算一次。
"""

from datetime import date

import pandas as pd
import pytest

from src.liquidity import chain_starts, daily_value, level


DAYS = pd.bdate_range("2026-01-05", periods=100)


def _punish(code: str, announced: int, start: int, nth: int) -> dict[str, object]:
    return {
        "code": code,
        "announced": DAYS[announced],
        "start": DAYS[start],
        "end": DAYS[start + 9],
        "nth": nth,
    }


def test_成交金額是股數乘收盤_沒成交是零() -> None:
    prices = pd.DataFrame(
        {
            "day": [DAYS[0], DAYS[1], DAYS[0]],
            "code": ["A", "A", "B"],
            "close": [10.0, 11.0, 5.0],
            "volume": [1000.0, None, 2000.0],
        }
    )
    value = daily_value(prices)
    assert value.at[DAYS[0], "A"] == 10_000
    assert value.at[DAYS[1], "A"] == 0
    assert value.at[DAYS[0], "B"] == 10_000


def test_水位是之前_20_個交易日的中位數_不含當天() -> None:
    value = pd.DataFrame({"A": [float(i) for i in range(100)]}, index=DAYS)
    # DAYS[30] 之前 20 天 = 10..29,中位數 19.5;當天的 30 不算
    assert level(value, "A", DAYS[30]) == pytest.approx(19.5)


def test_前面不滿_20_天就算不出來() -> None:
    value = pd.DataFrame({"A": [1.0] * 100}, index=DAYS)
    assert level(value, "A", DAYS[10]) is None
    assert level(value, "Z", DAYS[30]) is None


def test_同一串_第二次的串頭是第一次的開始日() -> None:
    rows = pd.DataFrame(
        [
            _punish("A", 20, 21, 1),
            _punish("A", 32, 33, 2),  # 跟上一次公告隔 12 個營業日 → 同一串
            _punish("A", 70, 71, 1),  # 隔 38 個營業日 → 新的一串
            _punish("B", 32, 33, 1),
        ]
    )
    got = chain_starts(rows, DAYS)
    assert got.tolist() == [DAYS[21], DAYS[21], DAYS[71], DAYS[33]]


def test_含當天往前_30_個營業日_位置差_29_是同一串_30_不是() -> None:
    rows = pd.DataFrame([_punish("A", 10, 11, 1), _punish("A", 39, 40, 2)])
    assert chain_starts(rows, DAYS).tolist() == [DAYS[11], DAYS[11]]
    rows = pd.DataFrame([_punish("A", 10, 11, 1), _punish("A", 40, 41, 2)])
    assert chain_starts(rows, DAYS).tolist() == [DAYS[11], DAYS[41]]


def test_督導會報決議_nth_0_不算一次() -> None:
    rows = pd.DataFrame([_punish("A", 10, 11, 0), _punish("A", 20, 21, 1)])
    # nth = 0 自己不成串、也不把後面那次接成第二次;它自己的串頭就是自己
    assert chain_starts(rows, DAYS).tolist() == [DAYS[11], DAYS[21]]


def test_輸出的順序跟輸入一樣() -> None:
    rows = pd.DataFrame([_punish("A", 32, 33, 2), _punish("A", 20, 21, 1)])
    assert chain_starts(rows, DAYS).tolist() == [DAYS[21], DAYS[21]]


def test_日期可以是_date() -> None:
    rows = pd.DataFrame([{**_punish("A", 20, 21, 1), "announced": date(2026, 2, 2)}])
    assert len(chain_starts(rows, DAYS)) == 1


def test_每一筆的_W1_W2_百萬元() -> None:
    from src.liquidity import chain_levels

    prices = pd.DataFrame(
        {
            "day": DAYS,
            "code": "A",
            "close": 100.0,
            "volume": [float(i) * 10_000 for i in range(100)],
        }
    )
    rows = pd.DataFrame([_punish("A", 30, 31, 1), _punish("A", 40, 41, 2)])
    got = chain_levels(rows, prices, DAYS)
    # 成交金額第 i 天 = i 百萬;W1 是開始日之前 20 天的中位數,W2 用串頭(DAYS[31])
    assert got.w1.tolist() == pytest.approx([20.5, 30.5])
    assert got.w2.tolist() == pytest.approx([20.5, 20.5])
