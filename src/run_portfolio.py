"""把處置股策略放回日曆:權益曲線、最大回檔、多久沒創新高(#33)。

交易來自 pre_release_run 的頭條樣本(t−6 收盤買、t−1 收盤賣,漲跌停順延)。
部位大小三種 mode(lot / fixed / fraction),本金分 4 檔。基準是同一段日曆的加權指數
買進持有。這是量測,不是檢定:不掃參數,難看就照實寫。

用法:.venv/bin/python -m src.run_portfolio
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from src import cli
from src.adjust import adjusted_closes
from src.disposition_study import pre_release_run, trading_days
from src.liquidity import chain_levels
from src.market import index_series
from src.portfolio import (
    SHARE,
    SIZINGS,
    Portfolio,
    drawdown,
    losing_streak,
    simulate,
    underwater_days,
)
from src.universe import all_actions, all_prices, all_punishes


if TYPE_CHECKING:
    from datetime import date

RAW = Path("data/raw")
#: 本金分檔(#33 事前寫下的)
CAPITALS = (1_000_000, 3_000_000, 10_000_000, 30_000_000)
SECOND = 2
#: #30 的候選:整串第一次處置前 20 日成交金額中位數 ≥ 200 百萬(W2,#31)
W2_MIN = 200
DAYS_PER_YEAR = 365.25
#: #33 原本的連虧門檻(日曆天)。Jordan 2026-10-07 改成「不超過大盤」,這個只列出來參考
UNDERWATER_LIMIT = 365


def _line(label: str, equity: pd.Series, extra: str = "") -> str:
    dd = drawdown(equity)
    span = (equity.index[-1] - equity.index[0]).days
    total = equity.iloc[-1] / equity.iloc[0] - 1
    annual = (1 + total) ** (DAYS_PER_YEAR / span) - 1 if span else 0.0
    back = "未回復" if dd.recovered is None else f"{dd.recovered:%Y-%m-%d} 回復"
    return (
        f"  {label:<10} 期末 {total * 100:+7.1f}%  年化 {annual * 100:+5.1f}%"
        f"  MDD {dd.pct:6.1f}%({dd.peak:%Y-%m-%d} → {dd.trough:%Y-%m-%d},{back})"
        f"  最長沒創新高 {underwater_days(equity):>4} 天{extra}"
    )


def _benchmark(index: dict[date, float], days: pd.DatetimeIndex) -> pd.Series:
    """同一段日曆的加權指數。缺的日子用前一天。"""
    series = pd.Series({pd.Timestamp(k): v for k, v in index.items()}).sort_index()
    return series.reindex(days).ffill().dropna()


def _row(label: str, out: Portfolio, bench_dd: float, bench_under: int) -> str:
    """一個 mode × 本金的結果,加上三條判準(#33)。365 天只列出來參考。"""
    eq = out.equity
    dd = drawdown(eq)
    under = underwater_days(eq)
    span = (eq.index[-1] - eq.index[0]).days
    total = eq.iloc[-1] / eq.iloc[0] - 1
    annual = (1 + total) ** (DAYS_PER_YEAR / span) - 1 if span else 0.0
    ok = "".join(
        "✅" if passed else "❌"
        for passed in (
            dd.pct >= bench_dd,
            under <= bench_under,
            eq.iloc[-1] > out.capital,
        )
    )
    ref = "≤365" if under <= UNDERWATER_LIMIT else ">365"
    return (
        f"  {label:<16} 年化 {annual * 100:+6.1f}%  MDD {dd.pct:6.1f}%"
        f"  沒創新高 {under:>4} 天({ref})  成交 {out.taken:>4} / 跳過 {out.skipped:>4}"
        f"  同時 {out.max_concurrent:>3} 檔  連虧 {losing_streak(out.pnls):>2}  {ok}"
    )


def main() -> int:
    """三組樣本 × 三種部位大小 × 四檔本金,加上大盤基準。"""
    cli.no_args(__doc__)
    prices = all_prices()
    punishes = all_punishes()
    index = index_series(RAW / "prices")
    actions = all_actions()
    raw = pre_release_run(
        punishes[punishes.nth > 0],
        prices,
        index,
        all_punishes=punishes,
        actions=actions,
    )
    runs = raw[raw.knowable & raw.truly_released & raw.excess.notna()]
    # 市值用還原收盤:除息那天淨值不會憑空掉一截、減資不會憑空漲一截(#59)
    marks = prices[["code", "day", "close"]].assign(code=prices.code.astype(str))
    if actions is not None:
        marks = (
            adjusted_closes(marks, actions)
            .drop(columns="close")
            .rename(columns={"adj_close": "close"})
        )
    closes = marks.pivot_table(index="day", columns="code", values="close")
    days = pd.DatetimeIndex(closes.index)

    bench = _benchmark(index, days)
    bench_dd = drawdown(bench).pct
    bench_under = underwater_days(bench)
    print(f"期間 {days[0]:%Y-%m-%d} ~ {days[-1]:%Y-%m-%d}({len(days)} 個交易日)")
    print("來回成本 0.585% 在賣出時扣;報酬與市值都已還原除權息(#59)")
    print(
        f"部位大小:lot = 每筆 1 張;fixed = 本金 {SHARE:.0%};fraction = 前一天淨值 {SHARE:.0%}"
    )
    print("判準(#33):MDD ≤ 大盤、最長沒創新高 ≤ 大盤、複利為正\n")
    print(_line("加權指數", bench, "(買進持有)"))

    levels = chain_levels(punishes, prices, trading_days(prices))
    w2 = {
        (str(c), pd.Timestamp(st)): v
        for c, st, v in zip(punishes.code, punishes.start, levels.w2, strict=True)
    }
    liquid = runs[
        [
            w2.get((str(c), pd.Timestamp(st)), float("nan")) >= W2_MIN
            for c, st in zip(runs.code, runs.start, strict=True)
        ]
    ]
    samples = (
        ("全部", runs),
        ("第二次處置", runs[runs.nth == SECOND]),
        ("第二次 × W2≥200M(#30)", liquid[liquid.nth == SECOND]),
    )
    for label, sample in samples:
        # gross 一定要帶進去:那是還原過的報酬,沒有它就會退回原始的賣價 ÷ 買價
        trades = sample[["code", "buy_day", "sell_day", "buy", "sell", "gross"]].assign(
            code=sample.code.astype(str)
        )
        print(f"\n{label}:訊號 {len(trades)} 筆(統計樣本 = 可交易訊號,重疊的都留著)")
        marks_needed = closes[sorted(set(trades.code))]
        for sizing in SIZINGS:
            for capital in CAPITALS:
                out = simulate(trades, marks_needed, capital, sizing=sizing)
                name = f"{sizing} {capital / 10_000:,.0f} 萬"
                print(_row(name, out, bench_dd, bench_under))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
