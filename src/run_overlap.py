"""第一次還沒結束就公告第二次處置的,是不是不一樣?跑 #32 事前登記的 4 個檢定。

重疊深度 = 第一次的結束日 − 第二次的公告日(營業日)。≥ 0 = 第一次還沒結束就公告。
- O1:重疊(深度 ≥ 0)vs 沒重疊
- O2:深度 ≥ 0 / ≥ 5 / ≥ 10 vs 其他(重疊越深,效應應該越單調)
一次 BH 校正;O2 另外報五分位、Spearman、去期間化版本;分組變數跟進場日報酬的
Spearman 檢查 look-ahead;O1 在 W2 中位數上下兩半各跑一次,看是不是 W2 的鏡像(#31)。

報酬跟 #30 / #31 同一份:第二次處置,#22 框架扣等權宇集、漲跌停順延、還原除權息。
兩組互相比較,不受「跟 0 比」的偏差影響(#60)。

用法:.venv/bin/python -m src.run_overlap
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from src import cli
from src.disposition_study import trading_days
from src.run_chain_liquidity import second_dispositions
from src.universe import all_prices, all_punishes


SECOND = 2
#: O2 的門檻(營業日)
DEPTHS = (0, 5, 10)
ALPHA = 0.05
#: look-ahead 的警戒線:分組變數跟進場日報酬的 |Spearman|
LOOKAHEAD_R = 0.3
QUINTILES = 5


def overlap_depth(punishes: pd.DataFrame, days: pd.DatetimeIndex) -> pd.Series:
    """每一列第二次處置的重疊深度(營業日);其他列和找不到前一次的是 None。

    「前一次」= 同一檔、公告日比它早的最近一次編號處置。日期不是交易日時,
    取它之後的第一個交易日位置。
    """
    out: list[int | None] = [None] * len(punishes)
    announced = pd.to_datetime(punishes.announced)
    ends = pd.to_datetime(punishes.end)
    counted = punishes.nth > 0
    for i, (code, nth, when) in enumerate(
        zip(punishes.code, punishes.nth, announced, strict=True)
    ):
        if nth != SECOND:
            continue
        before = counted & (punishes.code == code) & (announced < when)
        if not before.any():
            continue
        prev = announced[before].idxmax()
        out[i] = int(days.searchsorted(ends[prev])) - int(days.searchsorted(when))
    return pd.Series(out, index=punishes.index, dtype=object)


@dataclass(frozen=True)
class Split:
    """一組比較:符合的那組 vs 其他。"""

    name: str
    n: int
    n_rest: int
    med: float
    med_rest: float
    p: float

    @property
    def gap(self) -> float:
        """中位數差(百分點)。"""
        return self.med - self.med_rest

    def line(self) -> str:
        """一行摘要(不含校正後 p)。"""
        return (
            f"{self.name:<18} n={self.n:>4} 中位數 {self.med:+.2f}%  vs  n={self.n_rest:>4}"
            f" {self.med_rest:+.2f}%  差 {self.gap:+.2f}  原始 p={self.p:.4f}"
        )


def compare(name: str, table: pd.DataFrame, mask: pd.Series) -> Split | None:
    """符合 mask 的 vs 其他,Mann-Whitney 雙尾。有一組是空的就回 None(檢定不了)。"""
    a, b = table.new[mask].dropna(), table.new[~mask].dropna()
    if a.empty or b.empty:
        return None
    p = float(stats.mannwhitneyu(a, b, alternative="two-sided").pvalue)
    return Split(name, len(a), len(b), float(a.median()), float(b.median()), p)


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    """第二次處置的報酬表(帶重疊深度)與價格。"""
    prices = all_prices()
    punishes = all_punishes()
    depth = overlap_depth(punishes, trading_days(prices))
    by_key = {
        (str(c), pd.Timestamp(s)): d
        for c, s, d in zip(punishes.code, punishes.start, depth, strict=True)
    }
    table = second_dispositions(prices, punishes)
    table["depth"] = [
        by_key.get((c, s)) for c, s in zip(table.code, table.start, strict=True)
    ]
    table = table[table.depth.notna() & table.new.notna()]
    return table.assign(depth=table.depth.astype(int)), prices


def registered(table: pd.DataFrame) -> None:
    """登記的 4 個檢定,一次 BH。檢定不了的(有一組是空的)不放進家族,照實標出。"""
    planned = [("O1 重疊 vs 沒重疊", table.depth >= 0)]
    planned += [(f"O2 深度 ≥ {k} vs 其他", table.depth >= k) for k in DEPTHS]
    tests: list[Split] = []
    for name, mask in planned:
        got = compare(name, table, mask)
        if got is None:
            # 處置期間大約 10 個營業日,重疊深度最多 9,「≥ 10」那組是空的 —— 登記時沒料到
            print(
                f"{name:<18} 檢定不了:有一組是空的(重疊深度最大 {table.depth.max()} 個營業日)"
            )
        else:
            tests.append(got)
    adjusted = multipletests([t.p for t in tests], method="fdr_bh")[1]
    for t, q in zip(tests, adjusted, strict=True):
        print(f"{t.line()}  BH p={q:.4f}")


def dose(table: pd.DataFrame) -> None:
    """O2 的劑量反應:五分位、Spearman,原始與去期間化。"""
    demeaned = table.new - table.groupby("month").new.transform("median")
    bucket = pd.qcut(table.depth.rank(method="first"), QUINTILES, labels=False) + 1
    print("\nO2 五分位(深度由淺到深):")
    for b in sorted(bucket.unique()):
        g = bucket == b
        print(
            f"  Q{b}  深度 {table.depth[g].min():>4}~{table.depth[g].max():>4}  n={int(g.sum()):>3}"
            f"  中位數 {table.new[g].median():+.2f}%  去期間化 {demeaned[g].median():+.2f}%"
        )
    for values, label in ((table.new, "原始"), (demeaned, "去期間化")):
        r, p = stats.spearmanr(table.depth, values)
        print(f"  Spearman(深度, {label}) r={r:+.3f} p={p:.4f}")


def lookahead(table: pd.DataFrame, prices: pd.DataFrame) -> None:
    """分組變數跟進場日當天報酬的 Spearman。|r| > 0.3 就是偷看未來的警訊。"""
    closes = prices.assign(code=prices.code.astype(str)).pivot_table(
        index="day", columns="code", values="close"
    )
    ret = closes.pct_change(fill_method=None).stack()  # noqa: PD013 —— 要的是 (日期, 代號) 查表
    day_ret = [
        ret.get((pd.Timestamp(e), c))
        for c, e in zip(table.code, table.entry, strict=True)
    ]
    r, _ = stats.spearmanr(
        table.depth, pd.Series(day_ret, dtype=float), nan_policy="omit"
    )
    flag = "⚠️ 超過警戒線" if abs(r) > LOOKAHEAD_R else "OK"
    print(
        f"\nlook-ahead:Spearman(深度, 進場日當天報酬) r={r:+.3f}({flag},門檻 |r| > {LOOKAHEAD_R})"
    )


def by_w2(table: pd.DataFrame) -> None:
    """控制 W2(#31):O1 在 W2 中位數上下兩半各跑一次。這是登記的診斷,不是新檢定。"""
    known = table[table.w2.notna()]
    cut = known.w2.median()
    print(f"\n控制 W2(中位數 {cut:,.0f} 百萬):")
    for label, half in (
        ("W2 高", known[known.w2 >= cut]),
        ("W2 低", known[known.w2 < cut]),
    ):
        got = compare(label, half, half.depth >= 0)
        if got is not None:
            print(f"  {got.line()}")


def main() -> int:
    """4 個檢定、BH、五分位與 Spearman、look-ahead 檢查、W2 分層。"""
    cli.no_args(__doc__)
    table, prices = load()
    print(
        f"第二次處置、有前一次可比、報酬算得出來:{len(table)} 筆;"
        f"重疊(深度 ≥ 0){int((table.depth >= 0).sum())} 筆\n"
    )
    registered(table)
    dose(table)
    lookahead(table, prices)
    by_w2(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
