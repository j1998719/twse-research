"""#9:處置條件的分組。"""

from __future__ import annotations

from src.clauses import window_for
from src.run_condition_split import K2_WINDOWS, day_trading


def test_day_trading_both_markets() -> None:
    assert day_trading("連續三次及當日沖銷標準")
    assert day_trading("連續3個營業日及沖銷標準")
    assert not day_trading("連續三次")
    assert not day_trading("最近10個營業日內有6個營業日")


def test_k2_groups_cover_both_wordings() -> None:
    # 上市、上櫃的同一種條件要落在同一組
    for listed, otc in (
        ("連續三次", "連續3個營業日"),
        ("連續五次", "連續5個營業日"),
        ("最近十個營業日已有六次", "最近10個營業日內有6個營業日"),
    ):
        assert window_for(listed) == window_for(otc) in K2_WINDOWS
