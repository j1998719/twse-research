"""產生網頁要用的 report.json。

欄位必須跟 web/src/report.ts 的 REQUIRED_KEYS 一致,
`tests/test_report_contract.py` 會檢查。
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from src.backtest import (
    Timing,
    event_rate,
    exit_returns,
    pre_release_run,
    summarise,
    trading_days,
    win_loss,
)
from src.capital import capital_run
from src.market import index_series
from src.regime import MARKET_REGIMES, slice_by
from src.universe import all_prices, all_punishes


RAW = Path("data/raw")
OUT = Path("data/out")

#: 出場時點的三種選擇,用來展示「差一天差很多」
EXIT_CHOICES = ((-6, -1, "出關前一日"), (-6, 0, "出關日"), (-6, 1, "出關後一日"))
#: 資金限制的對照組
CAPITAL_LEVELS: tuple[float | None, ...] = (None, 5_000_000, 1_000_000, 500_000)
#: 價格路徑上要畫的區間
PATH_RANGE = range(-6, 6)
MIN_SAMPLES = 3
SECOND = 2
#: 未來交易日用平日推算,往後推這麼多天夠用
PROJECT_DAYS = 40


def _p(values: np.ndarray) -> float | None:
    """Wilcoxon 檢定的 p 值。樣本太少就回 None。"""
    if len(values) < MIN_SAMPLES:
        return None
    return round(float(stats.wilcoxon(values)[1]), 4)


def _projected_days(days: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """已知交易日 + 往後推算的平日。國定假日無法預知,所以只能用平日。"""
    out = list(days)
    cursor = days.max().date()
    for _ in range(PROJECT_DAYS):
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:  # noqa: PLR2004
            out.append(pd.Timestamp(cursor))
    return out


def _shift(
    seq: list[pd.Timestamp], day: pd.Timestamp, steps: int
) -> pd.Timestamp | None:
    """在交易日序列上位移。找不到就回 None。"""
    nearest = min(range(len(seq)), key=lambda k: abs((seq[k] - day).days))
    target = nearest + steps
    return seq[target] if 0 <= target < len(seq) else None


def _status(today: pd.Timestamp, buy: pd.Timestamp, sell: pd.Timestamp) -> str:
    if today > sell:
        return "已過賣點"
    if today.date() == sell.date():
        return "今天賣出"
    if today >= buy:
        return "持有中"
    return "尚未到買點"


def _current(
    punishes: pd.DataFrame,
    runs: pd.DataFrame,
    seq: list[pd.Timestamp],
    known_last: pd.Timestamp,
    today: pd.Timestamp,
) -> list[dict[str, Any]]:
    """仍在處置期間的個股,附歷史同類事件的統計。"""
    rows: list[dict[str, Any]] = []
    for raw in punishes[punishes.end >= today].sort_values("end").to_dict("records"):
        release = _shift(seq, pd.Timestamp(raw["end"]), 1)
        if release is None:
            continue
        buy = _shift(seq, release, -6)
        sell = _shift(seq, release, -1)
        if buy is None or sell is None:
            continue
        nth = SECOND if raw["measure"] == "第二次處置" else 1
        hist = runs[runs.nth == nth]
        stat = summarise(hist, "excess")
        split = win_loss(hist, "excess")
        rows.append(
            {
                "code": int(raw["code"]),
                "name": str(raw["name"]),
                "measure": str(raw["measure"]),
                "condition": str(raw["condition"]),
                "start": str(pd.Timestamp(raw["start"]).date()),
                "end": str(pd.Timestamp(raw["end"]).date()),
                "daysLeft": int((pd.Timestamp(raw["end"]) - today).days) + 1,
                "release": str(release.date()),
                "buyDay": str(buy.date()),
                "sellDay": str(sell.date()),
                "status": _status(today, buy, sell),
                "projected": bool(release > known_last),
                "histN": stat["樣本數"],
                "histMedian": stat["中位數%"],
                "histWin": stat["勝率%"],
                "histEV": split["期望值%"],
                "histWinAvg": split["賺_平均%"],
                "histLossAvg": split["賠_平均%"],
                "histWorst": stat["最小%"],
            }
        )
    return rows


def _offenders(numbered: pd.DataFrame, limit: int = 12) -> list[dict[str, Any]]:
    """反覆被處置的個股,依次數排序。"""
    rows: list[dict[str, Any]] = []
    for (code, name), group in numbered.groupby(["code", "name"]):
        rows.append(
            {
                "code": int(str(code)),
                "name": str(name),
                "total": int(group.shape[0]),
                "second": int((group.nth == SECOND).sum()),
            }
        )
    rows.sort(key=lambda row: -int(row["total"]))
    return rows[:limit]


def build(today: pd.Timestamp) -> dict[str, Any]:
    """讀出所有資料,算出網頁要的每一塊。"""
    # 全市場(上市 + 上櫃)。原本只讀 prices.csv / punishes.csv,所以網頁顯示
    # 951 筆而程式跑出 2,265 筆 —— 兩邊對不上,而網頁是給人看的那一份([#23])
    prices = all_prices()
    punishes = all_punishes()
    # 注意股公告目前只有上市。櫃買中心的注意股端點還沒接,所以這個數字
    # 是上市的,不是全市場的 —— coverage 裡會標明
    notices = pd.read_csv(OUT / "notices.csv", parse_dates=["day"])
    index = index_series(RAW / "prices")
    days = trading_days(prices)
    numbered = punishes[punishes.nth > 0]

    raw_runs = pre_release_run(numbered, prices, index, all_punishes=punishes)
    runs = raw_runs[
        raw_runs.knowable & raw_runs.truly_released & raw_runs.excess.notna()
    ]

    series = pd.Series({pd.Timestamp(k): v for k, v in index.items()}).sort_index()
    span = (days.max() - days.min()).days + 1
    market = float((series.iloc[-1] / series.iloc[0] - 1) * 100)

    years = []
    for period in MARKET_REGIMES:
        values = slice_by(runs, period).excess.dropna().to_numpy()
        if len(values) < MIN_SAMPLES:
            continue
        years.append(
            {
                "name": period.name,
                "n": len(values),
                "median": round(float(np.median(values)), 2),
                "win": round(float((values > 0).mean() * 100), 1),
                "p": _p(values),
                "bear": "空頭" in period.name,
            }
        )

    exits = []
    for entry, exit_, label in EXIT_CHOICES:
        variant = pre_release_run(
            numbered,
            prices,
            index,
            Timing(entry=entry, exit=exit_),
            all_punishes=punishes,
        )
        variant = variant[variant.knowable & variant.truly_released]
        values = variant.excess.dropna().to_numpy()
        exits.append(
            {
                "label": label,
                "n": len(values),
                "median": round(float(np.median(values)), 2),
                "win": round(float((values > 0).mean() * 100), 1),
                "p": _p(values),
            }
        )

    second = runs[runs.nth == SECOND]
    caps: list[dict[str, Any]] = []
    for level in CAPITAL_LEVELS:
        result = capital_run(second, days, capital=level)
        caps.append(
            {
                "capital": level,
                "taken": result.taken,
                "total": len(second),
                "ret": result.return_pct,
                "ann": result.annualised_pct,
                "days": result.exposure_days,
                "bp": result.return_per_exposure_day_bp,
                "concurrent": result.max_concurrent,
            }
        )
    caps.append(
        {
            "capital": "market",
            "taken": None,
            "total": None,
            "ret": round(market, 1),
            "ann": round(((1 + market / 100) ** (365.25 / span) - 1) * 100, 1),
            "days": span,
            "bp": round(market / span * 100, 1),
            "concurrent": None,
        }
    )

    after = exit_returns(numbered, prices, index)
    seq = _projected_days(days)

    return {
        "generated": str(today.date()),
        "coverage": {
            "from": str(days.min().date()),
            "to": str(days.max().date()),
            "notices": len(notices),
            "noticesMarket": "twse",
            "punishes": len(punishes),
            "tradingDays": len(days),
            "backtested": len(runs),
            "codes": int(prices.code.nunique()),
            "markets": _by_market(prices, punishes, runs),
            "dropped": {
                "lookahead": int((~raw_runs.knowable).sum()),
                "fakeRelease": int(
                    (raw_runs.knowable & ~raw_runs.truly_released).sum()
                ),
            },
        },
        "current": _current(punishes, runs, seq, days.max(), today),
        "headline": summarise(runs, "excess"),
        "winloss": win_loss(runs, "excess"),
        "winlossSecond": win_loss(second, "excess"),
        "years": years,
        "exits": exits,
        "caps": caps,
        "afterRelease": summarise(after[~after.locked_up], "x5"),
        "rate": event_rate(runs),
        "binomial": round(0.5 ** len(years), 4),
        "monthly": [
            {"m": str(k), "n": int(v)}
            for k, v in numbered.groupby(numbered.announced.dt.to_period("M"))
            .size()
            .items()
        ],
        "offenders": _offenders(numbered),
        "dist": runs.excess.dropna().round(1).tolist(),
    }


def _by_market(
    prices: pd.DataFrame, punishes: pd.DataFrame, runs: pd.DataFrame
) -> dict[str, dict[str, int]]:
    """分市場的檔數、公告數、可回測事件數。

    上櫃的流動性比上市差,一個分不出市場的涵蓋率等於把兩個不同的東西
    當成一個([#23])。事件的市場要從公告那一列認,不是按代號查 ——
    轉上市的股票兩邊都有公告。
    """
    label = {
        (str(row["code"]), pd.Timestamp(row["start"]).date()): str(row["market"])
        for row in punishes.to_dict("records")
    }
    events: dict[str, int] = {}
    for row in runs.to_dict("records"):
        key = (str(row["code"]), pd.Timestamp(row["start"]).date())
        market = label.get(key, "?")
        events[market] = events.get(market, 0) + 1
    out: dict[str, dict[str, int]] = {}
    for market in sorted({*prices.market.unique(), *punishes.market.unique()}):
        out[str(market)] = {
            "codes": int(prices[prices.market == market].code.nunique()),
            "punishes": int((punishes.market == market).sum()),
            "backtested": events.get(str(market), 0),
        }
    return out


def main() -> None:
    """產生 report.json。"""
    report = build(pd.Timestamp.today().normalize())
    path = OUT / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"輸出 {path}:{report['coverage']['backtested']} 筆可回測事件")


if __name__ == "__main__":
    main()
