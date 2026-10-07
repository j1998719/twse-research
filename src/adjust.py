"""還原股價與長期均線。

十年線這麼長的期間,原始收盤價幾乎一定失真:十年裡配了十次息的股票,
每次除息價格就往下跳一次,用原始價算的均線會讓它「看起來」跌破;減資或
變更面額更是直接讓價格跳好幾倍。所以均線一律用還原股價算
(Jordan 2026-10-06 選的)。

還原用的是**向後還原**:最新一天的價格不動,每遇到一次除權息(或減資、
變更面額),就把那一天**之前**的所有價格乘上

    因子 = 參考價 / 前一日收盤價

多次事件的因子相乘。好處是最新收盤價就是實際成交價,拿它跟均線比不用再換算。

事件從哪裡來(證交所、櫃買中心的除權息、減資、變更面額)由抓取那一層負責,
這裡只吃「代號、日期、因子」。

均線用交易日數算,照台股的習慣「年線 = 240 日」:五年線 1,200 日、
十年線 2,400 日。歷史不夠長的股票不算,回 None —— 上市才三年的股票
沒有十年線,不能拿三年的平均冒充。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd


if TYPE_CHECKING:
    from collections.abc import Sequence

#: 台股習慣的「年線」是 240 個交易日
YEAR_DAYS = 240
#: 五年線、十年線
WINDOWS = {"ma5y": 5 * YEAR_DAYS, "ma10y": 10 * YEAR_DAYS}


def adjusted_closes(prices: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """把收盤價向後還原。

    prices:code、day、close(一檔一天一列)
    events:code、day、factor —— day 是除權息(或減資等)交易日,
    factor = 參考價 / 前一日收盤,所以 day 之前的價格要乘上它。

    回傳 prices 加上 adj_close 欄。沒有事件的股票 adj_close 就等於 close。
    """
    out = prices.sort_values(["code", "day"]).reset_index(drop=True)
    out["adj_close"] = out["close"].astype(float)
    if events.empty:
        return out
    # 每個事件之後(含)所有事件的因子連乘:某一天的價格要乘的,就是它之後
    # 第一個事件的這個值。用 merge_asof 一次對齊,不要逐檔逐事件掃全表
    # 同一檔同一天有兩個事件(例如除息和減資同一天恢復交易)時先乘起來:
    # merge_asof 遇到同一天只會對到其中一筆,另一個因子會安靜地不見
    evs = (
        events.assign(factor=events["factor"].astype(float))
        .groupby(["code", "day"], as_index=False)
        .agg(factor=("factor", "prod"))
        .sort_values(["code", "day"], ascending=[True, False])
    )
    evs["multiplier"] = evs.groupby("code")["factor"].cumprod()
    aligned = pd.merge_asof(
        out[["day", "code"]].reset_index().sort_values("day"),
        evs[["day", "code", "multiplier"]].sort_values("day"),
        on="day",
        by="code",
        direction="forward",
        # 除權息當天的價格已經是除權息後的,不用還原
        allow_exact_matches=False,
    ).set_index("index")
    out["adj_close"] *= aligned["multiplier"].reindex(out.index).fillna(1.0)
    return out


@dataclass(frozen=True)
class LongTerm:
    """一檔股票最後一天的收盤,以及跟長期均線的距離。"""

    day: str
    close: float
    ma5y: float | None
    ma10y: float | None

    def gap(self, ma: float | None) -> float | None:
        """收盤價比均線高或低幾 %。負的就是跌破。"""
        if ma is None or ma == 0:
            return None
        return round((self.close / ma - 1) * 100, 2)


def long_term(
    adjusted: pd.DataFrame, windows: Sequence[int] | None = None
) -> dict[str, LongTerm]:
    """每一檔最後一天的收盤與五年線、十年線。

    只用有收盤價的日子算(停牌沒成交的那天不算一個交易日)。
    歷史不滿窗口長度的那條線回 None。
    """
    five, ten = windows or (WINDOWS["ma5y"], WINDOWS["ma10y"])
    out: dict[str, LongTerm] = {}
    if adjusted.empty:
        return out
    usable = adjusted.dropna(subset=["adj_close"]).sort_values(["code", "day"])
    for code, rows in usable.groupby("code"):
        series = rows["adj_close"]
        last = rows.iloc[-1]

        def mean_of(window: int, values: pd.Series = series) -> float | None:
            if len(values) < window:
                return None
            return float(values.iloc[-window:].mean())

        out[str(code)] = LongTerm(
            day=pd.Timestamp(last["day"]).date().isoformat(),
            close=float(last["close"]),
            ma5y=mean_of(five),
            ma10y=mean_of(ten),
        )
    return out
