"""可轉債條款研究的量測與檢定(#26,第五輪定稿、第六輪改 H2 分母、第七輪定樣本外)。

事前登記的 7 個檢定:

| 假設 | 錨點 | 分組 | 窗口(交易日) |
|---|---|---|---|
| H1 賣回日前的護盤 | 最近賣回權起日 = T | moneyness 價外 vs 價內 | 進 −10 / −5,出 −1 |
| H2 賣回壓力的規模 | 同上 | 發行餘額 ÷ 成交金額 中位數上下 | 進 −10 / −5,出 −1 |
| H3 轉換期開始的套利賣壓 | 轉換起日 | 有無轉換期開始 | 進 +1,出 +5 / +10 / +20 |

一次 Benjamini-Hochberg 校正,跑完不准補測。

量測一律取**進場日**,不是 T 日 —— 轉換價會在期間內重設,用 T 日的值是未來資訊:

* moneyness = 進場日(或之前最近一天)的收盤 ÷ 進場日實際有效的轉換價格。
  收盤用**原始**價,因為轉換價本身就是原始價的尺度(除權息會反稀釋調整轉換價)。
  事件組 = 價外(< 1)。
* 壓力 = 進場日看得到的那份看板上的「上月底發行餘額」÷ 進場日前 20 個交易日
  (不含當天)的成交金額中位數(第六輪:市值算不出來,改成「這筆賣回要用幾天
  的成交金額才吃得下」)。事件組 = 高於中位數的那一半,中位數取受測樣本自己的。

報酬走 [#22] 的框架:`resolve_window` 擋掉進場不晚於 knowable 的、
`window_excess` 扣成本、漲跌停順延(#58)、還原除權息(#59),基準是全宇集
同窗口的等權買進持有。同一檔重疊的窗口只留一筆(`study.pooled`)。

幾個框架沒有直接給、這裡要自己決定的地方(都在跑之前寫死):

* **去期間化按「進場月份」**,不按事件原點。`study.compare_groups` 用事件的
  happened 當期間,但賣回日幾乎每一天都只有一兩檔 —— 單筆的期間扣掉自己的
  中位數就是 0,整組會被抹平。按月去期間化保留「同一段行情裡,價外 vs 價內」
  的比較。H1/H2 進 BH 的是去期間化後的 Mann-Whitney p。
* **H3 是單樣本檢定**。「有無轉換期開始」的「無」就是基準 —— 同窗口全宇集的
  等權報酬 —— 所以檢定的是超額報酬的中心是不是 0(`study.one_sample`,
  Wilcoxon 雙尾)。
* **同期相關照 [#18] 的定義**:分組依據與**量測它的那一段**(進場前 20 個交易日)
  的超額報酬的 Spearman r,對照分組依據與持有窗口報酬的 r(領先)。
  同期 p < 0.05 而且 |同期 r| > |領先 r| 就是「價格的鏡像」。
  H3 的錨點是發行時就定好的日曆日,不是由價格導出來的,沒有鏡像的問題。
"""

from __future__ import annotations

import bisect
import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd
from statsmodels.stats.multitest import multipletests

from src.eventstats import (
    MIN_GROUP,
    Observation,
    compare,
    contemporaneous,
    demean_by_period,
    effective_n,
    window_excess,
)
from src.liquidity import daily_value, level
from src.study import ALPHA, Window, one_sample, pooled, resolve_window


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import date

    from src.events.cb import Ledger
    from src.study import Event

#: H1、H2 的兩個窗口(第五輪撤掉 T−20)
H1_WINDOWS = (Window(-10, -1), Window(-5, -1))
#: H3 的三個窗口
H3_WINDOWS = (Window(1, 5), Window(1, 10), Window(1, 20))
#: 事前登記的檢定數
DECLARED = 2 * len(H1_WINDOWS) + len(H3_WINDOWS)
#: 同期報酬:進場前幾個交易日
SAME_PERIOD_DAYS = 20
#: 每個假設預測的方向(事件組減對照組;H3 是超額報酬本身)
PREDICTED = {"H1": +1, "H2": +1, "H3": -1}


