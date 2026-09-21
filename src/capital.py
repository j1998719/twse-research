"""資金限制下實際吃得到多少。

事件研究法算的是「每一次事件平均會怎樣」,假設每次都有錢進場。
真實情況是訊號會重疊 —— 同一天可能有十檔在等你買,而你的錢只夠買三檔。
這個模組把訊號排成時間軸,照先來後到吃,算出實際的資金報酬率。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


#: 一張 = 1000 股
LOT_SIZE = 1000

DAYS_PER_YEAR = 365.25


@dataclass(frozen=True)
class CapitalResult:
    """某個本金下的實際結果。"""

    #: 本金上限;None 代表不設限
    capital: float | None
    taken: int
    skipped: int
    #: 實際損益(元)
    pnl: float
    #: 對本金的報酬率;不設限時用高峰佔用金額當分母
    return_pct: float
    annualised_pct: float
    #: 資金有多少比例的時間在工作
    utilisation_pct: float
    max_concurrent: int
    peak_capital: float
    #: 資金實際在市場裡的天數(加權:半數資金在場算半天)
    exposure_days: float
    #: 每一天曝險換來多少報酬(基點,1 基點 = 0.01%)。
    #: 不要把它年化 —— 年化等於假設你能無限次重複部署,
    #: 但事件頻率是固定的,沒那麼多機會。要跟大盤比就比這個數字。
    return_per_exposure_day_bp: float


def position_cost(price: float, lot: int = LOT_SIZE) -> float:
    """買一個單位要多少錢。"""
    return price * lot


def _timeline(
    taken: pd.DataFrame, trading_days: pd.DatetimeIndex
) -> tuple[float, int, float]:
    """回傳(高峰佔用金額, 同時最多幾檔, 平均佔用金額)。"""
    if taken.empty:
        return 0.0, 0, 0.0
    peak = 0.0
    most = 0
    total = 0.0
    for day in trading_days:
        live = taken[(taken["buy_day"] <= day) & (taken["sell_day"] >= day)]
        used = float(live["cost"].sum())
        peak = max(peak, used)
        most = max(most, len(live))
        total += used
    return peak, most, total / len(trading_days)


def capital_run(
    events: pd.DataFrame,
    trading_days: pd.DatetimeIndex,
    capital: float | None = None,
    lot: int = LOT_SIZE,
) -> CapitalResult:
    """照時間順序吃訊號,錢不夠就跳過。

    events 需要 buy_day、sell_day、buy(進場價)、net(扣成本後的報酬 %)。
    capital 給 None 代表資金無限,每個訊號都吃。
    """
    if events.empty:
        return CapitalResult(capital, 0, 0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0)

    rows = events.copy()
    rows["buy_day"] = pd.to_datetime(rows["buy_day"])
    rows["sell_day"] = pd.to_datetime(rows["sell_day"])
    rows["cost"] = rows["buy"].astype(float) * lot
    rows = rows.sort_values("buy_day")

    # 用位置索引跑,不用 iterrows —— 後者的索引型別是寬鬆的 Hashable
    costs = rows["cost"].to_numpy(dtype=float)
    buys = rows["buy_day"].to_numpy()
    sells = rows["sell_day"].to_numpy()

    open_until: list[tuple[float, object]] = []
    chosen: list[int] = []
    for i in range(len(rows)):
        open_until = [(c, end) for c, end in open_until if end >= buys[i]]
        used = sum(c for c, _ in open_until)
        if capital is not None and used + costs[i] > capital:
            continue
        open_until.append((costs[i], sells[i]))
        chosen.append(i)

    taken = rows.iloc[chosen]
    pnl = float((taken["cost"] * taken["net"] / 100).sum())
    peak, most, mean_used = _timeline(taken, trading_days)

    base = capital if capital is not None else peak
    # 分母用整段研究期間,不是「第一次買到最後一次賣」——
    # 錢是整段期間都準備著的,空手的日子也是成本
    span = (trading_days.max() - trading_days.min()).days + 1
    ret = pnl / base * 100 if base else 0.0
    annual = ((1 + ret / 100) ** (DAYS_PER_YEAR / span) - 1) * 100 if span else 0.0

    exposure_days = mean_used / base * len(trading_days) if base else 0.0
    per_day_bp = ret / exposure_days * 100 if exposure_days > 0 else 0.0

    return CapitalResult(
        capital=capital,
        taken=len(taken),
        skipped=len(rows) - len(taken),
        pnl=round(pnl, 0),
        return_pct=round(ret, 1),
        annualised_pct=round(annual, 1),
        utilisation_pct=round(mean_used / base * 100, 1) if base else 0.0,
        max_concurrent=most,
        peak_capital=round(peak, 0),
        exposure_days=round(exposure_days, 1),
        return_per_exposure_day_bp=round(per_day_bp, 1),
    )
