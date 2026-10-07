"""漲停的質:跑 #27 事前登記的 4 個分組比較。

漲停日的下一個交易日收盤進場、持有 5 個交易日(#22 框架的超額:扣成本、扣等權宇集、
漲跌停順延、還原除權息),流動性門檻 20 日成交金額中位數 ≥ 1,000 萬元。

- G1 一價到底 vs 盤中打開過
- G2 第 1 根 vs 連續第 3 根以上
- G3 量比最高三分之一 vs 最低三分之一
- G4 前 60 日漲幅最低三分之一(從底部起漲)vs 最高三分之一(已經漲一大段)

兩組合起來按月去期間化(每筆減掉同月中位數)再做 Mann-Whitney 雙尾。形成 = 上市,
4 個一次 BH;三分位切點用上市算、上櫃沿用;驗證 = 上櫃,只跑找到了的,不再校正。

用法:.venv/bin/python -m src.run_limitups
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from src import cli
from src.disposition_study import trading_days
from src.events.limitups import limit_up_events
from src.liquidity import MILLION, daily_value, level
from src.run_chip_signals import Excess, placebo_hits, scored, summarize
from src.run_wholemarket import closes_by_code
from src.tpex import is_common_stock
from src.universe import all_actions, all_prices


if TYPE_CHECKING:
    from collections.abc import Callable

    from src.events.chips import Hit

HOLD = 5
MIN_VALUE = 10
ALPHA = 0.05
TERCILE = (1 / 3, 2 / 3)


@dataclass(frozen=True)
class Split:
    """一組比較的結果。"""

    name: str
    n_a: int
    n_b: int
    med_a: float
    med_b: float
    pre_a: float
    pre_b: float
    p: float


def groups(
    ev: pd.DataFrame, cuts: dict[str, tuple[float, float]]
) -> dict[str, tuple[pd.Series, pd.Series]]:
    """4 個分組:名稱 → (A 組遮罩, B 組遮罩)。"""
    v_lo, v_hi = cuts["vol_ratio"]
    p_lo, p_hi = cuts["prior60"]
    return {
        "G1 一價到底 vs 盤中打開": (ev.one_price, ~ev.one_price),
        "G2 第 1 根 vs 第 3 根以上": (ev.streak == 1, ev.streak >= 3),  # noqa: PLR2004
        "G3 量比高 vs 低": (ev.vol_ratio >= v_hi, ev.vol_ratio <= v_lo),
        "G4 底部起漲 vs 已經漲一大段": (ev.prior60 <= p_lo, ev.prior60 >= p_hi),
    }


def compare(
    name: str,
    a: list[Hit],
    b: list[Hit],
    score: Callable[[list[Hit]], pd.DataFrame],
) -> Split:
    """兩組各自算超額(同組內窗口不重疊),合起來按月去期間化,再比。"""
    fa, fb = score(a).assign(side="a"), score(b).assign(side="b")
    both = pd.concat([fa, fb], ignore_index=True)
    month = both.day.dt.to_period("M")
    both["dm"] = both.excess - both.groupby(month).excess.transform("median")
    da, db = both.dm[both.side == "a"], both.dm[both.side == "b"]
    p = float(stats.mannwhitneyu(da, db, alternative="two-sided").pvalue)
    return Split(
        name,
        len(fa),
        len(fb),
        float(fa.excess.median()),
        float(fb.excess.median()),
        float(fa.pre.median()),
        float(fb.pre.median()),
        p,
    )


def line(s: Split, q: float | None) -> str:
    """一列結果。"""
    tag = f"BH p={q:.4f}" if q is not None else f"p={s.p:.4f}"
    return (
        f"  {s.name:<22} A n={s.n_a:>5} {s.med_a:+.2f}%(事件前 5 日 {s.pre_a:+.2f}%)"
        f"  B n={s.n_b:>5} {s.med_b:+.2f}%(事件前 5 日 {s.pre_b:+.2f}%)"
        f"  差 {s.med_a - s.med_b:+.2f}  {tag}"
    )


def tercile_cuts(frame: pd.DataFrame) -> dict[str, tuple[float, float]]:
    """量比和前 60 日漲幅的三分位切點(用形成組算,驗證組沿用)。"""
    out: dict[str, tuple[float, float]] = {}
    for col in ("vol_ratio", "prior60"):
        lo, hi = (float(frame[col].quantile(t)) for t in TERCILE)
        out[col] = (lo, hi)
    return out


def describe(
    listed: pd.DataFrame,
    codes: list[str],
    days: pd.DatetimeIndex,
    score: Callable[[list[Hit]], pd.DataFrame],
    market_of: dict[str, str],
) -> None:
    """描述(不是檢定):上市全部漲停 vs 同期隨機股票。"""
    all_lu = score(list(zip(listed.code, listed.day, strict=True)))
    null = score(placebo_hits(codes, days))
    s1, s0 = summarize(all_lu, market_of), summarize(null, market_of)
    print(
        f"\n描述(不是檢定):上市全部漲停 n={s1['n']} 中位數 {s1['median']:+.2f}%  vs  "
        f"安慰劑 n={s0['n']} {s0['median']:+.2f}%"
    )


def load() -> tuple[
    pd.DataFrame, pd.DatetimeIndex, Excess, pd.DataFrame, dict[str, str]
]:
    """普通股價格、交易日、超額報酬計算器、每日成交金額、漲停事件(帶市場)。"""
    prices = all_prices()
    prices = prices[prices.code.astype(str).map(is_common_stock)]
    prices = prices.assign(code=prices.code.astype(str))
    actions = all_actions()
    acts = (
        set()
        if actions is None
        else {
            (str(c), pd.Timestamp(d))
            for c, d in zip(actions.code, actions.day, strict=True)
        }
    )
    market_of = {
        str(c): str(m) for c, m in zip(prices.code, prices.market, strict=True)
    }
    ev = limit_up_events(prices, acts)
    ev["market"] = ev.code.map(market_of)
    excess = Excess(closes_by_code(prices, actions))
    return ev, trading_days(prices), excess, daily_value(prices), market_of


def main() -> int:
    """形成(上市)4 個一次 BH、驗證(上櫃)、安慰劑描述。"""
    cli.no_args(__doc__)
    ev, days, excess, value, market_of = load()

    def liquid(code: str, day: pd.Timestamp) -> bool:
        got = level(value, code, day)
        return got is not None and got >= MIN_VALUE * MILLION

    def score(hits: list[Hit]) -> pd.DataFrame:
        return scored(hits, HOLD, days, excess, liquid)

    listed = ev[ev.market == "twse"]
    cuts = tercile_cuts(listed)
    print(f"漲停 {len(ev):,} 次(上市 {len(listed):,}、上櫃 {len(ev) - len(listed):,})")
    print(
        f"三分位切點(上市):量比 {cuts['vol_ratio']}、前 60 日漲幅 {cuts['prior60']}\n"
    )

    def run(frame: pd.DataFrame) -> list[Split]:
        out = []
        for name, (ma, mb) in groups(frame, cuts).items():
            a = list(zip(frame.code[ma], frame.day[ma], strict=True))
            b = list(zip(frame.code[mb], frame.day[mb], strict=True))
            out.append(compare(name, a, b, score))
        return out

    form = run(listed)
    q = [float(x) for x in multipletests([s.p for s in form], method="fdr_bh")[1]]
    print("形成組(上市),4 個比較一次 BH(A − B,按月去期間化):")
    for s, adj in zip(form, q, strict=True):
        print(line(s, adj) + ("  找到了" if adj < ALPHA else ""))
    if any(adj < ALPHA for adj in q):
        print("\n驗證組(上櫃,同一組切點,只跑找到了的,不再校正):")
        for s, f0, adj in zip(run(ev[ev.market == "otc"]), form, q, strict=True):
            if adj < ALPHA:
                same = (s.med_a - s.med_b) * (f0.med_a - f0.med_b) > 0
                print(
                    line(s, None)
                    + f"  → {'成立' if same and s.p < ALPHA else '不成立'}"
                )
    else:
        # 登記的「線索」判準:上市不顯著,但上市、上櫃方向一致。只看方向,不再檢定
        print("\n形成組沒有找到了。線索判斷(上櫃同一組切點,只看方向):")
        for s, f0 in zip(run(ev[ev.market == "otc"]), form, strict=True):
            same = (s.med_a - s.med_b) * (f0.med_a - f0.med_b) > 0
            print(line(s, None) + f"  → {'方向一致:線索' if same else '方向相反'}")
    twse = sorted({c for c, m in market_of.items() if m == "twse"} & set(excess.closes))
    describe(listed, twse, days, score, market_of)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