def horizon(window: Window) -> int:
    """去重用的持有長度(交易日):報酬區間 (進場, 出場] 有幾天,至少 1。"""
    return max(window.exit - window.entry, 1)


def lead_time(event: Event, days: Sequence[date]) -> int | None:
    """最早可以在原點前幾個交易日進場(進場要嚴格晚於 knowable)。

    負的代表原點那天還看不到。原點在交易日曆之外就是 None。窗口 (−k, …)
    解得出來的條件就是 lead_time ≥ k。
    """
    anchor = bisect.bisect_left(days, event.happened)
    if anchor >= len(days):
        return None
    return anchor - bisect.bisect_right(days, event.knowable)


def traded_value(prices: pd.DataFrame) -> pd.DataFrame:
    """交易日 × 代號的成交金額;上市期間內沒有列的日子補 0。

    長日線(fetch_history)只寫有收盤價的列,沒成交的那天整列不在 —— 直接
    pivot 會變成空值,而 `liquidity.level` 遇到空值就整段算不出來。上市以前
    和下市以後仍然留空,那不是「成交 0 元」。
    """
    value = daily_value(prices)
    listed = value.ffill().notna() & value.bfill().notna()
    return value.where(~listed | value.notna(), 0.0)


def close_on_or_before(series: dict[date, float] | None, day: date) -> float | None:
    """當天或之前最近一個收盤。"""
    if not series:
        return None
    ordered = sorted(series)
    at = bisect.bisect_right(ordered, day)
    return series[ordered[at - 1]] if at else None


def moneyness(
    ledger: Ledger, raw: dict[str, dict[date, float]], event: Event, entry: date
) -> float | None:
    """進場日的收盤 ÷ 進場日實際有效的轉換價格。"""
    price = ledger.conversion_price(str(event.tags["bond"]), entry)
    close = close_on_or_before(raw.get(event.code), entry)
    if price is None or close is None:
        return None
    return close / price


def pressure(
    ledger: Ledger, value: pd.DataFrame, event: Event, entry: date
) -> float | None:
    """進場日看得到的發行餘額 ÷ 進場日前 20 個交易日的成交金額中位數。"""
    row = ledger.as_of(str(event.tags["bond"]), entry)
    if row is None or row.outstanding is None:
        return None
    liquid = level(value, event.code, pd.Timestamp(entry))
    if liquid is None or liquid <= 0:
        return None
    return row.outstanding / liquid


@dataclass(frozen=True)
class Scored:
    """一個事件在一個窗口上的結果。"""

    event: Event
    entry: date
    exit: date
    #: 持有窗口的超額報酬(%,扣成本、漲跌停順延)
    excess: float
    #: 進場前 SAME_PERIOD_DAYS 個交易日的超額報酬(%),同期相關用
    before: float | None


def score(
    events: Sequence[Event],
    days: Sequence[date],
    window: Window,
    closes: dict[str, dict[date, float]],
) -> list[Scored]:
    """每個事件算一次窗口超額報酬。進場不晚於 knowable 的、算不出來的丟掉。"""
    out = []
    for event in events:
        span = resolve_window(event, days, window)
        series = closes.get(event.code)
        if span is None or series is None or span[0] <= event.knowable:
            continue
        excess = window_excess(series, closes, *span)
        if excess is None:
            continue
        at = bisect.bisect_left(days, span[0])
        before = (
            window_excess(
                series,
                closes,
                days[at - SAME_PERIOD_DAYS],
                span[0],
                costs=False,
                defer_limits=False,
            )
            if at >= SAME_PERIOD_DAYS
            else None
        )
        out.append(Scored(event, span[0], span[1], excess, before))
    return out


@dataclass(frozen=True)
class PutGroups:
    """H1、H2 在一個窗口上的分組。量測都取進場日。"""

    #: H1:價外(moneyness < 1)是事件組
    out_of_money: Callable[[Scored], bool | None]
    #: H2:壓力高於中位數是事件組
    high_pressure: Callable[[Scored], bool | None]
    #: moneyness 算得出來的筆數
    priced: int
    #: 壓力算得出來的筆數
    loaded: int
    #: 壓力的中位數(天)
    cut: float


