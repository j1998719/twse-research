"""出關前那波漲勢,是誰在買?

兩個問題要分開:
  描述性 —— 那段期間法人是買超還是賣超(可以用當期資料)
  預測性 —— 進場「之前」的法人動向能不能預測後續(必須落後一天,
            因為法人買賣超是收盤後才公布的)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from src import cli
from src.disposition_study import (
    pre_release_run,
    shift_trading_day,
    trading_days,
    win_loss,
)
from src.market import index_series
from src.universe import all_actions


OUT = Path("data/out")
RAW = Path("data/raw")

#: 出關前的進出場偏移,跟 pre_release_run 的預設一致
ENTRY = -6
EXIT = -1
ALPHA = 0.05
#: 少於這個數字連中位數都不穩
MIN_SAMPLES = 3


def net_flow(
    chips: pd.DataFrame,
    days: pd.DatetimeIndex,
    code: object,
    end: pd.Timestamp,
    span: int,
) -> dict[str, float]:
    """End 往前 span 個交易日的法人買賣超合計(張)。"""
    first = shift_trading_day(days, end, -(span - 1))
    if first is None:
        return {}
    window = chips[
        (chips["code"] == code) & (chips["day"] >= first) & (chips["day"] <= end)
    ]
    if window.empty:
        return {}
    return {
        "外資": float(window["foreign"].sum()) / 1000,
        "投信": float(window["trust"].sum()) / 1000,
        "自營": float(window["dealer"].sum()) / 1000,
        "合計": float(window[["foreign", "trust", "dealer"]].to_numpy().sum()) / 1000,
    }


def show(label: str, values: np.ndarray) -> None:
    """一行摘要。"""
    if len(values) < MIN_SAMPLES:
        print(f"  {label:<26} n={len(values):>4}  樣本太少")
        return
    _, p = stats.wilcoxon(values)
    print(
        f"  {label:<26} n={len(values):>4}  中位數 {np.median(values):+6.2f}%"
        f"  勝率 {(values > 0).mean() * 100:4.1f}%  p={p:.4f}"
        f" {'✓' if p < ALPHA else ''}"
    )


def main() -> None:
    """跑完描述性與預測性兩段分析。"""
    cli.no_args(__doc__)
    prices = pd.read_csv(OUT / "prices.csv", parse_dates=["day"])
    punishes = pd.read_csv(
        OUT / "punishes.csv", parse_dates=["announced", "start", "end"]
    )
    chips = pd.read_csv(OUT / "chips.csv", parse_dates=["day"])
    index = index_series(RAW / "prices")
    days = trading_days(prices)

    runs = pre_release_run(
        punishes[punishes.nth > 0], prices, index, actions=all_actions()
    )
    runs = runs[runs.knowable & runs.excess.notna()].copy()
    print(
        f"處置事件 {len(runs)} 筆,法人資料 {chips.day.min().date()} ~ {chips.day.max().date()}\n"
    )

    # 持有期間(t-6 到 t-1)的法人動向 —— 描述性
    during: list[dict[str, float]] = []
    before: list[dict[str, float]] = []
    for row in runs.to_dict("records"):
        sell_day = pd.Timestamp(str(row["sell_day"]))
        buy_day = pd.Timestamp(str(row["buy_day"]))
        during.append(
            net_flow(chips, days, row["code"], sell_day, abs(ENTRY - EXIT) + 1)
        )
        # 進場前一天為止,這才是下單當下看得到的資訊
        prior = shift_trading_day(days, buy_day, -1)
        before.append(
            net_flow(chips, days, row["code"], prior, 5) if prior is not None else {}
        )

    runs["持有期間_法人"] = [d.get("合計", np.nan) for d in during]
    runs["持有期間_外資"] = [d.get("外資", np.nan) for d in during]
    runs["持有期間_投信"] = [d.get("投信", np.nan) for d in during]
    runs["進場前_法人"] = [d.get("合計", np.nan) for d in before]

    _describe(runs)
    _predict(runs)


def _describe(runs: pd.DataFrame) -> None:
    """出關前那波,法人在買還是在賣。"""
    print("=" * 74)
    print("描述性:出關前那波,法人在買還是在賣")
    print("=" * 74)
    have = runs[runs["持有期間_法人"].notna()]
    for col in ("持有期間_法人", "持有期間_外資", "持有期間_投信"):
        v = have[col]
        print(
            f"  {col:<14} 買超比例 {(v > 0).mean() * 100:4.1f}%"
            f"  中位數 {v.median():+8.0f} 張  平均 {v.mean():+9.0f} 張"
        )

    print("\n依法人動向分組看報酬:")
    show("法人買超的事件", have[have["持有期間_法人"] > 0].excess.to_numpy())
    show("法人賣超的事件", have[have["持有期間_法人"] < 0].excess.to_numpy())


def _predict(runs: pd.DataFrame) -> None:
    """進場前的法人動向能不能預測後續。"""
    print("\n" + "=" * 74)
    print("預測性:進場前五日的法人動向(下單當下看得到的資訊)")
    print("=" * 74)
    prior_have = runs[runs["進場前_法人"].notna()]
    show("進場前法人買超", prior_have[prior_have["進場前_法人"] > 0].excess.to_numpy())
    show("進場前法人賣超", prior_have[prior_have["進場前_法人"] < 0].excess.to_numpy())

    a = prior_have[prior_have["進場前_法人"] > 0].excess.to_numpy()
    b = prior_have[prior_have["進場前_法人"] < 0].excess.to_numpy()
    if len(a) >= MIN_SAMPLES and len(b) >= MIN_SAMPLES:
        _, p = stats.mannwhitneyu(a, b, alternative="two-sided")
        verdict = "可以當過濾條件" if p < ALPHA else "沒有預測力,不能當過濾條件"
        print(f"\n  兩組差異 p={p:.4f}  → {verdict}")

    print("\n買超那組的賺賠結構:")
    for key, value in win_loss(
        prior_have[prior_have["進場前_法人"] > 0], "excess"
    ).items():
        print(f"  {key:<12} {value}")


if __name__ == "__main__":
    main()
