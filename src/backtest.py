"""處置股出關後的報酬統計。

進場假設:出關後第一個交易日「開盤買進」。這是最保守的假設 ——
處置期間不能當沖、盤中只有集合競價,散戶實際上很難拿到比開盤更好的價格。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from src.market import ROUND_TRIP_COST_PCT, limit_down, limit_up


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
    """一組報酬的關鍵統計量。

    中位數比平均重要 —— 這類資料少數幾筆暴漲會把平均拉歪,
    兩者差很多本身就是訊息(分布偏斜)。四分位距則看得出中間六成落在哪。
    """
    series = returns[column].dropna()
    if series.empty:
        return {}
    return {
        "樣本數": len(series),
        "最小%": round(float(series.min()), 2),
        "四分之一%": round(float(series.quantile(0.25)), 2),
        "中位數%": round(float(series.median()), 2),
        "平均%": round(float(series.mean()), 2),
        "四分之三%": round(float(series.quantile(0.75)), 2),
        "最大%": round(float(series.max()), 2),
        "標準差%": round(float(series.std()), 2),
        "勝率%": round(float((series > 0).mean() * 100), 1),
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


@dataclass(frozen=True)
class Timing:
    """什麼時候進出、用哪個價格。

    兩邊都用開盤是最保守的假設 —— 幅度大約是收盤進出的一半,方向仍然成立。
    """

    #: 相對出關日的交易日偏移,負數是出關之前
    entry: int = PRE_RELEASE_ENTRY
    exit: int = PRE_RELEASE_EXIT
    #: "close" 或 "open"
    entry_price: str = "close"
    exit_price: str = "close"
    #: 買進那天的價格在漲停就順延到隔一個交易日,賣出那天在跌停也順延
    #: (Jordan 2026-10-07:漲停買不到、跌停賣不掉)。歷史上釘住的數字
    #: 是不順延算的,重現它們的測試要關掉這個
    defer_limits: bool = True


def _locked_days(
    punishes: pd.DataFrame,
) -> dict[object, list[tuple[pd.Timestamp, pd.Timestamp]]]:
    """每一檔的所有處置期間。用來判斷某一天是不是真的自由了。"""
    spans: dict[object, list[tuple[pd.Timestamp, pd.Timestamp]]] = {}
    for raw in punishes.to_dict("records"):
        spans.setdefault(raw["code"], []).append(
            (pd.Timestamp(str(raw["start"])), pd.Timestamp(str(raw["end"])))
        )
    return spans


#: 浮點誤差的容忍度。價格和漲跌停價都是交易所檔位上的數字
_LIMIT_EPS = 1e-6


def _pos(days: pd.DatetimeIndex, day: pd.Timestamp) -> int:
    """Day 在交易日序列裡的位置。day 一定是交易日。"""
    return int(days.searchsorted(day))


@dataclass(frozen=True)
class Book:
    """判斷某天成交得了成交不了要用的價格:成交價那一張表,以及收盤(算漲跌停)。"""

    days: pd.DatetimeIndex
    px: pd.DataFrame
    close: pd.DataFrame


def tradable_from(
    book: Book,
    code: object,
    start: pd.Timestamp,
    until: pd.Timestamp | None,
    *,
    buying: bool,
) -> pd.Timestamp | None:
    """從 start(含)往後,第一個買得到(或賣得掉)的交易日。

    買進:那天的成交價在漲停就當成買不到;賣出:在跌停就當成賣不掉。
    沒有價格(停牌)也一樣成交不了。漲跌停價用前一個交易日的收盤算 ——
    除權息當天的漲跌停是以參考價計算的,這裡會有誤差,但那天剛好落在
    進出場日、又剛好碰到漲跌停的機率很低。

    超過 until(不含)還成交不了就回 None。until 是 None 代表一路找到資料結束。
    """
    days = book.days
    for i in range(_pos(days, start), len(days)):
        day = days[i]
        if until is not None and day >= until:
            return None
        price = as_number(book.px.at[day, code])
        prev = as_number(book.close.at[days[i - 1], code]) if i > 0 else None
        if price is None:
            continue
        if prev is None or prev <= 0:
            return day
        if buying and price >= limit_up(prev) - _LIMIT_EPS:
            continue
        if not buying and price <= limit_down(prev) + _LIMIT_EPS:
            continue
        return day
    return None


#: pre_release_run 每一列的欄位
RUN_COLUMNS = [
    "code",
    "name",
    "nth",
    "start",
    "end",
    "announced",
    "knowable",
    "truly_released",
    "buy_day",
    "sell_day",
    "buy_deferred",
    "sell_deferred",
    "release",
    "buy",
    "sell",
    "gross",
    "net",
    "excess",
    "new_rules",
]


def pre_release_run(
    punishes: pd.DataFrame,
    prices: pd.DataFrame,
    index: dict[date, float] | None = None,
    timing: Timing | None = None,
    all_punishes: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """處置後半段買進,出關前一日賣出。

    以出關日為原點(t=0)對齊,而不是以公告日 —— 處置長度有 5 日也有 10 日,
    用公告日對齊會把兩種混在一起。對齊之後看得出漲勢在 t-1 見頂,
    出關當天就回跌,所以出場要在出關前一日。

    """
    index = index or {}
    timing = timing or Timing()
    # 兩次處置常常重疊。用全部的處置期間判斷「出關日」那天是不是真的自由了,
    # 而不是只看這一筆公告自己的結束日。
    spans = _locked_days(all_punishes if all_punishes is not None else punishes)
    days = trading_days(prices)
    panels = build_panels(prices)
    close_px = panels["close"]
    buy_px = panels[timing.entry_price]
    sell_px = panels[timing.exit_price]

    records: list[dict[str, object]] = []
    #: 順延到最後還是成交不了的筆數(買進順延到賣出日、或賣出順延到資料結束)
    unfilled = 0
    for raw in punishes.to_dict("records"):
        code = raw["code"]
        release = next_trading_day(days, pd.Timestamp(str(raw["end"])))
        if release is None or code not in close_px.columns:
            continue
        buy_day = shift_trading_day(days, release, timing.entry)
        sell_day = shift_trading_day(days, release, timing.exit)
        if buy_day is None or sell_day is None:
            continue
        if buy_day not in close_px.index or sell_day not in close_px.index:
            continue
        planned_buy, planned_sell = buy_day, sell_day
        if timing.defer_limits:
            # 先找賣出日,再找買進日 —— 買進最晚只能順延到原定賣出日的前一天
            sell_found = tradable_from(
                Book(days, sell_px, close_px), code, sell_day, None, buying=False
            )
            buy_found = tradable_from(
                Book(days, buy_px, close_px), code, buy_day, sell_day, buying=True
            )
            if sell_found is None or buy_found is None:
                unfilled += 1
                continue
            buy_day, sell_day = buy_found, sell_found
        buy = as_number(buy_px.at[buy_day, code])
        sell = as_number(sell_px.at[sell_day, code])
        if buy is None or sell is None or buy <= 0:
            continue

        gross = (sell / buy - 1) * 100
        net = gross - ROUND_TRIP_COST_PCT
        market = _index_return(index, buy_day, sell_day)
        # 處置公告是盤後發布的。在公告日當天(或更早)的收盤買進,
        # 等於在公告還沒出來時就知道它會被處置 —— 那是用到未來資訊。
        announced = (
            pd.Timestamp(str(raw["announced"])) if raw.get("announced") else None
        )
        records.append(
            {
                "code": code,
                "name": str(raw["name"]),
                "nth": int(raw["nth"]),
                "start": raw["start"],
                "end": raw["end"],
                "announced": None if announced is None else announced.date(),
                #: 進場時公告已經發布了嗎。False 代表這筆用到了未來資訊
                # 用**原定**的買進日判斷,不是順延之後的:會在 t−6 出手,
                # 前提是那時候已經知道處置的時程。漲停順延幾天剛好跨過
                # 公告日,不能讓一筆原本用到未來資訊的樣本變合法
                "knowable": announced is None or planned_buy > announced,
                # 出關日那天是不是真的自由了。兩次處置常常重疊,
                # False 代表它還在另一段處置裡,是假出關
                "truly_released": not any(
                    a <= release <= b for a, b in spans.get(code, [])
                ),
                "buy_day": buy_day.date(),
                "sell_day": sell_day.date(),
                #: 因為漲停 / 跌停順延了幾個交易日。0 代表照原定日期成交
                "buy_deferred": _pos(days, buy_day) - _pos(days, planned_buy),
                "sell_deferred": _pos(days, sell_day) - _pos(days, planned_sell),
                "release": release.date(),
                "buy": buy,
                "sell": sell,
                "gross": round(gross, 2),
                "net": round(net, 2),
                "excess": None if market is None else round(net - market, 2),
                "new_rules": pd.Timestamp(str(raw["start"])).date() >= NEW_RULES_FROM,
            }
        )
    # 全部都成交不了時 records 是空的;沒有欄位的話呼叫端一取 .knowable 就壞
    out = pd.DataFrame(records, columns=RUN_COLUMNS)
    out.attrs["unfilled"] = unfilled
    return out


#: 一個月平均幾天
DAYS_PER_MONTH = 30.44
DAYS_PER_YEAR = 365.25


def event_rate(events: pd.DataFrame, column: str = "buy_day") -> dict[str, float]:
    """事件發生的頻率。

    報酬率再好,一年只出現三次也吃不飽;反過來一個月三十次就要煩惱資金夠不夠。
    所以頻率跟報酬一樣是決策依據,不是附註。
    """
    if events.empty:
        return {}
    days = pd.to_datetime(events[column])
    span = (days.max() - days.min()).days + 1
    per_month = days.dt.to_period("M").value_counts()
    return {
        "總件數": len(days),
        "涵蓋天數": span,
        "每月平均": round(len(days) / (span / DAYS_PER_MONTH), 1),
        "每年平均": round(len(days) / (span / DAYS_PER_YEAR), 1),
        "最忙的月份": int(per_month.max()),
        "最閒的月份": int(per_month.min()),
        "有事件的月份數": len(per_month),
    }


def win_loss(returns: pd.DataFrame, column: str) -> dict[str, float]:
    """把賺的和賠的拆開看。

    勝率高不等於賺錢。57%% 的勝率配上「賺的時候小賺、賠的時候大賠」
    一樣是虧的,所以賺賠的幅度要跟勝率一起看。
    最後的期望值就是這三個數字的組合。
    """
    series = returns[column].dropna()
    if series.empty:
        return {}
    wins = series[series > 0]
    losses = series[series < 0]
    win_rate = len(wins) / len(series)
    out: dict[str, float] = {
        "全部_樣本": len(series),
        "全部_平均%": round(float(series.mean()), 2),
        "全部_中位數%": round(float(series.median()), 2),
        "賺_筆數": len(wins),
        "賠_筆數": len(losses),
        "勝率%": round(win_rate * 100, 1),
    }
    if len(wins):
        out["賺_平均%"] = round(float(wins.mean()), 2)
        out["賺_中位數%"] = round(float(wins.median()), 2)
        out["賺_最大%"] = round(float(wins.max()), 2)
    if len(losses):
        out["賠_平均%"] = round(float(losses.mean()), 2)
        out["賠_中位數%"] = round(float(losses.median()), 2)
        out["賠_最大%"] = round(float(losses.min()), 2)
    if len(wins) and len(losses):
        # 賺賠比:賺的時候的平均 ÷ 賠的時候的平均(取絕對值)
        out["賺賠比"] = round(float(wins.mean() / abs(losses.mean())), 2)
        # 期望值 = 勝率 × 平均賺 − 敗率 × 平均賠
        out["期望值%"] = round(
            win_rate * float(wins.mean()) + (1 - win_rate) * float(losses.mean()), 2
        )
    return out
