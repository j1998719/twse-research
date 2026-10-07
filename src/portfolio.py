"""組合層級的權益曲線:事件研究算不出來的那一半(#33)。

事件研究把每一筆事件對齊在 t=0 再取統計,**時間順序被抹掉了**,所以算不出
最大回檔(MDD)或「多久沒創新高」—— 這兩個都是建立在順序上的。這裡把交易
放回日曆:

- 每天評價:現金 + Σ 持股 × 當天收盤(停牌用最後一個收盤)。只在進出場評價
  等於假設持有期間不會回檔,會系統性低估 MDD
- 部位大小三種 mode(#33,Jordan 2026-10-07:「應該是不同 mode」):
  lot = 每筆 1 張(跟 capital.py 一樣);fixed = 每筆本金的 10%;fraction = 每筆
  前一天收盤淨值的 10%。後兩種取整數股(允許零股)。錢不夠買足就跳過
- 同一天先賣再買:收盤賣掉的錢,當天收盤就能再用 —— 但**全額預收**的股票(第二次
  處置)下單時錢就要在戶頭,賣出的錢 T+2 才交割,所以只能用已交割的現金(#30)
- 來回成本在賣出時一次扣

交易本身(哪天買、哪天賣、成交價)由 disposition_study.pre_release_run 決定,
漲跌停已經順延過。這個模組只負責放回日曆,不決定進出場。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import pandas as pd

from src.market import ROUND_TRIP_COST_PCT


if TYPE_CHECKING:
    from collections.abc import Sequence

#: 一張 = 1000 股
LOT = 1000
#: 賣出的錢幾個交易日後交割(台股 T+2)
SETTLE_DAYS = 2
#: fixed / fraction 每筆佔本金或淨值的比例(#33 事前登記,不掃)
SHARE = 0.10
#: 部位大小的 mode
Sizing = Literal["lot", "fixed", "fraction"]
SIZINGS: tuple[Sizing, ...] = ("lot", "fixed", "fraction")


@dataclass(frozen=True)
class Position:
    """一筆交易。進出場日和成交價都由事件研究決定好了,這裡只拿來放回日曆。"""

    code: str
    buy_day: pd.Timestamp
    sell_day: pd.Timestamp
    buy: float
    sell: float
    #: 賣出時的報酬倍數(賣價 / 還原後買價)。事件研究算好的,已還原除權息(#59)
    ratio: float
    #: 全額預收(第二次處置):只能用已交割的現金買
    prepay: bool = False


@dataclass(frozen=True)
class Portfolio:
    """一個本金下跑出來的結果。"""

    capital: float
    #: 每個交易日收盤的總資產(現金 + 持股市值)
    equity: pd.Series
    #: 已經賣掉的每一筆損益(元,已扣成本),照賣出順序
    pnls: list[float]
    taken: int
    skipped: int
    max_concurrent: int


def _positions(trades: pd.DataFrame) -> dict[pd.Timestamp, list[Position]]:
    """依買進日分組;同一天的照賣出日排,結果才不會因為輸入順序而變。"""
    out: dict[pd.Timestamp, list[Position]] = {}
    for row in trades.to_dict("records"):
        pos = Position(
            code=str(row["code"]),
            buy_day=pd.Timestamp(str(row["buy_day"])),
            sell_day=pd.Timestamp(str(row["sell_day"])),
            buy=float(row["buy"]),
            sell=float(row["sell"]),
            ratio=(
                1 + float(row["gross"]) / 100
                if "gross" in row
                else float(row["sell"]) / float(row["buy"])
            ),
            prepay=bool(row.get("prepay", False)),
        )
        out.setdefault(pos.buy_day, []).append(pos)
    for group in out.values():
        group.sort(key=lambda p: (p.sell_day, p.code))
    return out


def _shares(
    sizing: Sizing, price: float, capital: float, nav: float, lot: int, share: float
) -> int:
    """這筆要買幾股。0 代表連 1 股都買不起。"""
    if sizing == "lot":
        return lot
    budget = capital * share if sizing == "fixed" else nav * share
    return int(budget // price)


def simulate(
    trades: pd.DataFrame,
    closes: pd.DataFrame,
    capital: float,
    lot: int = LOT,
    sizing: Sizing = "lot",
    share: float = SHARE,
) -> Portfolio:
    """照日曆跑一遍。

    trades 要有 code、buy_day、sell_day、buy、sell,有 gross(事件研究的毛報酬 %)
    就用它;closes 是 交易日 × 代號 的收盤寬表(欄名是字串代號)。

    持股市值 = 買進金額 × 當天收盤 / 買進日收盤。closes 給還原收盤的話,
    除息那天淨值不會憑空掉一截(股息算回來),減資也不會憑空漲一截(#59)。
    """
    if sizing not in SIZINGS:
        msg = f"sizing 只能是 {SIZINGS},收到 {sizing!r}"
        raise ValueError(msg)
    marks = closes.sort_index().ffill()
    days = pd.DatetimeIndex(marks.index)
    column = {str(code): i for i, code in enumerate(marks.columns)}
    prices = marks.to_numpy(dtype=float)
    by_buy = _positions(trades)
    keep = 1 - ROUND_TRIP_COST_PCT / 100

    cash = float(capital)
    #: 持有中:(部位, 股數, 買進那天在 days 裡的位置)。市值是相對於那天收盤的漲跌
    held: list[tuple[Position, int, int]] = []
    pnls: list[float] = []
    #: 還沒交割的賣出款:(第幾個交易日到帳, 金額)
    unsettled: list[tuple[int, float]] = []
    taken = skipped = most = 0
    equity: list[float] = []
    for i, day in enumerate(days):
        # 先賣,收盤賣掉的錢當天收盤就能再用
        for item in [h for h in held if h[0].sell_day == day]:
            pos, shares, _ = item
            proceeds = pos.buy * shares * pos.ratio * keep
            cash += proceeds
            unsettled.append((i + SETTLE_DAYS, proceeds))
            pnls.append(proceeds - pos.buy * shares)
            held.remove(item)
        # 再買,錢不夠買足就跳過這個訊號
        nav = equity[-1] if equity else float(capital)
        unsettled = [(at, amount) for at, amount in unsettled if at > i]
        for pos in by_buy.get(day, []):
            shares = _shares(sizing, pos.buy, capital, nav, lot, share)
            usable = cash - sum(a for _, a in unsettled) if pos.prepay else cash
            if shares <= 0 or pos.buy * shares > usable:
                skipped += 1
                continue
            cash -= pos.buy * shares
            held.append((pos, shares, i))
            taken += 1
        most = max(most, len(held))
        value = sum(
            pos.buy
            * shares
            * prices[i, column[pos.code]]
            / prices[at, column[pos.code]]
            for pos, shares, at in held
        )
        equity.append(cash + float(value))

    return Portfolio(
        capital=float(capital),
        equity=pd.Series(equity, index=days, name="equity"),
        pnls=pnls,
        taken=taken,
        skipped=skipped,
        max_concurrent=most,
    )


@dataclass(frozen=True)
class Drawdown:
    """最大回檔:從哪一天的高點、跌到哪一天、哪一天回到那個高點(還沒回來是 None)。"""

    pct: float
    peak: pd.Timestamp
    trough: pd.Timestamp
    recovered: pd.Timestamp | None


def drawdown(equity: pd.Series) -> Drawdown:
    """最大回檔(%,負數)。"""
    days = pd.DatetimeIndex(equity.index)
    values = equity.to_numpy(dtype=float)
    running = pd.Series(values).cummax().to_numpy()
    dd = values / running - 1
    low = int(dd.argmin())
    high = int(values[: low + 1].argmax())
    back = [j for j in range(low, len(values)) if values[j] >= values[high]]
    return Drawdown(
        pct=float(dd[low] * 100),
        peak=days[high],
        trough=days[low],
        recovered=days[back[0]] if back else None,
    )


def underwater_days(equity: pd.Series) -> int:
    """最長多久沒創新高(日曆天):從一個高點到下一次超過它;一直沒超過就算到最後一天。"""
    days = pd.DatetimeIndex(equity.index)
    values = equity.to_numpy(dtype=float)
    longest = 0
    high = float("-inf")
    since = days[0]
    for day, value in zip(days, values, strict=True):
        if value > high:
            longest = max(longest, (day - since).days)
            high, since = float(value), day
    return max(longest, (days[-1] - since).days)


def losing_streak(pnls: Sequence[float]) -> int:
    """照時間順序,最多連續幾筆虧損。剛好 0 不算虧。"""
    longest = run = 0
    for value in pnls:
        run = run + 1 if value < 0 else 0
        longest = max(longest, run)
    return longest
