"""事件研究共用的報酬與統計。

這些東西在 [#14] / [#18] / [#20] 各自手寫過一次,每次都有機會犯不同的錯。
集中在這裡,並且把踩過的坑做成預設行為:

* 報酬可以扣掉基準(超額報酬)—— [#18] 少了這一步
* 長持有期用不重疊區塊 —— [#20] 把 36 個重疊觀察當成 36 個樣本
* 多重比較校正是 adjust() 的預設,不是選項 —— [#14] 死在這上面
* 同期相關性有專門的函式,提醒每個新指標都要一起報 —— [#18] 的主要教訓
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scipy import stats
from statsmodels.stats.multitest import multipletests

from src.market import ROUND_TRIP_COST_PCT, limit_down, limit_up


if TYPE_CHECKING:
    from collections.abc import Sequence

    from _typeshed import SupportsAllComparisons

#: 一組少於這麼多筆就不做檢定,算出來也沒有意義
MIN_GROUP = 4


#: 浮點誤差的容忍度。價格和漲跌停價都是交易所檔位上的數字
LIMIT_EPS = 1e-6


def non_overlapping(positions: Sequence[int], horizon: int) -> list[int]:
    """從事件位置裡挑出窗口互不重疊的一組,由早到晚貪心選。

    positions 是事件在時間序列上的索引(例如第幾週),horizon 是持有幾期。
    相隔不到 horizon 期的兩個事件,報酬窗口重疊、彼此相關,當成兩個獨立
    樣本會把樣本數虛報好幾倍 —— [#20] 就是這樣把約 3 個獨立區塊講成 36
    個觀察。

    由早到晚貪心,在「最多能選幾個」這件事上是最佳解。
    """
    if horizon < 1:
        msg = "持有期至少是 1"
        raise ValueError(msg)
    kept: list[int] = []
    for pos in sorted(positions):
        if not kept or pos - kept[-1] >= horizon:
            kept.append(pos)
    return kept


@dataclass(frozen=True)
class Comparison:
    """事件組和對照組的比較結果。"""

    name: str
    n_event: int
    n_control: int
    median_event: float
    median_control: float
    win_rate_event: float
    win_rate_control: float
    pvalue: float
    #: 有沒有先做不重疊篩選。長持有期應該是 True
    deduped: bool


def median(values: Sequence[float]) -> float:
    """中位數。偶數筆取中間兩筆的平均。"""
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def compare(
    name: str,
    event: Sequence[float],
    control: Sequence[float],
    *,
    deduped: bool = False,
) -> Comparison | None:
    """兩組報酬的 Mann-Whitney 比較。任一組少於 MIN_GROUP 筆就回 None。

    雙尾:訊號可能往任何方向,事前假設它往哪邊等於偷看結果。
    """
    if len(event) < MIN_GROUP or len(control) < MIN_GROUP:
        return None
    return Comparison(
        name=name,
        n_event=len(event),
        n_control=len(control),
        median_event=median(event),
        median_control=median(control),
        win_rate_event=sum(x > 0 for x in event) / len(event),
        win_rate_control=sum(x > 0 for x in control) / len(control),
        pvalue=float(
            stats.mannwhitneyu(event, control, alternative="two-sided").pvalue
        ),
        deduped=deduped,
    )


def adjust(comparisons: Sequence[Comparison]) -> list[tuple[Comparison, float]]:
    """對整組檢定做 Benjamini-Hochberg 校正,回傳 (比較, 校正後 p)。

    預設行為而不是選項:[#14] 有 10 個檢定、3 個原始 p<0.05,校正後全部
    不顯著。跑一組檢定只看原始 p 值,幾乎保證會找到假訊號。

    只有一個檢定時校正等於沒做,但仍然走同一條路,呼叫端不用分兩種情況。
    """
    if not comparisons:
        return []
    adjusted = multipletests([c.pvalue for c in comparisons], method="fdr_bh")[1]
    return list(zip(comparisons, (float(p) for p in adjusted), strict=True))


def contemporaneous(
    changes: Sequence[float], same_period_returns: Sequence[float]
) -> tuple[float, float]:
    """指標變化和「同一期」報酬的相關性,回傳 (Spearman r, p)。

    每個新指標都要一起報這個。[#18] 的千張大戶人數對同期 r=0.464
    (p=0.001)、對未來 r=0.130 (p=0.390) —— 同期強而領先弱,意思是這個指標
    是價格的鏡像。只看領先那一邊會誤判成「沒訊號」,而真相是「有訊號但不能
    用」,兩者要分清楚。
    """
    result = stats.spearmanr(changes, same_period_returns)
    return float(result.statistic), float(result.pvalue)


# --- 窗口報酬 ---
#
# 這幾個本來寫在 run_dispersion.py 裡。那個檔案被 coverage 排除,所以研究的
# 核心算數完全沒有測試,而覆蓋率門檻照樣過。搬到這裡才測得到。


def first_on_or_after[DayT: SupportsAllComparisons](
    series: dict[DayT, float], day: DayT
) -> tuple[DayT, float] | None:
    """當天或之後最近一個有值的日子。全部都在之前就回 None。"""
    later = sorted(d for d in series if d >= day)
    return (later[0], series[later[0]]) if later else None


def equal_weight_buy_and_hold[DayT: SupportsAllComparisons](
    closes: dict[str, dict[DayT, float]], entry: DayT, exit_: DayT
) -> float | None:
    """一籃子股票在這段窗口內買進持有的等權報酬,百分比。

    用這個而不是把每日等權指數的兩個點相除:每日再平衡的指數是一個每天
    調倉的組合,而個股那一邊是買進持有,兩者不可比。實測在 13 週的窗口上
    差約 1 個百分點,而且方向固定 —— 會讓每一筆超額報酬都偏高。

    只算在窗口兩端都有價格的股票。
    """
    rets = [
        series[exit_] / series[entry] - 1
        for series in closes.values()
        if entry in series and exit_ in series and series[entry] > 0
    ]
    return sum(rets) / len(rets) * 100 if rets else None


@dataclass(frozen=True)
class Observation:
    """一筆事件觀察:哪一檔、哪一期進場、報酬多少、是不是事件組。"""

    code: str
    #: 進場所屬的期間(通常是集保資料週)。去期間化和算有效樣本數都靠它
    period: object
    excess: float
    is_event: bool


def demean_by_period(items: Sequence[Observation]) -> list[Observation]:
    """把每個期間的橫斷面中位數扣掉。

    事件組和對照組各自去重之後,兩組會落在不同的市場期間 —— 實測事件組
    進場日中位數比對照組早兩個月。那個時間差本身就會產生報酬差異,跟訊號
    無關:對大盤的超額報酬擋不住這件事,因為隨期間變的是橫斷面的「離散度」
    (平均與中位數的差),不是指數的水位。

    扣掉之後,比較的才是「同一週裡,有訊號的股票 vs 沒訊號的股票」。
    """
    by_period: dict[object, list[float]] = {}
    for item in items:
        by_period.setdefault(item.period, []).append(item.excess)
    centre = {period: median(vals) for period, vals in by_period.items()}
    return [
        Observation(
            code=item.code,
            period=item.period,
            excess=item.excess - centre[item.period],
            is_event=item.is_event,
        )
        for item in items
    ]


def effective_n(items: Sequence[Observation]) -> int:
    """有幾個不同的期間。

    這比觀察筆數更接近獨立樣本數:20 檔共用同一組集保週次,同一週裡的
    股票一起漲跌,所以 14 筆來自同一週的觀察不是 14 個獨立樣本。
    """
    return len({item.period for item in items})


def tradable_on_or_after[DayT: SupportsAllComparisons](
    series: dict[DayT, float], day: DayT, *, buying: bool
) -> tuple[DayT, float] | None:
    """當天或之後,第一個成交得了的日子與收盤價(#58)。

    買進:收盤在漲停就買不到,順延到下一個有價格的日子;賣出:收盤在跌停就
    賣不掉,一樣順延(Jordan 2026-10-07)。漲跌停用前一個有價格日子的收盤算 ——
    停牌好幾天的話那是停牌前的收盤,跟交易所的參考價一樣。
    """
    ordered = sorted(series)
    for i, d in enumerate(ordered):
        if d < day:
            continue
        price = series[d]
        prev = series[ordered[i - 1]] if i > 0 else None
        if prev is not None and prev > 0:
            if buying and price >= limit_up(prev) - LIMIT_EPS:
                continue
            if not buying and price <= limit_down(prev) + LIMIT_EPS:
                continue
        return d, price
    return None


def window_excess[DayT: SupportsAllComparisons](
    series: dict[DayT, float],
    closes: dict[str, dict[DayT, float]],
    entry_day: DayT,
    exit_day: DayT,
    *,
    costs: bool = True,
    defer_limits: bool = True,
) -> float | None:
    """一個窗口的超額報酬。兩端任一邊找不到價格就回 None。

    entry_day / exit_day 是「不早於這一天」—— 實際進出場是當天或之後最近的
    交易日。基準是同一個窗口內整個宇集的買進持有等權報酬,用的是**實際**
    進出場那兩天。

    defer_limits:進場那天收漲停就順延、出場那天收跌停也順延(#58)。順延到
    出場日還買不到,或一路跌停到資料結束,就回 None —— 那筆成交不了,不是
    報酬為 0。釘住舊數字的重現測試才關掉它。
    """
    if defer_limits:
        entry = tradable_on_or_after(series, entry_day, buying=True)
        out = tradable_on_or_after(series, exit_day, buying=False)
    else:
        entry = first_on_or_after(series, entry_day)
        out = first_on_or_after(series, exit_day)
    # 進場日要早於原定出場日,否則這一筆成交不了(None),不是 0%:漲停一路順延過頭,
    # 或者那一天還沒上市(順延會把進出場都推到上市第一天,算成 0% 再扣成本 =
    # 剛好 −0.585%;可轉債的安慰劑有 13.7% 是這種假的觀察值,#62 抓到的)
    if entry is None or out is None or entry[1] <= 0 or entry[0] >= exit_day:
        return None
    bench = equal_weight_buy_and_hold(closes, entry[0], out[0])
    if bench is None:
        return None
    stock = (out[1] / entry[1] - 1) * 100
    if costs:
        stock -= ROUND_TRIP_COST_PCT
    return stock - bench


def clustered_ci(
    values: Sequence[float],
    clusters: Sequence[object],
    draws: int = 2000,
    seed: int = 20260101,
) -> tuple[float, float, float]:
    """按群集重抽的中位數信賴區間,回傳 (下界, 上界, 中位數 ≤ 0 的比例)。

    事件會叢聚在同一段行情裡 —— 全市場處置研究的 2,265 個事件只落在約 1,081
    個不同的買進日,最多 20 個共用同一天。同一天的股票一起漲跌,所以
    Wilcoxon 把它們當獨立樣本會把 p 值算得太小。

    重抽的單位是**群集**(通常是月),不是單筆觀察,這樣才保留群集內的相關性。
    回傳的第三個值是「有多少比例的重抽中位數不為正」,那比一個小 p 值誠實。

    seed 固定:研究要能重現,而 Math.random 式的不可重現在這裡是缺陷不是特性。
    """
    grouped: dict[object, list[float]] = {}
    for value, key in zip(values, clusters, strict=True):
        grouped.setdefault(key, []).append(value)
    keys = list(grouped)
    if len(keys) < MIN_CLUSTERS:
        return (0.0, 0.0, 1.0)
    # S311:拔靴重抽不是密碼學用途,而且要可重現
    rng = random.Random(seed)  # noqa: S311
    medians: list[float] = []
    for _ in range(draws):
        pooled: list[float] = []
        for _ in keys:
            pooled.extend(grouped[keys[rng.randrange(len(keys))]])
        medians.append(median(pooled))
    medians.sort()
    low = medians[int(0.025 * len(medians))]
    high = medians[int(0.975 * len(medians))]
    nonpositive = sum(1 for m in medians if m <= 0) / len(medians)
    return (low, high, nonpositive)


#: 少於這麼多個群集就不做拔靴,重抽的變異會大到沒有意義
MIN_CLUSTERS = 8
