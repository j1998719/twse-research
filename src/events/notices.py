"""注意股階段的事件(#3,事前登記見 issue)。

處置的門檻是「連續 3 個營業日」或「最近若干營業日內 N 次」被列注意,所以第 3 次
注意代表已經走在被處置的路上。這裡在**被處置之前**就找出這個時點:

每天收盤後數這一檔**最近 5 個交易日(含當天)**被列注意幾次(同一天多則只算一次),
剛好達到 3 的那天就是事件。只用當天以前公布的公告 —— 不准用「後來有沒有被處置」來
篩,那是偷看未來。不用 API 的「累計次數」欄,那個值會隨查詢區間改變(#16)。
同一檔 60 個交易日內只算第一次(events.chips.first_only)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from src.events.chips import first_only


if TYPE_CHECKING:
    from src.events.chips import Hit

#: 回看幾個交易日、第幾次
WINDOW = 5
NTH = 3


def third_notice(notices: pd.DataFrame, days: pd.DatetimeIndex) -> list[Hit]:
    """注意次數(最近 WINDOW 個交易日)剛好達到 NTH 的那一天。notices 要有 code、day。"""
    flags = (
        notices.assign(day=pd.to_datetime(notices.day), hit=1)
        .drop_duplicates(["code", "day"])
        .pivot_table(index="day", columns="code", values="hit", aggfunc="max")
        .reindex(days)
        .fillna(0)
    )
    count = flags.rolling(WINDOW, min_periods=1).sum()
    reached = (count >= NTH) & (count.shift(1, fill_value=0) < NTH)
    rows, cols = reached.to_numpy().nonzero()
    names = [str(c) for c in flags.columns]
    return first_only(
        [(names[int(c)], days[int(r)]) for r, c in zip(rows, cols, strict=True)], days
    )
