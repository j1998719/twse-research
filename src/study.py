"""事件研究框架:讓踩過的坑寫不出來。

處置股([#13])、大戶籌碼([#18]–[#21])、以及下一個題目都走這裡。

這個模組的目的不是提供功能,是**讓錯誤寫不出來**。每一道守衛都對應一個
實際踩過的坑:

* `Event.knowable` **必填且無預設**,而 `resolve_window` 會擋掉進場早於它的
  窗口 —— [#13] 有 29/31 筆新制事件的進場點落在公告當天。算報酬一定要先
  拿到窗口,所以這道檢查繞不過去。
* `Spec` 是 `run_study` 的輸入,而且檢定清單是 frozen 的 tuple。跑完才想加
  檢定,就得改 Spec 並重跑整組 —— 校正的家族大小會跟著變。[#14] 有 10 個
  檢定、3 個原始 p<0.05,校正後全滅。
* 校正由 `run_study` 自己做,不是選項。
* 同期相關性是 `Finding` 的必填欄位,不是選項 —— 沒有它就組不出結果。
* 重疊窗口自動篩掉並回報獨立樣本數 —— [#20] 把 36 個重疊觀察當成 36 個樣本。
* 期間叢聚自動去除並兩種都報 —— [#19] 的 review 抓到事件組和對照組落在
  差兩個月的不同期間。
* 涵蓋率跟結果一起輸出,低於門檻標示為先導測試 —— [#23] 目前只涵蓋 37%
  的普通股,不能讓 20 檔的結果印出來長得像全市場研究。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

from scipy import stats

from src.eventstats import (
    Comparison,
    Observation,
    adjust,
    compare,
    contemporaneous,
    demean_by_period,
    effective_n,
    median,
    non_overlapping,
    window_excess,
)


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import date

#: 涵蓋率低於這個比例就標示為先導測試,不能當全市場研究讀
PILOT_BELOW = 0.5
#: 校正後低於這個才算顯著
ALPHA = 0.05


@dataclass(frozen=True)
class Event:
    """一件事情發生在某一檔股票上。

    `happened` 和 `knowable` 分開是這個框架的核心:前者是事件對齊的原點,
    後者是**資訊公開的那一天**。進場必須嚴格晚於它:公告多半盤後發布,
    在公告日收盤買進就是偷看未來。

    兩者的先後沒有限制,而且兩種都常見:

    * **資料發布型**:集保的資料日期是 happened,再加約 5 天才公布 ——
      `knowable > happened`。
    * **預定事件型**:處置的出關日是 happened,但處置公告在**兩週前**就
      發出了 —— `knowable < happened`。出關日是事先知道的。

    所以守衛不在這裡。真正要擋的是「**進場日不能早於 knowable**」,那由
    `resolve_window` 負責 —— 拿不到窗口就沒辦法算報酬。

    knowable 沒有預設值。忘記給是 TypeError,不會安靜地變成偷看未來。
    """

    code: str
    happened: date
    knowable: date
    #: 分組用的任意欄位:處置次數、觸發款次、指標變化方向…
    tags: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Window:
    """相對事件原點的持有窗口,單位是交易日。

    負數是原點之前。處置股的主要發現是 (-6, -1):出關前六個交易日買進、
    出關前一日賣出。
    """

    entry: int
    exit: int

    def __post_init__(self) -> None:
        """出場不能在進場之前。"""
        if self.exit < self.entry:
            msg = f"出場偏移 {self.exit} 在進場偏移 {self.entry} 之前"
            raise ValueError(msg)


def resolve_window(
    event: Event, days: Sequence[date], window: Window
) -> tuple[date, date] | None:
    """把窗口換成實際的兩個交易日。**進場早於 knowable 就回 None。**

    這是 [#13] 那個偷看未來的結構性解法:算報酬一定要先拿到窗口,而拿窗口
    一定會經過這個檢查。[#13] 原本有 29/31 筆新制事件的進場點落在公告當天
    —— 那等於在公告還沒出來時就知道它會被處置。

    days 要由小到大排好。原點不在交易日上時,用當天或之後最近的那一天。
    """
    anchor = _index_at_or_after(days, event.happened)
    if anchor is None:
        return None
    entry_at = anchor + window.entry
    exit_at = anchor + window.exit
    if entry_at < 0 or exit_at >= len(days):
        return None
    entry, exit_ = days[entry_at], days[exit_at]
    # 嚴格晚於,不是「不早於」。knowable 是**資訊公開的那一天**,而公告多半
    # 是盤後發布 —— 在公告日收盤買進等於在公告出來前就知道它會發生。
    # backtest.pre_release_run 用的也是嚴格不等式(buy_day > announced),
    # 兩邊的語意必須一致。
    if entry <= event.knowable:
        return None
    return entry, exit_


def _index_at_or_after(days: Sequence[date], day: date) -> int | None:
    """當天或之後最近一個交易日的位置。

    原點落在全部資料之前也回 None —— 靜靜地錨到第一天的話,一個比價格資料
    還早好幾年的事件會配到一個看起來很合理、但完全錯誤時期的窗口。
    """
    if not days or day < days[0]:
        return None
    for i, candidate in enumerate(days):
        if candidate >= day:
            return i
    return None


@dataclass(frozen=True)
class Coverage:
    """這次研究實際涵蓋了什麼。跟結果一起輸出,不能只報 p 值。

    不要自己填 —— 用 `Coverage.of()`。四個數字都自己填的話,少報宇集就能
    讓先導警告消失,而那個警告存在的意義就是不讓人把部分樣本當全市場讀。
    """

    codes: int
    universe: int
    events: int
    #: 窗口解得出來的事件數。比 events 少就是有事件被守衛擋掉了
    usable: int
    span: tuple[date, date] | None

    @classmethod
    def of(
        cls,
        events: Sequence[Event],
        usable: Sequence[Event],
        universe: int,
    ) -> Coverage:
        """從事件本身推導。universe 是宇集有幾檔,那個必須由外面給。"""
        span = (
            (min(e.happened for e in usable), max(e.happened for e in usable))
            if usable
            else None
        )
        return cls(
            codes=len({e.code for e in usable}),
            universe=universe,
            events=len(events),
            usable=len(usable),
            span=span,
        )

    @property
    def ratio(self) -> float:
        """涵蓋了宇集的幾分之幾。"""
        return self.codes / self.universe if self.universe else 0.0

    @property
    def pilot(self) -> bool:
        """是先導測試而不是全市場研究。"""
        return self.ratio < PILOT_BELOW

    def describe(self) -> str:
        """一行摘要。先導測試要講出來。"""
        span = f"{self.span[0]}–{self.span[1]}" if self.span else "沒有事件"
        head = (
            f"{self.codes}/{self.universe} 檔({self.ratio:.1%})、"
            f"{self.usable}/{self.events} 個可用事件、{span}"
        )
        if self.pilot:
            return f"{head}\n⚠️ 涵蓋率低於 {PILOT_BELOW:.0%},這是先導測試,不是全市場研究"
        return head


def window_return(
    event: Event,
    days: Sequence[date],
    window: Window,
    closes: dict[str, dict[date, float]],
) -> float | None:
    """一個事件在這個窗口的超額報酬。窗口解不出來就回 None。

    這是框架裡唯一算報酬的入口,而它一定先過 `resolve_window` —— 所以
    look-ahead 的檢查繞不過去。`eventstats.window_excess` 仍然是公開的
    (測試和舊的 runner 要用),但新研究應該走這裡。
    """
    resolved = resolve_window(event, days, window)
    if resolved is None:
        return None
    series = closes.get(event.code)
    if series is None:
        return None
    return window_excess(series, closes, *resolved)


def one_sample(values: Sequence[float]) -> tuple[float, float]:
    """一組報酬對零的檢定,回傳 (中位數, p)。

    Wilcoxon 符號等級檢定,雙尾。問的是「這組報酬的中心是不是 0」,
    用在沒有自然對照組的研究(例如處置股:所有處置事件都是事件,
    沒有「沒被處置」的對照)。
    """
    cleaned = [v for v in values if v == v]  # noqa: PLR0124 - 濾掉 NaN
    if len(cleaned) < MIN_ONE_SAMPLE or not any(cleaned):
        # 全部是零時 scipy 會除以零並發警告,而答案本來就是「沒有差異」
        return (0.0, 1.0)
    # zsplit 把零值平分到兩側,而不是丟掉。scipy 預設的 wilcox 會丟掉它們,
    # 讓有效樣本數悄悄變小、p 值被推大 —— 報酬四捨五入到兩位小數之後,
    # 剛好是零的筆數不見得少。
    result = stats.wilcoxon(cleaned, alternative="two-sided", zero_method="zsplit")
    return median(cleaned), float(result.pvalue)


#: 少於這麼多筆就不做單樣本檢定
MIN_ONE_SAMPLE = 6


def pooled(
    observations: Sequence[Observation],
    horizon: int,
    periods: Sequence[object],
) -> tuple[list[Observation], list[Observation]]:
    """把觀察分成事件組和對照組,各自篩掉重疊窗口。

    periods 是這次研究的**時間尺標** —— 由早到晚排好的所有期間(例如集保的
    51 個週次,或所有交易日)。重疊是時間上的概念,所以距離一定要在這個尺標
    上量,不能用觀察在清單裡的位置:兩筆相隔四年的事件如果剛好是相鄰兩筆,
    用位置量會被當成重疊而砍掉一筆。

    分組之後才篩重疊,而且兩組各自篩 —— 這正是 [#19] 的 review 抓到會造成
    期間錯配的地方。框架不假裝避開它(避不掉,兩組本來就在不同時間),而是
    讓 `compare_groups` 一定同時算去期間化的版本。
    """
    ordinal = {period: i for i, period in enumerate(periods)}
    events = [o for o in observations if o.is_event]
    controls = [o for o in observations if not o.is_event]
    return _dedup(events, horizon, ordinal), _dedup(controls, horizon, ordinal)


def _dedup(
    items: Sequence[Observation], horizon: int, ordinal: dict[object, int]
) -> list[Observation]:
    """同一檔之內篩掉重疊窗口。不同檔之間不會互相重疊。

    期間不在尺標上的觀察直接丟掉 —— 留著就得猜它的時間位置,而猜錯會安靜
    地砍掉不該砍的事件。
    """
    by_code: dict[str, list[tuple[int, Observation]]] = {}
    for item in items:
        at = ordinal.get(item.period)
        if at is not None:
            by_code.setdefault(item.code, []).append((at, item))
    kept: list[Observation] = []
    for group in by_code.values():
        keep = set(non_overlapping([at for at, _ in group], horizon))
        kept.extend(item for at, item in sorted(group) if at in keep)
    return kept


@dataclass(frozen=True)
class Finding:
    """一個檢定的結果。

    `same_period` 是必填的:[#18] 的千張大戶人數對同期報酬 r=0.464
    (p=0.001)、對未來 r=0.130 (p=0.390) —— 同期強而領先弱,意思是這個指標
    是價格的鏡像,不是領先訊號。只看領先那一邊會把它誤判成「沒訊號」,而
    真相是「有訊號但不能用」。兩者要分清楚,所以組不出 Finding 就報不出結果。
    """

    name: str
    raw: Comparison
    demeaned: Comparison
    #: 事件組有幾個不同的期間。獨立樣本數更接近這個而不是 n
    periods: int
    #: 分組依據與**同一期**報酬的相關性 (Spearman r, p)
    same_period: tuple[float, float]

    @property
    def overstated(self) -> float:
        """筆數是獨立期間數的幾倍。1 代表沒有高估。"""
        return self.raw.n_event / self.periods if self.periods else 0.0

    @property
    def mirrors_price(self) -> bool:
        """同期比領先強 —— 這個指標可能只是價格的鏡像。"""
        r, p = self.same_period
        return p < ALPHA and abs(r) > abs_or_zero(self.demeaned)


def abs_or_zero(comparison: Comparison) -> float:
    """用去期間化後的中位數差當「領先效果」的粗略量尺。"""
    return abs(comparison.median_event - comparison.median_control) / 100


def compare_groups(
    name: str,
    observations: Sequence[Observation],
    horizon: int,
    periods: Sequence[object],
) -> Finding | None:
    """一個檢定:分組、篩重疊、原始與去期間化各跑一次。

    兩者都跑不是為了讓人挑好看的 —— 去期間化後的那一份是結果,原始那一份
    是為了讓期間叢聚的影響看得見。
    """
    events, controls = pooled(observations, horizon, periods)
    both = [*events, *controls]
    raw = compare(
        name,
        [o.excess for o in events],
        [o.excess for o in controls],
        deduped=True,
    )
    centred = demean_by_period(both)
    demeaned = compare(
        name,
        [o.excess for o in centred if o.is_event],
        [o.excess for o in centred if not o.is_event],
        deduped=True,
    )
    if raw is None or demeaned is None:
        return None
    # 同期:分組(事件=1、對照=0)和同一期報酬的相關性。強的同期關係加上
    # 弱的領先關係,就是「價格的鏡像」那個形狀 —— [#18] 的主要教訓
    sides = [1.0 if o.is_event else 0.0 for o in both]
    return Finding(
        name=name,
        raw=raw,
        demeaned=demeaned,
        periods=effective_n(events),
        same_period=contemporaneous(sides, [o.excess for o in both]),
    )


def report(findings: Sequence[Finding], coverage: Coverage) -> str:
    """結果表。校正一定做,涵蓋率一定印。

    校正後的 p 值按**位置**配回去,不是按名字 —— 用名字當 key 的話,兩個
    同名的檢定會collapse 成一個,兩列都印最後那一個的值。那會讓一個真正
    顯著的結果印成不顯著,也就是防多重比較的機制反而消滅了真結果。
    """
    lines = [coverage.describe(), ""]
    if not findings:
        return "\n".join([*lines, "沒有可用的檢定"])
    scored = adjust([f.demeaned for f in findings])
    lines.append(
        f"{'檢定':24}{'事件n':>6}{'期間':>5}{'高估':>6}"
        f"{'原始p':>8}{'去期間p':>9}{'校正p':>8}{'同期r':>8}"
    )
    hits = 0
    for finding, (_, adjusted) in zip(findings, scored, strict=True):
        if adjusted < ALPHA:
            hits += 1
        mark = " <-" if adjusted < ALPHA else ""
        lines.append(
            f"{finding.name:24}{finding.raw.n_event:>6}{finding.periods:>5}"
            f"{finding.overstated:>5.1f}x{finding.raw.pvalue:>8.3f}"
            f"{finding.demeaned.pvalue:>9.3f}{adjusted:>8.3f}"
            f"{finding.same_period[0]:>+8.2f}{mark}"
        )
    lines.append("")
    lines.append(f"{len(findings)} 個檢定,BH 校正後顯著:{hits} 個")
    lines.append("註:去期間化後中位數與勝率依構造靠近 0 與 50%,只看 p 值")
    mirrors = [f.name for f in findings if f.mirrors_price]
    if mirrors:
        lines.append(
            "⚠️ 同期關係強而領先關係弱,以下可能只是價格的鏡像:" + "、".join(mirrors)
        )
    return "\n".join(lines)


# --- 單一入口 ---


@dataclass(frozen=True)
class Grouping:
    """一個檢定:怎麼把事件分成兩組,以及持有多久。

    `is_event` 收一個 Event 回傳 True/False/None。None 代表這筆不參加這個
    檢定(例如按處置次數分組時,第三次以上的不歸任何一邊)。
    """

    name: str
    horizon: int
    is_event: Callable[[Event], bool | None]


@dataclass(frozen=True)
class Spec:
    """要測什麼。**跑之前就要寫完。**

    `window_of` 把一個事件變成 (進場日, 出場日),或 None 代表算不出來。
    兩個研究的窗口語意根本不同,所以這裡收的是函式而不是偏移量:

    * 處置股:相對出關日的**交易日偏移** —— 用 `anchor_window()`
    * 大戶籌碼:往後**幾個集保週次** —— 用 `period_window()`,因為週次序列
      本身有缺口(農曆年那一週沒資料),往後 13 週不是固定的 91 天

    不管用哪一個,`run_study` 都會自己檢查進場晚於 knowable。解析器回傳的
    窗口不合格就整筆丟掉,所以偷看未來的事件進不了樣本。

    groupings 是 tuple 而不是 list:跑完才想加一個檢定的話,得回來改這個
    物件並重跑整組,而校正的家族大小會跟著變。這不能阻止人作弊,但它讓
    「事後補一個檢定」變成一件看得見的事,而不是在 for 迴圈裡多一行。

    [#14] 就是死在這上面:10 個檢定裡 3 個原始 p<0.05,BH 校正後全滅。
    """

    name: str
    window_of: Callable[[Event], tuple[date, date] | None]
    groupings: tuple[Grouping, ...]
    #: 宇集有幾檔。涵蓋率要靠它算,所以必須由外面明確給
    universe: int


def anchor_window(
    days: Sequence[date], window: Window
) -> Callable[[Event], tuple[date, date] | None]:
    """相對事件原點的交易日偏移。處置股用這個。"""

    def resolve(event: Event) -> tuple[date, date] | None:
        return resolve_window(event, days, window)

    return resolve


def period_window(
    periods: Sequence[date], horizon: int
) -> Callable[[Event], tuple[date, date] | None]:
    """往後 horizon 個期間。大戶籌碼用這個。

    時滯不在這裡給 —— 它從事件自己的 `knowable` 推導出來。進場是資訊公開的
    隔天,出場把同樣的位移套在出場期間上,兩端一致持有期才不會少一截。

    時滯只能有一個來源。之前這裡收一個 lag 參數,而轉接層也把同一個時滯加進
    knowable,結果進場日剛好等於 knowable、被嚴格不等式全部拒掉 ——
    兩個地方各自決定同一件事,就一定會有一個是錯的。

    期間序列有缺口時,實際天數會跟著變長 —— 那是事實而不是 bug:集保在
    農曆年那一週沒資料,所以跨過缺口的 13 週窗口實際是 98 天。
    """
    ordinal = {period: i for i, period in enumerate(periods)}

    def resolve(event: Event) -> tuple[date, date] | None:
        at = ordinal.get(event.happened)
        if at is None or at + horizon >= len(periods):
            return None
        # 進場是資訊公開的隔天。同樣的位移也套在出場期間上
        shift = event.knowable - event.happened + timedelta(days=1)
        return event.happened + shift, periods[at + horizon] + shift

    return resolve


def run_study(
    spec: Spec,
    events: Sequence[Event],
    closes: dict[str, dict[date, float]],
    periods: Sequence[object],
) -> tuple[list[Finding], Coverage]:
    """跑完 Spec 裡的每一個檢定,回傳結果與涵蓋率。

    這是框架的入口。從這裡進去的研究自動得到:進場早於 knowable 的事件被
    丟掉、重疊窗口篩掉並回報獨立期間數、去期間化與原始兩種都算、同期相關性
    一起算、涵蓋率跟著輸出。
    """
    scored: list[tuple[Event, float]] = []
    for event in events:
        span = spec.window_of(event)
        # 守衛在這裡,不在解析器裡 —— 換一個解析器也繞不過去
        if span is None or span[0] <= event.knowable:
            continue
        series = closes.get(event.code)
        if series is None:
            continue
        value = window_excess(series, closes, *span)
        if value is not None:
            scored.append((event, value))
    usable = [event for event, _ in scored]

    findings: list[Finding] = []
    for grouping in spec.groupings:
        observations = [
            Observation(
                code=event.code,
                period=event.happened,
                excess=value,
                is_event=side,
            )
            for event, value in scored
            if (side := grouping.is_event(event)) is not None
        ]
        found = compare_groups(grouping.name, observations, grouping.horizon, periods)
        if found is not None:
            findings.append(found)
    return findings, Coverage.of(events, usable, spec.universe)
