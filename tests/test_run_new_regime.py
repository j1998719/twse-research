"""#65:新制處置「公告後最早買、出關前一天賣」的事件。"""

from __future__ import annotations

import pandas as pd

from src.run_new_regime import new_regime_events


def _punish(code: str, nth: int, announced: str, start: str, end: str) -> dict:
    return {
        "code": code,
        "nth": nth,
        "announced": announced,
        "start": start,
        "end": end,
    }


def test_buy_after_announcement_sell_day_before_release() -> None:
    days = pd.bdate_range("2026-08-03", "2026-08-31")
    punishes = pd.DataFrame(
        [
            # 8/12(三)盤後公告,8/13–8/19 處置,8/20 出關 → 8/13 買、8/19 賣
            _punish("1234", 2, "2026-08-12", "2026-08-13", "2026-08-19"),
            # 舊制(8/10 以前開始)不算
            _punish("5678", 1, "2026-08-05", "2026-08-06", "2026-08-19"),
            # 不編號的措施不算
            _punish("9999", 0, "2026-08-12", "2026-08-13", "2026-08-19"),
            # 還沒出關(出關日超過資料)不算
            _punish("4321", 1, "2026-08-25", "2026-08-26", "2026-09-01"),
        ]
    )
    got = new_regime_events(punishes, days)
    assert got.to_dict("records") == [
        {
            "code": "1234",
            "nth": 2,
            "buy": pd.Timestamp("2026-08-13"),
            "sell": pd.Timestamp("2026-08-19"),
        }
    ]


def test_announced_too_late_to_hold_is_dropped() -> None:
    days = pd.bdate_range("2026-08-03", "2026-08-31")
    # 公告後第一個交易日就是出關前一天 → 買點不早於賣點,做不了
    punishes = pd.DataFrame(
        [_punish("1234", 1, "2026-08-18", "2026-08-19", "2026-08-19")]
    )
    assert new_regime_events(punishes, days).empty