def put_groups(
    scored: Sequence[Scored],
    ledger: Ledger,
    raw: dict[str, dict[date, float]],
    value: pd.DataFrame,
) -> PutGroups:
    """量好每一筆的 moneyness 與壓力,做成兩個分組。

    壓力的中位數取**受測這組樣本自己的**(登記寫的是「中位數上下」)。
    剛好等於中位數的歸低的那一半。
    """
    money = {id(s): moneyness(ledger, raw, s.event, s.entry) for s in scored}
    load = {id(s): pressure(ledger, value, s.event, s.entry) for s in scored}
    known = [v for v in load.values() if v is not None]
    cut = statistics.median(known) if known else 0.0

    def out_of_money(s: Scored) -> bool | None:
        m = money.get(id(s))
        return None if m is None else m < 1

    def high_pressure(s: Scored) -> bool | None:
        v = load.get(id(s))
        return None if v is None else v > cut

    return PutGroups(
        out_of_money=out_of_money,
        high_pressure=high_pressure,
        priced=sum(v is not None for v in money.values()),
        loaded=len(known),
        cut=cut,
    )


@dataclass(frozen=True)
class Result:
    """一個檢定的結果。"""

    name: str
    hypothesis: str
    n_event: int
    #: 單樣本檢定(H3)沒有對照組
    n_control: int | None
    median_event: float
    median_control: float | None
    #: 事件組中位數減對照組中位數;單樣本就是中位數本身
    effect: float
    #: 沒有去期間化的 p(單樣本就是同一個)
    raw_p: float
    #: 進 BH 的 p
    p: float
    #: 事件組落在幾個不同的進場月份
    months: int
    #: 分組依據與進場前 20 日超額報酬的 (Spearman r, p)。H3 不適用
    same_period: tuple[float, float] | None
    #: 分組依據與持有窗口超額報酬的 (Spearman r, p)
    lead: tuple[float, float] | None

    @property
    def mirrors(self) -> bool:
        """同期強而領先弱:這個分組可能只是價格的鏡像([#18])。"""
        if self.same_period is None or self.lead is None:
            return False
        r, p = self.same_period
        return p < ALPHA and abs(r) > abs(self.lead[0])


def _month(items: Sequence[Observation]) -> list[Observation]:
    return [
        Observation(o.code, f"{o.period:%Y-%m}", o.excess, o.is_event) for o in items
    ]


def two_group(
    name: str,
    hypothesis: str,
    scored: Sequence[Scored],
    side: Callable[[Scored], bool | None],
    span: int,
    days: Sequence[date],
) -> Result | None:
    """事件組 vs 對照組。同一檔重疊的窗口先篩掉,再按進場月份去期間化。"""
    sides = {id(s): side(s) for s in scored}
    observations = [
        Observation(s.event.code, s.entry, s.excess, flag)
        for s in scored
        if (flag := sides[id(s)]) is not None
    ]
    events, controls = pooled(observations, span, days)
    kept = {(o.code, o.period) for o in [*events, *controls]}
    raw = compare(
        name, [o.excess for o in events], [o.excess for o in controls], deduped=True
    )
    centred = demean_by_period(_month([*events, *controls]))
    demeaned = compare(
        name,
        [o.excess for o in centred if o.is_event],
        [o.excess for o in centred if not o.is_event],
        deduped=True,
    )
    if raw is None or demeaned is None:
        return None
    used = [
        s
        for s in scored
        if sides[id(s)] is not None and (s.event.code, s.entry) in kept
    ]
    flags = [1.0 if sides[id(s)] else 0.0 for s in used]
    paired = [
        (f, s.before) for f, s in zip(flags, used, strict=True) if s.before is not None
    ]
    return Result(
        name=name,
        hypothesis=hypothesis,
        n_event=raw.n_event,
        n_control=raw.n_control,
        median_event=raw.median_event,
        median_control=raw.median_control,
        effect=raw.median_event - raw.median_control,
        raw_p=raw.pvalue,
        p=demeaned.pvalue,
        months=effective_n(_month(events)),
        same_period=contemporaneous([f for f, _ in paired], [b for _, b in paired]),
        lead=contemporaneous(flags, [s.excess for s in used]),
    )


