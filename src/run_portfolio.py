"""把處置股策略放回日曆:權益曲線、最大回檔、多久沒創新高(#33)。

交易來自 pre_release_run 的頭條樣本(t−6 收盤買、t−1 收盤賣,漲跌停順延)。
每個訊號買 1 張,錢不夠就跳過;本金分 4 檔。基準是同一段日曆的加權指數
買進持有。這是量測,不是檢定:不掃參數,難看就照實寫。

用法:.venv/bin/python -m src.run_portfolio
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from src import cli
from src.disposition_study import pre_release_run, trading_days
from src.liquidity import chain_levels
from src.market import index_series
from src.portfolio import drawdown, losing_streak, simulate, underwater_days
from src.universe import all_prices, all_punishes


if TYPE_CHECKING:
    from datetime import date

RAW = Path("data/raw")
#: 除權息、減資、變更面額(fetch_actions)。持有期間遇到的交易,報酬是用未還原股價算的
ACTIONS = Path("data/out/corporate_actions.csv")
#: 本金分檔(#33 事前寫下的)
CAPITALS = (1_000_000, 3_000_000, 10_000_000, 30_000_000)
SECOND = 2
#: #30 的候選:整串第一次處置前 20 日成交金額中位數 ≥ 200 百萬(W2,#31)
W2_MIN = 200
DAYS_PER_YEAR = 365.25
#: #33 事前登記的連虧門檻(日曆天)。要不要改還在等 Jordan,這裡照實報
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


def touched_by_actions(runs: pd.DataFrame, actions: pd.DataFrame) -> pd.Series:
    """持有期間(買進日之後、賣出日當天以前)有沒有股本事件。

    事件研究的報酬用未還原股價算(#59):除息讓報酬偏低,減資讓股價跳上去變成
    假獲利。還原之前,用「排除這些交易」當敏感度檢查。
    """
    by_code: dict[str, list[pd.Timestamp]] = {}
    for code, day in zip(actions.code.astype(str), actions.day, strict=True):
        by_code.setdefault(code, []).append(pd.Timestamp(day))
    flags = [
        any(pd.Timestamp(b) < d <= pd.Timestamp(e) for d in by_code.get(str(c), []))
        for c, b, e in zip(runs.code, runs.buy_day, runs.sell_day, strict=True)
    ]
    return pd.Series(flags, index=runs.index)


def main() -> int:
    """兩組樣本 × 四檔本金,加上大盤基準。"""
    cli.no_args(__doc__)
    prices = all_prices()
    punishes = all_punishes()
    index = index_series(RAW / "prices")
    numbered = punishes[punishes.nth > 0]
    raw = pre_release_run(numbered, prices, index, all_punishes=punishes)
    runs = raw[raw.knowable & raw.truly_released & raw.excess.notna()]
    closes = prices.pivot_table(index="day", columns="code", values="close")
    closes.columns = closes.columns.astype(str)
    days = pd.DatetimeIndex(closes.index)

    bench = _benchmark(index, days)
    bench_dd = drawdown(bench)
    bench_under = underwater_days(bench)
    print(f"期間 {days[0]:%Y-%m-%d} ~ {days[-1]:%Y-%m-%d}({len(days)} 個交易日)")
    print("每個訊號買 1 張,錢不夠就跳過;來回成本 0.585% 在賣出時扣\n")
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
    actions = pd.read_csv(ACTIONS, dtype={"code": str}, parse_dates=["day"])
    touched = touched_by_actions(runs, actions)
    clean = runs[~touched]
    print(f"持有期間遇到股本事件的交易 {int(touched.sum())} 筆;敏感度檢查會把它們拿掉")
    samples = (
        ("全部", runs),
        ("第二次處置", runs[runs.nth == SECOND]),
        ("第二次 × W2≥200M(#30)", liquid[liquid.nth == SECOND]),
        ("全部,排除股本事件", clean),
        ("第二次,排除股本事件", clean[clean.nth == SECOND]),
    )
    for label, sample in samples:
        trades = sample[["code", "buy_day", "sell_day", "buy", "sell"]].assign(
            code=sample.code.astype(str)
        )
        print(f"\n{label}:訊號 {len(trades)} 筆(統計樣本 = 可交易訊號,重疊的都留著)")
        for capital in CAPITALS:
            out = simulate(trades, closes[sorted(set(trades.code))], capital)
            under = underwater_days(out.equity)
            dd = drawdown(out.equity)
            ok = [
                "MDD≤大盤 " + ("✅" if dd.pct >= bench_dd.pct else "❌"),
                f"沒創新高≤{UNDERWATER_LIMIT}天 "
                + ("✅" if under <= UNDERWATER_LIMIT else "❌"),
                "≤大盤 " + ("✅" if under <= bench_under else "❌"),
                "複利為正 " + ("✅" if out.equity.iloc[-1] > capital else "❌"),
            ]
            print(
                _line(
                    f"{capital / 10_000:,.0f} 萬",
                    out.equity,
                    f"  成交 {out.taken} / 跳過 {out.skipped}、同時最多 {out.max_concurrent} 檔"
                    f"、最長連虧 {losing_streak(out.pnls)} 筆",
                )
            )
            print(f"  {'':<10} {'  '.join(ok)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
