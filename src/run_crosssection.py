"""大戶指標的橫斷面研究:每週把全市場排序,看排前面的下一週有沒有比較強(#25)。

兩個指標:X1 = 1000 張以上佔比的週變化、X2 = 400 張以上佔比的週變化(百分點)。
集保資料日期 + 5 天當 knowable(同 #19),之後第一個交易日收盤進場、持有 5 個
交易日;報酬是 #22 框架的超額(扣成本、扣等權宇集、漲跌停順延、還原除權息);
流動性門檻 20 日成交金額中位數 ≥ 1,000 萬元。

每週算排序相關 IC(Spearman)和十分位最高 − 最低。⚠️ 事前登記:現在的 7 週是
先導,只描述;正式檢定等之後新累積的 26 週。

用法:.venv/bin/python -m src.run_crosssection
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path

import pandas as pd
from scipy import stats

from src import cli
from src.disposition_study import trading_days
from src.fetch_tdcc import ARCHIVE
from src.liquidity import MILLION, daily_value, level
from src.run_chip_signals import Excess
from src.run_wholemarket import closes_by_code
from src.universe import all_actions, all_prices
from src.weekly import Week, load_weeks


WEEKS_DIR = Path("data/raw/tdcc_weeks")
#: 集保資料日期到可以交易之間的時滯(同 #19 的 events/dispersion.py)
PUBLISH_LAG = timedelta(days=5)
HOLD = 5
MIN_VALUE = 10
#: 指標:名稱 → 從第幾級(索引)往上加總
INDICATORS = {"X1 千張以上週變化": 14, "X2 400 張以上週變化": 11}
DECILES = 10
#: 每週最少幾檔才算 IC
MIN_STOCKS = 100


def weekly_changes(
    weeks: dict[date, dict[str, Week]], level: int
) -> dict[date, dict[str, float]]:
    """每一週(有上一週可比的)每檔的佔比變化:從 level 那一級往上加總,新減舊。"""
    ordered = sorted(weeks)
    out: dict[date, dict[str, float]] = {}
    for prev, now in pairwise(ordered):
        out[now] = {
            code: round(sum(week[0][level:]) - sum(weeks[prev][code][0][level:]), 4)
            for code, week in weeks[now].items()
            if code in weeks[prev]
        }
    return out


def entry_after(data_day: date, days: pd.DatetimeIndex) -> pd.Timestamp | None:
    """Knowable(資料日期 + 5 天)之後的第一個交易日。超過資料範圍回 None。"""
    knowable = pd.Timestamp(data_day + PUBLISH_LAG)
    later = days[days > knowable]
    return later[0] if len(later) else None


def main() -> int:
    """每週 IC 與十分位,兩個指標;最後印平均 IC 和 t 值(先導,只描述)。"""
    cli.no_args(__doc__)
    prices = all_prices()
    days = trading_days(prices)
    excess = Excess(closes_by_code(prices, all_actions()))
    value = daily_value(prices)
    _, weeks = load_weeks(ARCHIVE, WEEKS_DIR, max_weeks=60)
    print(f"週資料 {len(weeks)} 週:{min(weeks)} ~ {max(weeks)}\n")

    for name, lv in INDICATORS.items():
        print(name)
        ics = []
        for week, changes in sorted(weekly_changes(weeks, lv).items()):
            start = entry_after(week, days)
            if start is None:
                continue
            at = int(days.searchsorted(start))
            if at + HOLD >= len(days):
                print(f"  {week}:下一週的報酬還不完整,跳過")
                continue
            end = days[at + HOLD]
            rows = []
            for code, x in changes.items():
                liquid = level(value, code, start)
                if liquid is None or liquid < MIN_VALUE * MILLION:
                    continue
                got = excess(code, start.date(), end.date())
                if got is not None:
                    rows.append((x, got))
            if len(rows) < MIN_STOCKS:
                continue
            frame = pd.DataFrame(rows, columns=["x", "r"])
            ic = float(stats.spearmanr(frame.x, frame.r)[0])
            frame["d"] = pd.qcut(frame.x.rank(method="first"), DECILES, labels=False)
            spread = (
                frame.r[frame.d == DECILES - 1].median()
                - frame.r[frame.d == 0].median()
            )
            ics.append(ic)
            print(
                f"  {week} → 進場 {start.date()}:n={len(frame)} IC {ic:+.3f}  十分位高−低 {spread:+.2f}pp"
            )
        if len(ics) > 1:
            mean = statistics.mean(ics)
            t = mean / (statistics.stdev(ics) / len(ics) ** 0.5)
            print(
                f"  平均 IC {mean:+.3f}(t = {t:+.2f},{len(ics)} 週)—— 先導,只描述,不判定\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
