"""可轉債折溢價與深度折價事件(#64,事前登記見 issue)。"""

import pandas as pd
import pytest

from src.cbquote import Quote, QuoteDay
from src.run_cb_premium import discount_events, premiums


DAYS = pd.bdate_range("2020-01-02", periods=150)


def _q(code: str, close: float | None, ref: float = 100.0) -> Quote:
    return Quote(
        code=code,
        name="測試",
        close=close,
        units=1 if close else None,
        amount=None,
        reference=ref,
    )


def test_折溢價_債價除以轉換價值() -> None:
    day = DAYS[0].date()
    quotes = [QuoteDay(day, (_q("11111", 98.0), _q("22221", None, 105.0)))]
    conv = {("11111", day): 40.0, ("22221", day): 50.0}
    stock = {"1111": {day: 40.0}, "2222": {day: 50.0}}
    got = premiums(quotes, lambda c, d: conv.get((c, d)), stock)
    a = got.set_index("code")
    # 轉換價值 = 100 × 40 / 40 = 100;債 98 → 折價 2%
    assert a.loc["11111", "prem"] == pytest.approx(-0.02)
    assert bool(a.loc["11111", "traded"])
    # 沒成交:用參考價,標成沒成交
    assert a.loc["22221", "prem"] == pytest.approx(0.05)
    assert not bool(a.loc["22221", "traded"])


def test_沒有轉換價或股價就跳過() -> None:
    day = DAYS[0].date()
    got = premiums([QuoteDay(day, (_q("11111", 98.0),))], lambda _c, _d: None, {})
    assert got.empty


def test_深度折價事件_只看有成交的_60_天只算一次() -> None:
    frame = pd.DataFrame(
        {
            "code": ["11111", "11111", "11111", "22221"],
            "day": [DAYS[5].date(), DAYS[10].date(), DAYS[80].date(), DAYS[5].date()],
            "traded": [True, True, True, False],
            "prem": [-0.03, -0.04, -0.025, -0.10],
        }
    )
    # 22221 沒成交不算;11111 第 10 天在 60 天內;第 80 天離第 10 天 70 天 → 算
    assert discount_events(frame, DAYS) == [("1111", DAYS[5]), ("1111", DAYS[80])]
