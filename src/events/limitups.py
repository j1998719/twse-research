"""漲停的事件與「漲停的質」(#27,事前登記見 issue)。

漲停日 = 收盤 ≥ 用前一日收盤和交易所檔位算的漲停價(market.limit_up,跟 #45 同一套)。
除權息 / 減資那天的漲停價是用參考價算的,不是前一日收盤,所以那天的漲停不算(會誤判)。

每個漲停日帶著四個分組變數:
- one_price:一價到底(開 = 高 = 低 = 收)
- streak:連續第幾根漲停
- vol_ratio:當天成交量 ÷ 前 20 個交易日的平均量
- prior60:前一天收盤 ÷ 61 個交易日前收盤 − 1(用還原前的價格;除權息會讓它偏低,
  但三分位比的是相對位置)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.market import limit_up


#: 浮點誤差容忍(價格都在交易所檔位上)
EPS = 1e-6
#: 量比的回看天數、位置的回看天數
VOL_DAYS = 20
PRIOR_DAYS = 60
#: 先用寬鬆的漲幅過濾,再用檔位精算
ROUGH = 1.09


def _one_stock(
    code: str, g: pd.DataFrame, actions: set[tuple[str, pd.Timestamp]]
) -> pd.DataFrame:
    """一檔股票的漲停日。g 依日期排好、索引從 0 開始。"""
    close = g["close"].astype(float)
    prev = close.shift(1)
    rough = (close / prev >= ROUGH).fillna(False)
    cap = pd.Series(
        [limit_up(float(p)) if r else np.nan for p, r in zip(prev, rough, strict=True)],
        index=g.index,
    )
    days = pd.to_datetime(g["day"])
    blocked = pd.Series([(code, d) in actions for d in days], index=g.index)
    hit = rough & (close >= cap - EPS) & ~blocked
    avg = (
        g["volume"]
        .astype(float)
        .shift(1)
        .rolling(VOL_DAYS, min_periods=VOL_DAYS)
        .mean()
    )
    flat = (g["open"] == g["high"]) & (g["high"] == g["low"]) & (g["low"] == g["close"])
    return pd.DataFrame(
        {
            "code": code,
            "day": days,
            "one_price": flat,
            "streak": hit.astype(int).groupby((~hit).cumsum()).cumsum(),
            "vol_ratio": g["volume"].astype(float) / avg,
            "prior60": prev / close.shift(PRIOR_DAYS + 1) - 1,
        }
    )[hit]


def limit_up_events(
    prices: pd.DataFrame, actions: set[tuple[str, pd.Timestamp]]
) -> pd.DataFrame:
    """每一個漲停日一列:code、day、one_price、streak、vol_ratio、prior60。

    prices 要有 day、code、open、high、low、close、volume;actions 是 (代號, 日期) 的除權息集合。
    """
    parts = [
        _one_stock(str(code), g.reset_index(drop=True), actions)
        for code, g in prices.sort_values("day").groupby("code")
    ]
    cols = ["code", "day", "one_price", "streak", "vol_ratio", "prior60"]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)
