"""分市況、分制度期間檢驗同一個策略。

同一套規則在多頭有效、在空頭失效,那它就是動能策略的變形,不是制度套利。
所以結論不能只看整段期間的平均,要一段一段分開驗。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class Period:
    """一個市況或制度期間。"""

    name: str
    start: date
    end: date
    note: str = ""


#: 台股改逐筆交易。在那之前盤中是每 5 秒集合競價一次,
#: 跟處置期間的集合競價差別很小 —— 「處置壓縮流動性」這個前提在那之前並不成立
CONTINUOUS_TRADING_FROM = date(2020, 3, 23)

#: 盤中零股交易上路,小額資金才進得來
ODD_LOT_INTRADAY_FROM = date(2020, 10, 26)

#: 處置新制:10 個營業日縮為 5 個,撮合 20 分鐘改約 2 分鐘
NEW_DISPOSITION_RULES_FROM = date(2026, 8, 10)


#: 依加權指數的走勢切段。日期取大波段的轉折,不求精確到日
MARKET_REGIMES: list[Period] = [
    Period("2020 疫情崩跌與反彈", date(2020, 1, 1), date(2020, 12, 31), "V 型反轉"),
    Period("2021 多頭", date(2021, 1, 1), date(2021, 12, 31), ""),
    Period("2022 空頭", date(2022, 1, 1), date(2022, 12, 31), "加權指數全年下跌約兩成"),
    Period("2023 復甦", date(2023, 1, 1), date(2023, 12, 31), ""),
    Period("2024 多頭", date(2024, 1, 1), date(2024, 12, 31), ""),
    Period("2025 多頭", date(2025, 1, 1), date(2025, 12, 31), ""),
    Period("2026 多頭", date(2026, 1, 1), date(2026, 12, 31), "處置件數暴增"),
]


def slice_by(
    events: pd.DataFrame, period: Period, column: str = "buy_day"
) -> pd.DataFrame:
    """取出落在這個期間內的事件。頭尾那天都算在內。"""
    days = pd.to_datetime(events[column]).dt.date
    return events[(days >= period.start) & (days <= period.end)]


def microstructure_era(day: date) -> str:
    """這一天屬於哪個市場微結構時期。

    這會影響「處置期間流動性被壓縮」這個前提成不成立。
    """
    if day < CONTINUOUS_TRADING_FROM:
        return "集合競價時代"
    if day >= NEW_DISPOSITION_RULES_FROM:
        return "處置新制"
    return "逐筆交易"