def one_sample_test(
    name: str,
    hypothesis: str,
    scored: Sequence[Scored],
    span: int,
    days: Sequence[date],
) -> Result | None:
    """超額報酬對 0。同一檔重疊的窗口先篩掉。"""
    observations = [Observation(s.event.code, s.entry, s.excess, True) for s in scored]
    kept, _ = pooled(observations, span, days)
    if len(kept) < MIN_GROUP:
        return None
    centre, p = one_sample([o.excess for o in kept])
    return Result(
        name=name,
        hypothesis=hypothesis,
        n_event=len(kept),
        n_control=None,
        median_event=centre,
        median_control=None,
        effect=centre,
        raw_p=p,
        p=p,
        months=effective_n(_month(kept)),
        same_period=None,
        lead=None,
    )


def adjusted(results: Sequence[Result]) -> list[float]:
    """整組一次 Benjamini-Hochberg。"""
    if not results:
        return []
    return [float(p) for p in multipletests([r.p for r in results], method="fdr_bh")[1]]


def verdict(
    results: Sequence[Result], corrected: Sequence[float]
) -> tuple[str, list[str]]:
    """照第五輪事前寫的判定標準。

    * 任一檢定校正後 p < 0.05 且同期 r 顯示它不是價格的鏡像 → 找到了
    * 全部不顯著,但同一個假設的方向在各窗口一致 → 線索
    * 全部不顯著且方向不一致 → 收掉

    回傳 (判定, 找到的檢定名或成為線索的假設)。顯著的全都是鏡像時,三條都不
    符合,照實回報而不是硬歸一類。
    """
    significant = [r for r, p in zip(results, corrected, strict=True) if p < ALPHA]
    found = [r.name for r in significant if not r.mirrors]
    if found:
        return "找到了", found
    if significant:
        return "顯著但全是價格的鏡像(不符合任何一條)", [r.name for r in significant]
    by_hypothesis: dict[str, set[int]] = {}
    for r in results:
        by_hypothesis.setdefault(r.hypothesis, set()).add(
            (r.effect > 0) - (r.effect < 0)
        )
    leads = [
        h for h, signs in by_hypothesis.items() if len(signs) == 1 and 0 not in signs
    ]
    if leads:
        return "線索", leads
    return "收掉", []


def _r(pair: tuple[float, float] | None) -> str:
    return "不適用" if pair is None else f"{pair[0]:+.3f} (p={pair[1]:.3f})"


def table(results: Sequence[Result], corrected: Sequence[float]) -> str:
    """結果表:n、中位數、效果、原始 p、進 BH 的 p、校正後 p、同期與領先 r。"""
    head = (
        f"{'檢定':22}{'n事件':>6}{'n對照':>6}{'月':>5}{'事件中位':>9}{'對照中位':>9}"
        f"{'效果':>8}{'原始p':>8}{'檢定p':>8}{'BH p':>8}  同期 r / 領先 r"
    )
    lines = [head]
    for r, p in zip(results, corrected, strict=True):
        control = "—" if r.n_control is None else str(r.n_control)
        median_control = "—" if r.median_control is None else f"{r.median_control:+.2f}"
        mark = " <-" if p < ALPHA else ""
        mirror = " ⚠️鏡像" if r.mirrors else ""
        lines.append(
            f"{r.name:22}{r.n_event:>6}{control:>6}{r.months:>5}"
            f"{r.median_event:>+9.2f}{median_control:>9}{r.effect:>+8.2f}"
            f"{r.raw_p:>8.3f}{r.p:>8.3f}{p:>8.3f}  {_r(r.same_period)} / {_r(r.lead)}"
            f"{mirror}{mark}"
        )
    return "\n".join(lines)
