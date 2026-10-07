"""處置前的流動性水位(#29、#31、#30)。

原本的 liquidity.py 在拿不到的機器上,這裡照 issue 裡寫下的定義重做:

- 成交金額:成交股數 × 收盤價。prices.csv 沒有成交金額欄,這是近似值 ——
  收盤價不是當天的平均成交價,差距在單日振幅以內。沒成交的日子是 0
- 水位:某一天**之前** 20 個交易日的成交金額中位數(不含當天)
- W1:這一次處置開始日的水位
- W2:**整串第一次**處置開始日的水位。第二次處置的 W1 窗口有一半落在第一次
  處置期間,量到的是被壓縮過的流動性(#31),W2 才是真正處置前的
- 整串:同一檔,這次公告「含當天往前 30 個營業日」內有上一次公告,就是同一串
  (#16:換成交易日位置是差 ≤ 29;嚴格夾在中間的營業日 ≤ 28 是唯一的誤判極小值)。
  nth = 0 的督導會報決議不算一次
"""

from __future__ import annotations

import statistics

import pandas as pd


#: 水位往前看幾個交易日
LOOKBACK = 20
#: 這次公告往前、含當天 30 個營業日 = 交易日位置差 ≤ 29(#16)
CHAIN_GAP = 29


def daily_value(prices: pd.DataFrame) -> pd.DataFrame:
    """交易日 × 代號 的成交金額(元)。沒成交(股數空白)是 0。"""
    value = prices.close.astype(float) * prices.volume.astype(float).fillna(0.0)
    wide = prices.assign(value=value.fillna(0.0)).pivot_table(
        index="day", columns="code", values="value", aggfunc="sum"
    )
    wide.columns = wide.columns.astype(str)
    return wide.sort_index()


def level(
    value: pd.DataFrame, code: str, day: pd.Timestamp, lookback: int = LOOKBACK
) -> float | None:
    """Day 之前 lookback 個交易日的成交金額中位數。前面不滿 lookback 天就算不出來。

    這段期間還沒上市的日子(整欄是空的)不算數,不能當成 0 拉低中位數。
    """
    if code not in value.columns:
        return None
    before = value.index[value.index < day][-lookback:]
    if len(before) < lookback:
        return None
    window = value.loc[before, code]
    if window.isna().any():
        return None
    return float(statistics.median(window.tolist()))


def chain_starts(punishes: pd.DataFrame, days: pd.DatetimeIndex) -> pd.Series:
    """每一列處置所屬那一串的第一次處置開始日,順序跟 punishes 一樣。

    punishes 要有 code、announced、start、nth。nth = 0 的列自成一串、也不接別人。
    """
    pos = pd.Series(
        days.searchsorted(pd.to_datetime(punishes.announced)), index=punishes.index
    )
    start = pd.to_datetime(punishes.start)
    out = start.copy()
    counted = punishes.index[punishes.nth > 0]
    order = sorted(
        counted, key=lambda i: (str(punishes.at[i, "code"]), pos[i], start[i])
    )
    head: dict[str, tuple[int, pd.Timestamp]] = {}
    for i in order:
        code = str(punishes.at[i, "code"])
        last = head.get(code)
        first = start[i] if last is None or pos[i] - last[0] > CHAIN_GAP else last[1]
        out[i] = first
        head[code] = (int(pos[i]), first)
    return out


#: 一百萬元。門檻和報表都用百萬元
MILLION = 1_000_000


def chain_levels(
    punishes: pd.DataFrame, prices: pd.DataFrame, days: pd.DatetimeIndex
) -> pd.DataFrame:
    """每一筆處置的 W1、W2(百萬元),索引跟 punishes 一樣。算不出來是 NaN。"""
    value = daily_value(prices)
    heads = chain_starts(punishes, days)
    w1 = [
        level(value, str(code), pd.Timestamp(start))
        for code, start in zip(punishes.code, punishes.start, strict=True)
    ]
    w2 = [
        level(value, str(code), pd.Timestamp(head))
        for code, head in zip(punishes.code, heads, strict=True)
    ]
    return (
        pd.DataFrame(
            {"w1": pd.Series(w1, dtype=float), "w2": pd.Series(w2, dtype=float)}
        ).set_axis(punishes.index)
        / MILLION
    )
