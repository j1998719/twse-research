"""停損 / 停利有沒有幫助?跑 #15 事前登記的六組。

頭條樣本(t−6 收盤買、t−1 收盤賣、漲跌停順延)上,每一筆分別套上
停損 5% / 8% / 10%、停利 10% / 15% / 20%:收盤觸發、隔天收盤賣。

判定(事前登記):期望值比基準高,而且「規則 − 基準」逐筆成對差的
Wilcoxon signed-rank 在六組一起 BH 校正後 p < 0.05,才算有幫助。

用法:.venv/bin/python -m src.run_exits
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from src import cli
from src.disposition_study import exit_rule, pre_release_run, win_loss
from src.market import index_series
from src.universe import all_actions, all_prices, all_punishes


RAW = Path("data/raw")
#: 事前登記的六組:(名稱, 停損, 停利)
RULES: list[tuple[str, float | None, float | None]] = [
    ("停損 5%", 0.05, None),
    ("停損 8%", 0.08, None),
    ("停損 10%", 0.10, None),
    ("停利 10%", None, 0.10),
    ("停利 15%", None, 0.15),
    ("停利 20%", None, 0.20),
]
ALPHA = 0.05


def _row(label: str, excess: pd.Series, triggered: int | None) -> str:
    wl = win_loss(excess.to_frame("x"), "x")
    hit = "" if triggered is None else f"{triggered:>5}"
    return (
        f"{label:<10}{hit:>6}  期望值 {wl['期望值%']:+6.2f}%  中位數 {excess.median():+6.2f}%"
        f"  勝率 {wl['勝率%']:5.1f}%  賺賠比 {wl['賺賠比']:5.2f}  最差 {excess.min():+7.2f}%"
    )


def main() -> int:
    """跑六組,印出描述統計和成對檢定。"""
    cli.no_args(__doc__)
    prices = all_prices()
    punishes = all_punishes()
    index = index_series(RAW / "prices")
    numbered = punishes[punishes.nth > 0]
    actions = all_actions()
    raw = pre_release_run(
        numbered, prices, index, all_punishes=punishes, actions=actions
    )
    runs = raw[raw.knowable & raw.truly_released & raw.excess.notna()]
    base = runs.excess.astype(float)
    print(f"頭條樣本 {len(runs)} 筆(t−6 收盤買、t−1 收盤賣、漲跌停順延)\n")
    print(f"{'':<10}{'觸發':>6}")
    print(_row("基準", base, None))

    results = []
    for label, stop, take in RULES:
        out = exit_rule(runs, prices, index, stop=stop, take=take, actions=actions)
        both = pd.concat(
            [base, out.excess.astype(float)], axis=1, keys=["b", "r"]
        ).dropna()
        diff = both.r - both.b
        # 沒觸發的那幾筆差是 0;signed-rank 用 zsplit 把零差平分兩邊,不丟掉
        p = float(stats.wilcoxon(diff, zero_method="zsplit").pvalue)
        results.append((label, both.r, int(out.triggered.sum()), diff.mean(), p))
        print(_row(label, both.r, int(out.triggered.sum())))

    adjusted = multipletests([r[4] for r in results], method="fdr_bh")[1]
    print("\n成對差(規則 − 基準),六組一起 BH 校正")
    base_ev = win_loss(base.to_frame("x"), "x")["期望值%"]
    for (label, values, _, mean_diff, p), q in zip(results, adjusted, strict=True):
        ev = win_loss(values.to_frame("x"), "x")["期望值%"]
        helps = ev > base_ev and q < ALPHA
        print(
            f"  {label:<10} 平均差 {mean_diff:+6.3f} 個百分點  原始 p={p:.4f}  校正 p={q:.4f}"
            f"  → {'有幫助' if helps else '沒有幫助'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
