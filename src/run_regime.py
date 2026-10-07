"""分市況、分制度期間檢驗「出關前一日見頂」這個發現。

用法:.venv/bin/python -m src.run_regime
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from scipy import stats

from src import cli
from src.disposition_study import event_rate, pre_release_run, summarise
from src.market import index_series, parse_exrights
from src.regime import (
    CONTINUOUS_TRADING_FROM,
    MARKET_REGIMES,
    slice_by,
)


if TYPE_CHECKING:
    from datetime import date


RAW = Path("data/raw")
OUT = Path("data/out")

#: 少於這個數字連中位數都不穩,直接標示樣本太少
MIN_SAMPLES = 3
#: 低於這個數字的 p 值才當成顯著
ALPHA = 0.05
#: 少於這個數字的結果要加註警語,不要看起來很確定
SMALL_SAMPLE = 30
#: 第二次處置
SECOND_DISPOSITION = 2


def load() -> tuple[pd.DataFrame, pd.DataFrame, dict[date, float]]:
    """讀回價量、處置公告與大盤指數。"""
    prices = pd.read_csv(OUT / "prices.csv", parse_dates=["day"])
    punishes = pd.read_csv(
        OUT / "punishes.csv", parse_dates=["announced", "start", "end"]
    )
    index = index_series(RAW / "prices")
    return prices, punishes[punishes.nth > 0], index


def exrights() -> set[tuple[date, str]]:
    """所有除權息事件。"""
    found: set[tuple[date, str]] = set()
    for path in sorted(RAW.glob("exright_*.json")):
        found |= parse_exrights(json.loads(path.read_text(encoding="utf-8")))
    return found


def report(label: str, values: np.ndarray, width: int = 22) -> None:
    """一行摘要。樣本太少就直說,不要給一個看起來很確定的 p 值。"""
    if len(values) < MIN_SAMPLES:
        print(f"  {label:<{width}} n={len(values):>4}  樣本太少")
        return
    _, p = stats.wilcoxon(values)
    mark = "✓" if p < ALPHA else " "
    warn = "  (樣本少,參考用)" if len(values) < SMALL_SAMPLE else ""
    print(
        f"  {label:<{width}} n={len(values):>4}  中位數 {np.median(values):+6.2f}%"
        f"  平均 {values.mean():+6.2f}%  勝率 {(values > 0).mean() * 100:4.1f}%"
        f"  p={p:.4f} {mark}{warn}"
    )


def main() -> None:
    """分段跑完所有檢定並印出結果。"""
    cli.no_args(__doc__)
    prices, punishes, index = load()
    runs = pre_release_run(punishes, prices, index)
    runs = runs[runs.excess.notna()]
    print(f"資料期間 {prices.day.min().date()} ~ {prices.day.max().date()}")
    print(f"納入研究的處置事件 {len(runs)} 筆\n")

    print("=" * 78)
    print("逐年:t-6 收盤買、出關前一日收盤賣,超額報酬(已扣成本與大盤)")
    print("=" * 78)
    for period in MARKET_REGIMES:
        sub = slice_by(runs, period)
        report(period.name, sub.excess.dropna().to_numpy())

    print("\n" + "=" * 78)
    print("只看第二次處置")
    print("=" * 78)
    second = runs[runs.nth == SECOND_DISPOSITION]
    for period in MARKET_REGIMES:
        sub = slice_by(second, period)
        report(period.name, sub.excess.dropna().to_numpy())

    print("\n" + "=" * 78)
    print("證偽測試:逐筆交易上路前,正常交易本來就是集合競價")
    print("那段期間若也有效,「處置壓縮流動性」的解釋就站不住")
    print("=" * 78)
    days = pd.to_datetime(runs.buy_day).dt.date
    before = runs[days < CONTINUOUS_TRADING_FROM]
    after = runs[days >= CONTINUOUS_TRADING_FROM]
    report("逐筆交易上路前", before.excess.dropna().to_numpy())
    report("逐筆交易上路後", after.excess.dropna().to_numpy())

    print("\n" + "=" * 78)
    print("事件頻率")
    print("=" * 78)
    for key, value in event_rate(runs).items():
        print(f"  {key:<12} {value}")

    print("\n整段期間彙總:")
    for key, value in summarise(runs, "excess").items():
        print(f"  {key:<10} {value}")


if __name__ == "__main__":
    main()
