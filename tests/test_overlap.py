"""第二次處置在第一次還沒結束時就公告(#32)。

重疊深度 = 第一次的結束日 − 第二次的公告日,用營業日(交易日位置差)。
≥ 0 就是「第一次還沒結束就公告了」。
"""

import pandas as pd

from src.run_overlap import overlap_depth


DAYS = pd.bdate_range("2026-03-02", periods=40)


def _row(
    code: str, nth: int, announced: int, start: int, end: int
) -> dict[str, object]:
    return {
        "code": code,
        "nth": nth,
        "announced": DAYS[announced],
        "start": DAYS[start],
        "end": DAYS[end],
    }


def test_第一次還沒結束就公告第二次_深度是正的() -> None:
    rows = pd.DataFrame([_row("A", 1, 0, 1, 10), _row("A", 2, 7, 11, 20)])
    got = overlap_depth(rows, DAYS)
    # 第一次結束在 DAYS[10],第二次在 DAYS[7] 公告 → 重疊 3 個營業日
    assert got.tolist() == [None, 3]


def test_第一次結束之後才公告_深度是負的() -> None:
    rows = pd.DataFrame([_row("A", 1, 0, 1, 10), _row("A", 2, 13, 14, 20)])
    assert overlap_depth(rows, DAYS).tolist() == [None, -3]


def test_找同一檔最近一次在它之前公告的處置() -> None:
    rows = pd.DataFrame(
        [
            _row("A", 1, 0, 1, 5),
            _row("B", 1, 5, 6, 30),
            _row("A", 1, 10, 11, 18),
            _row("A", 2, 15, 19, 25),
        ]
    )
    # A 的第二次看最近的那次(DAYS[18] 結束),不是更早那次、也不是 B
    assert overlap_depth(rows, DAYS).tolist()[3] == 3


def test_第一次處置和找不到前一次的是空的() -> None:
    rows = pd.DataFrame([_row("A", 2, 5, 6, 12)])
    assert overlap_depth(rows, DAYS).tolist() == [None]
