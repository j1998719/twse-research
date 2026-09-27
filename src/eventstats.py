"""事件研究共用的報酬與統計。

這些東西在 [#14] / [#18] / [#20] 各自手寫過一次,每次都有機會犯不同的錯。
集中在這裡,並且把踩過的坑做成預設行為:

* 報酬可以扣掉基準(超額報酬)—— [#18] 少了這一步
* 長持有期用不重疊區塊 —— [#20] 把 36 個重疊觀察當成 36 個樣本
* 多重比較校正是 adjust() 的預設,不是選項 —— [#14] 死在這上面
* 同期相關性有專門的函式,提醒每個新指標都要一起報 —— [#18] 的主要教訓
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from scipy import stats
from statsmodels.stats.multitest import multipletests

from src.market import ROUND_TRIP_COST_PCT


if TYPE_CHECKING:
    from collections.abc import Sequence

    from _typeshed import SupportsAllComparisons, SupportsRichComparison

#: 一組少於這麼多筆就不做檢定,算出來也沒有意義
MIN_GROUP = 4


def equal_weight_index[DayT: SupportsRichComparison](
    closes: dict[str, dict[DayT, float]],
) -> dict[DayT, float]:
    """用一籃子股票的等權報酬做基準指數,起點 100。

    等權而不是市值加權:市值加權會被少數大型股主導,而事件樣本多半是中小型
    股,拿大型股當基準比不出東西。

    每天只用「當天和前一天都有價格」的股票算報酬 —— 停牌或還沒上市的不能
    當成零報酬,那會把指數往下拉。
    """
    days = sorted({day for series in closes.values() for day in series})
    level = 100.0
    out: dict[DayT, float] = {}
    prev: DayT | None = None
    for day in days:
        if prev is not None:
            rets = [
                series[day] / series[prev] - 1
                for series in closes.values()
                if day in series and prev in series and series[prev] > 0
            ]
            if rets:
                level *= 1 + sum(rets) / len(rets)
        out[day] = level
        prev = day
    return out


def excess_return(
    entry: float,
    exit_: float,
    bench_entry: float,
    bench_exit: float,
    *,
    costs: bool = True,
) -> float:
    """對基準的超額報酬,百分比。

    成本只扣在個股那一邊 —— 基準是不用交易的參考線,不是一個要付手續費的
    部位。
    """
    if entry <= 0 or bench_entry <= 0:
        msg = "進場價和基準起點都必須大於零"
        raise ValueError(msg)
    stock = (exit_ / entry - 1) * 100
    bench = (bench_exit / bench_entry - 1) * 100
    if costs:
        stock -= ROUND_TRIP_COST_PCT
    return stock - bench


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
