"""處置股出關後的報酬統計。

進場假設:出關後第一個交易日「開盤買進」。這是最保守的假設 ——
處置期間不能當沖、盤中只有集合競價,散戶實際上很難拿到比開盤更好的價格。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


#: 新制上路日:處置改 5 個營業日、撮合改約 2 分鐘
NEW_RULES_FROM = date(2026, 8, 10)


def as_number(value: Any) -> float | None:
    """Pandas 查值回傳的型別很鬆,轉數字的動作集中在這裡處理。"""
    if value is None or pd.isna(value):
        return None
    return float(value)


def trading_days(prices: pd.DataFrame) -> pd.DatetimeIndex:
    """資料裡出現過的所有交易日,由早到晚。"""
    return pd.DatetimeIndex(sorted(prices["day"].unique()))


def next_trading_day(
    days: pd.DatetimeIndex, after: pd.Timestamp
) -> pd.Timestamp | None:
    """第一個「嚴格晚於」after 的交易日。找不到回 None。"""
    later = days[days > after]
    if not len(later):
        return None
    return later[0]


def shift_trading_day(
    days: pd.DatetimeIndex, day: pd.Timestamp, steps: int
) -> pd.Timestamp | None:
    """從 day 往後數 steps 個交易日。超出範圍回 None。"""
    where = int(days.searchsorted(day))
    target = where + steps
    if target >= len(days) or where >= len(days):
        return None
    return days[target]


def build_panels(prices: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """轉成 日期 × 股票代號 的寬表,查價才快。"""
    return {
        field: prices.pivot_table(index="day", columns="code", values=field)
        for field in ("open", "close")
    }


def exit_returns(
    punishes: pd.DataFrame,
    prices: pd.DataFrame,
    horizons: tuple[int, ...] = (0, 1, 3, 5, 10),
) -> pd.DataFrame:
    """每一次處置出關後,持有 N 個交易日的報酬率(%)。

    第 0 天 = 出關日當天開盤買、收盤賣。
    """
    days = trading_days(prices)
    panels = build_panels(prices)
    open_px, close_px = panels["open"], panels["close"]

    records: list[dict[str, object]] = []
    # itertuples 的型別太鬆,改用 dict 逐列取值,順便把型別轉明確
    for raw in punishes.to_dict("records"):
        code = raw["code"]
        end_day = pd.Timestamp(str(raw["end"]))
        release = next_trading_day(days, end_day)
        if release is None or code not in open_px.columns:
            continue
        if release not in open_px.index:
            continue
        entry = as_number(open_px.at[release, code])
        if entry is None or entry <= 0:
            continue

        record: dict[str, object] = {
            "code": code,
            "name": str(raw["name"]),
            "nth": int(raw["nth"]),
            "measure": str(raw["measure"]),
            "start": raw["start"],
            "end": raw["end"],
            "release": release.date(),
            "entry": entry,
            "new_rules": pd.Timestamp(str(raw["start"])).date() >= NEW_RULES_FROM,
        }
        for horizon in horizons:
            target = shift_trading_day(days, release, horizon)
            value: float | None = None
            if target is not None and target in close_px.index:
                out = as_number(close_px.at[target, code])
                if out is not None:
                    value = round((out / entry - 1) * 100, 2)
            record[f"r{horizon}"] = value
        records.append(record)

    return pd.DataFrame(records)


def summarise(returns: pd.DataFrame, column: str) -> dict[str, float]:
    """一組報酬的重點數字。中位數比平均重要 —— 少數暴漲會把平均拉歪。"""
    series = returns[column].dropna()
    if series.empty:
        return {}
    return {
        "樣本數": len(series),
        "中位數%": round(float(series.median()), 2),
        "平均%": round(float(series.mean()), 2),
        "勝率%": round(float((series > 0).mean() * 100), 1),
        "最差%": round(float(series.min()), 1),
        "最好%": round(float(series.max()), 1),
    }
