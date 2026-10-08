"""依處置條件、觸發的注意款次拆開看主策略報酬:跑 #9 事前登記的 4 個檢定。

報酬 = 主策略(出關前 6 日收盤買、前 1 日收盤賣),#22 框架,跟 #30 / #31 同一份
(run_chain_liquidity.numbered_dispositions)。只看舊制(10 個營業日)的編號處置。

- K1:條件含「沖銷標準」vs 不含(上市 + 上櫃)
- K2:連續 3 次 / 連續 5 次 / 10 日 6 次,不含沖銷(上市 + 上櫃,Kruskal-Wallis)
- K3:觸發的注意公告裡有第 6 款(估值)vs 沒有(只有上市:注意股資料只有上市)
- K4:觸發的注意以「籌碼」款為主 vs 以「價格動能」款為主(只有上市)
形成期 ~2023-12 一次 BH;通過的才在 2024-01 之後驗證(單一檢定、不再校正)。
處置天數幾乎完全由沖銷標準決定(12 vs 10 天),所以「天數」就是 K1。

用法:.venv/bin/python -m src.run_condition_split
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from src import cli
from src.clauses import classify, window_for
from src.disposition_study import trading_days
from src.run_chain_liquidity import numbered_dispositions
from src.run_new_regime import NEW_RULES
from src.universe import all_prices, all_punishes


if TYPE_CHECKING:
    from collections.abc import Callable

NOTICES = "data/out/notices.csv"
FORMATION_END = pd.Timestamp("2023-12-31")
#: K2 比的三種條件(回看窗口);30 日 12 次太少不放
K2_WINDOWS = (3, 5, 10)
VALUATION = 6
ALPHA = 0.05


def day_trading(condition: str) -> bool:
    """條件有沒有附加「沖銷標準」(上市寫「當日沖銷標準」、上櫃寫「沖銷標準」)。"""
    return "沖銷" in condition


def with_clauses(
    table: pd.DataFrame, punishes: pd.DataFrame, days: pd.DatetimeIndex
) -> pd.DataFrame:
    """上市的列加上觸發的款次(clauses)與主要的組(family);上櫃是 None。"""
    notices = pd.read_csv(NOTICES, dtype={"code": str}, parse_dates=["day"])
    listed = punishes[(punishes.market == "twse") & (punishes.nth > 0)]
    found = classify(listed, notices, days)
    key = {
        (str(c), pd.Timestamp(s)): (cl, fam, n)
        for c, s, cl, fam, n in zip(
            found.code,
            found.start,
            found.clauses,
            found.family,
            found.notice_count,
            strict=True,
        )
    }
    got = [key.get((c, s)) for c, s in zip(table.code, table.start, strict=True)]
    # 找不到觸發的注意(資料從 2020 起)就當作不知道,不當作「沒有第 6 款」
    return table.assign(
        clauses=pd.Series(
            [g[0] if g and g[2] else None for g in got], index=table.index, dtype=object
        ),
        family=pd.Series(
            [g[1] if g and g[2] else None for g in got], index=table.index, dtype=object
        ),
    )


def k1(t: pd.DataFrame) -> tuple[str, float]:
    """含沖銷 vs 不含。"""
    a, b = t.new[t.dt], t.new[~t.dt]
    p = float(stats.mannwhitneyu(a, b, alternative="two-sided").pvalue)
    return _two("含沖銷", a, "不含", b), p


def k2(t: pd.DataFrame) -> tuple[str, float]:
    """三種條件(不含沖銷)。"""
    plain = t[~t.dt]
    groups = [plain.new[plain.window == w] for w in K2_WINDOWS]
    p = float(stats.kruskal(*groups).pvalue)
    text = "  ".join(
        f"{w} 日窗口 n={len(g)} 中位數 {g.median():+.2f}%"
        for w, g in zip(K2_WINDOWS, groups, strict=True)
    )
    return text, p


def k3(t: pd.DataFrame) -> tuple[str, float]:
    """有第 6 款 vs 沒有(只有找得到觸發注意的上市列)。"""
    known = t[t.clauses.notna()]
    has = known.clauses.map(lambda c: VALUATION in c)
    a, b = known.new[has], known.new[~has]
    p = float(stats.mannwhitneyu(a, b, alternative="two-sided").pvalue)
    return _two("有第 6 款", a, "沒有", b), p


def k4(t: pd.DataFrame) -> tuple[str, float]:
    """以籌碼款為主 vs 以價格動能款為主。"""
    a, b = t.new[t.family == "籌碼"], t.new[t.family == "價格動能"]
    p = float(stats.mannwhitneyu(a, b, alternative="two-sided").pvalue)
    return _two("籌碼為主", a, "價格動能為主", b), p


def _two(name_a: str, a: pd.Series, name_b: str, b: pd.Series) -> str:
    return (
        f"{name_a} n={len(a)} 中位數 {a.median():+.2f}%  vs  {name_b} n={len(b)}"
        f" 中位數 {b.median():+.2f}%  差 {a.median() - b.median():+.2f}"
    )


TESTS: tuple[tuple[str, Callable[[pd.DataFrame], tuple[str, float]]], ...] = (
    ("K1", k1),
    ("K2", k2),
    ("K3", k3),
    ("K4", k4),
)


def load() -> pd.DataFrame:
    """舊制編號處置的主策略報酬,帶條件、窗口、款次。"""
    prices = all_prices()
    punishes = all_punishes()
    days = trading_days(prices)
    table = numbered_dispositions(prices, punishes, (1, 2))
    table = table[table.new.notna() & (table.start < NEW_RULES)]
    table = table.assign(
        dt=table.condition.map(day_trading),
        window=table.condition.map(window_for),
    )
    return with_clauses(table, punishes, days)


def main() -> int:
    """形成期 4 個檢定一次 BH;通過的在樣本外各跑一次。"""
    cli.no_args(__doc__)
    table = load()
    formation = table[table.entry <= FORMATION_END.date()]
    later = table[table.entry > FORMATION_END.date()]
    print(
        f"舊制編號處置:{len(table)} 筆(形成期 {len(formation)}、樣本外 {len(later)})\n"
    )
    results = [(name, *test(formation)) for name, test in TESTS]
    adjusted = multipletests([p for _, _, p in results], method="fdr_bh")[1]
    print("形成期,4 個檢定一次 BH:")
    for (name, text, p), q in zip(results, adjusted, strict=True):
        print(f"{name}  {text}  原始 p={p:.4f}  BH p={q:.4f}")
    winners = [
        (name, test)
        for (name, test), q in zip(TESTS, adjusted, strict=True)
        if q < ALPHA
    ]
    if not winners:
        print("\n沒有任何一個通過。")
        return 0
    print("\n樣本外(2024-01 ~ 新制前,單一檢定、不再校正):")
    for name, test in winners:
        text, p = test(later)
        print(f"{name}  {text}  p={p:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
