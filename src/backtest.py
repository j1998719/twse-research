"""處置股出關後的報酬統計。

進場假設:出關後第一個交易日「開盤買進」。這是最保守的假設 ——
處置期間不能當沖、盤中只有集合競價,散戶實際上很難拿到比開盤更好的價格。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from src.market import ROUND_TRIP_COST_PCT, limit_up


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
    """從 day 數 steps 個交易日;steps 為負就往前數。超出範圍回 None。

    下界的檢查不能省 —— Python 的負索引會從尾端取值,
    少了這一行,「往前數太多天」會安靜地回傳資料最後面的某一天。
    """
    where = int(days.searchsorted(day))
    target = where + steps
    if target < 0 or target >= len(days) or where >= len(days):
        return None
    return days[target]


def build_panels(prices: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """轉成 日期 × 股票代號 的寬表,查價才快。"""
    return {
        field: prices.pivot_table(index="day", columns="code", values=field)
        for field in ("open", "high", "low", "close")
    }


def opened_limit_up(
    open_px: float, low: float | None, prev_close: float | None
) -> bool:
    """一開盤就鎖漲停 —— 這種情況散戶通常買不到。

    條件是開盤價已達漲停,而且盤中沒有跌回漲停之下(low 也在漲停價)。
    """
    if prev_close is None or prev_close <= 0:
        return False
    cap = limit_up(prev_close)
    return open_px >= cap - 1e-9 and (low is None or low >= cap - 1e-9)


def _index_return(
    index: dict[date, float], start: pd.Timestamp, end: pd.Timestamp
) -> float | None:
    """大盤同期報酬(%)。進場是開盤,所以基準起點用前一個交易日的收盤。"""
    a = index.get(start.date())
    b = index.get(end.date())
    if a is None or b is None or a <= 0:
        return None
    return (b / a - 1) * 100


@dataclass(frozen=True)
class PriceView:
    """查價要用的東西。包成一包,函式的參數才不會長到看不懂。"""

    days: pd.DatetimeIndex
    close: pd.DataFrame
    index: dict[date, float]


def _horizon_row(
    view: PriceView,
    code: object,
    release: pd.Timestamp,
    base: pd.Timestamp,
    entry: float,
    horizon: int,
) -> dict[str, float | None]:
    """某個持有天數的毛報酬、扣成本後、以及扣掉大盤之後的超額。"""
    target = shift_trading_day(view.days, release, horizon)
    if target is None or target not in view.close.index:
        return {f"g{horizon}": None, f"n{horizon}": None, f"x{horizon}": None}
    out = as_number(view.close.at[target, code])
    if out is None:
        return {f"g{horizon}": None, f"n{horizon}": None, f"x{horizon}": None}

    gross = (out / entry - 1) * 100
    net = gross - ROUND_TRIP_COST_PCT
    market = _index_return(view.index, base, target)
    return {
        f"g{horizon}": round(gross, 2),
        f"n{horizon}": round(net, 2),
        f"x{horizon}": None if market is None else round(net - market, 2),
    }


def exit_returns(
    punishes: pd.DataFrame,
    prices: pd.DataFrame,
    index: dict[date, float] | None = None,
    horizons: tuple[int, ...] = (0, 1, 3, 5, 10),
) -> pd.DataFrame:
    """每一次處置出關後,持有 N 個交易日的報酬率(%)。

    第 0 天 = 出關日當天開盤買、收盤賣。三種報酬:
    g = 毛報酬、n = 扣掉來回交易成本、x = 再扣掉大盤同期漲跌(超額報酬)。
    """
    index = index or {}
    days = trading_days(prices)
    panels = build_panels(prices)
    open_px, low_px, close_px = panels["open"], panels["low"], panels["close"]
    view = PriceView(days=days, close=close_px, index=index)

    records: list[dict[str, object]] = []
    for raw in punishes.to_dict("records"):
        code = raw["code"]
        release = next_trading_day(days, pd.Timestamp(str(raw["end"])))
        if release is None or code not in open_px.columns:
            continue
        if release not in open_px.index:
            continue
        entry = as_number(open_px.at[release, code])
        if entry is None or entry <= 0:
            continue

        # 出關前一個交易日的收盤,用來算漲停價和大盤基準
        base = shift_trading_day(days, release, -1)
        prev_close = (
            as_number(close_px.at[base, code])
            if base is not None and base in close_px.index
            else None
        )
        locked = opened_limit_up(entry, as_number(low_px.at[release, code]), prev_close)

        record: dict[str, object] = {
            "code": code,
            "name": str(raw["name"]),
            "nth": int(raw["nth"]),
            "measure": str(raw["measure"]),
            "start": raw["start"],
            "end": raw["end"],
            "release": release.date(),
            "entry": entry,
            "prev_close": prev_close,
            # 一開盤就鎖漲停,散戶買不到 —— 這種樣本要排除,不然會高估報酬
            "locked_up": locked,
            "new_rules": pd.Timestamp(str(raw["start"])).date() >= NEW_RULES_FROM,
        }
        for horizon in horizons:
            record.update(
                _horizon_row(
                    view,
                    code,
                    release,
                    base if base is not None else release,
                    entry,
                    horizon,
                )
            )
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


def flag_exrights(
    returns: pd.DataFrame,
    prices: pd.DataFrame,
    exrights: set[tuple[date, str]],
    horizon: int = 10,
) -> pd.Series:
    """持有期間內有沒有遇到除權息。

    我們存的是未還原股價,除權息當天價格會斷崖式下跌 ——
    那不是真的跌。這種樣本算出來的報酬是假的,要標出來排除。
    """
    days = trading_days(prices)
    flags: list[bool] = []
    for raw in returns.to_dict("records"):
        release = pd.Timestamp(str(raw["release"]))
        where = int(days.searchsorted(release))
        window = days[where : where + horizon + 1]
        code = str(raw["code"])
        flags.append(any((d.date(), code) in exrights for d in window))
    return pd.Series(flags, index=returns.index)


def hold_through(
    punishes: pd.DataFrame,
    prices: pd.DataFrame,
    index: dict[date, float] | None = None,
    horizons: tuple[int, ...] = (0, 1, 3, 5),
) -> pd.DataFrame:
    """處置期間買進,出關後賣出。

    進場是處置首日開盤 —— 關禁閉期間仍然可以交易,只是改成集合競價。
    出場分兩段:出關日收盤(horizon 0),以及再多抱 N 個交易日。
    賭的是流動性被人為壓縮時價格偏低,恢復之後回彈。
    """
    index = index or {}
    days = trading_days(prices)
    panels = build_panels(prices)
    open_px, low_px, close_px = panels["open"], panels["low"], panels["close"]
    view = PriceView(days=days, close=close_px, index=index)

    records: list[dict[str, object]] = []
    for raw in punishes.to_dict("records"):
        code = raw["code"]
        begin = _first_trading_day(days, pd.Timestamp(str(raw["start"])))
        release = next_trading_day(days, pd.Timestamp(str(raw["end"])))
        if begin is None or release is None or code not in open_px.columns:
            continue
        entry = as_number(open_px.at[begin, code])
        if entry is None or entry <= 0:
            continue

        before = shift_trading_day(days, begin, -1)
        prev_close = (
            as_number(close_px.at[before, code])
            if before is not None and before in close_px.index
            else None
        )
        record: dict[str, object] = {
            "code": code,
            "name": str(raw["name"]),
            "nth": int(raw["nth"]),
            "start": raw["start"],
            "end": raw["end"],
            "begin": begin.date(),
            "release": release.date(),
            "entry": entry,
            "locked_up": opened_limit_up(
                entry, as_number(low_px.at[begin, code]), prev_close
            ),
            "new_rules": pd.Timestamp(str(raw["start"])).date() >= NEW_RULES_FROM,
        }
        base = before if before is not None else begin
        for horizon in horizons:
            record.update(_horizon_row(view, code, release, base, entry, horizon))
        records.append(record)

    return pd.DataFrame(records)


def _first_trading_day(
    days: pd.DatetimeIndex, on_or_after: pd.Timestamp
) -> pd.Timestamp | None:
    """當天就是交易日就用當天,否則往後找。"""
    later = days[days >= on_or_after]
    return later[0] if len(later) else None


#: 出關前的預期性漲勢:進場日與出場日,都是相對於出關日的交易日偏移
PRE_RELEASE_ENTRY = -6
PRE_RELEASE_EXIT = -1


def pre_release_run(
    punishes: pd.DataFrame,
    prices: pd.DataFrame,
    index: dict[date, float] | None = None,
    entry: int = PRE_RELEASE_ENTRY,
    exit_: int = PRE_RELEASE_EXIT,
) -> pd.DataFrame:
    """處置後半段買進,出關前一日賣出。

    以出關日為原點(t=0)對齊,而不是以公告日 —— 處置長度有 5 日也有 10 日,
    用公告日對齊會把兩種混在一起。對齊之後看得出漲勢在 t-1 見頂,
    出關當天就回跌,所以出場要在出關前一日的收盤。
    """
    index = index or {}
    days = trading_days(prices)
    panels = build_panels(prices)
    close_px = panels["close"]

    records: list[dict[str, object]] = []
    for raw in punishes.to_dict("records"):
        code = raw["code"]
        release = next_trading_day(days, pd.Timestamp(str(raw["end"])))
        if release is None or code not in close_px.columns:
            continue
        buy_day = shift_trading_day(days, release, entry)
        sell_day = shift_trading_day(days, release, exit_)
        if buy_day is None or sell_day is None:
            continue
        if buy_day not in close_px.index or sell_day not in close_px.index:
            continue
        buy = as_number(close_px.at[buy_day, code])
        sell = as_number(close_px.at[sell_day, code])
        if buy is None or sell is None or buy <= 0:
            continue

        gross = (sell / buy - 1) * 100
        net = gross - ROUND_TRIP_COST_PCT
        market = _index_return(index, buy_day, sell_day)
        records.append(
            {
                "code": code,
                "name": str(raw["name"]),
                "nth": int(raw["nth"]),
                "start": raw["start"],
                "end": raw["end"],
                "buy_day": buy_day.date(),
                "sell_day": sell_day.date(),
                "release": release.date(),
                "buy": buy,
                "sell": sell,
                "gross": round(gross, 2),
                "net": round(net, 2),
                "excess": None if market is None else round(net - market, 2),
                "new_rules": pd.Timestamp(str(raw["start"])).date() >= NEW_RULES_FROM,
            }
        )
    return pd.DataFrame(records)
