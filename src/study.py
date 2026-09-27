"""事件研究框架:讓踩過的坑寫不出來。

處置股([#13])、大戶籌碼([#18]–[#21])、以及下一個題目都走這裡。

這個模組的目的不是提供功能,是**讓錯誤寫不出來**。每一道守衛都對應一個
實際踩過的坑:

* `Event.knowable` **必填且無預設**,而 `resolve_window` 會擋掉進場早於它的
  窗口 —— [#13] 有 29/31 筆新制事件的進場點落在公告當天。算報酬一定要先
  拿到窗口,所以這道檢查繞不過去。
* `Spec` 是輸入。跑完才想加檢定,就得重跑整組並重新校正 —— [#14] 有 10 個
  檢定、3 個原始 p<0.05,校正後全滅。
* 校正由 `run_study` 自己做,不是選項。
* 重疊窗口自動篩掉並回報獨立樣本數 —— [#20] 把 36 個重疊觀察當成 36 個樣本。
* 期間叢聚自動去除並兩種都報 —— [#19] 的 review 抓到事件組和對照組落在
  差兩個月的不同期間。
* 涵蓋率跟結果一起輸出,低於門檻標示為先導測試 —— [#23] 目前只涵蓋 37%
  的普通股,不能讓 20 檔的結果印出來長得像全市場研究。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from scipy import stats

from src.eventstats import (
    Comparison,
    Observation,
    adjust,
    compare,
    demean_by_period,
    effective_n,
    median,
    non_overlapping,
)


if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

#: 涵蓋率低於這個比例就標示為先導測試,不能當全市場研究讀
PILOT_BELOW = 0.5


@dataclass(frozen=True)
class Event:
    """一件事情發生在某一檔股票上。

    `happened` 和 `knowable` 分開是這個框架的核心:前者是事件對齊的原點,
    後者是**外界最早能知道它**的日子。

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
    if entry < event.knowable:
        return None
    return entry, exit_


def _index_at_or_after(days: Sequence[date], day: date) -> int | None:
    """當天或之後最近一個交易日的位置。"""
    for i, candidate in enumerate(days):
        if candidate >= day:
            return i
    return None


@dataclass(frozen=True)
class Coverage:
    """這次研究實際涵蓋了什麼。跟結果一起輸出,不能只報 p 值。"""

    codes: int
    universe: int
    events: int
    #: 進場點在 knowable 之後的事件數。比 events 少就是有事件被擋掉了
    usable: int
    span: tuple[date, date] | None

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


@dataclass(frozen=True)
class Test:
    """一個要跑的檢定。事前登記用 —— 跑之前就要寫完。"""

    name: str
    #: 事件組的判定。回 None 代表這筆事件不進這個檢定
    group: object


def one_sample(values: Sequence[float]) -> tuple[float, float]:
    """一組報酬對零的檢定,回傳 (中位數, p)。

    Wilcoxon 符號等級檢定,雙尾。問的是「這組報酬的中心是不是 0」,
    用在沒有自然對照組的研究(例如處置股:所有處置事件都是事件,
    沒有「沒被處置」的對照)。
    """
    cleaned = [v for v in values if v == v]  # noqa: PLR0124 - 濾掉 NaN
    if len(cleaned) < MIN_ONE_SAMPLE:
        return (0.0, 1.0)
    result = stats.wilcoxon(cleaned, alternative="two-sided")
    return median(cleaned), float(result.pvalue)


#: 少於這麼多筆就不做單樣本檢定
MIN_ONE_SAMPLE = 6


def pooled(
    observations: Sequence[Observation], horizon: int
) -> tuple[list[Observation], list[Observation]]:
    """把觀察分成事件組和對照組,各自篩掉重疊窗口。

    分組之後才篩重疊,而且兩組各自篩 —— 這正是 [#19] 的 review 抓到會造成
    期間錯配的地方。框架的處理不是避免它(避不掉,兩組本來就在不同時間),
    而是讓 `run_study` 一定同時報去期間化後的結果。
    """
    events = [o for o in observations if o.is_event]
    controls = [o for o in observations if not o.is_event]
    return (
        _dedup(events, horizon),
        _dedup(controls, horizon),
    )


def _dedup(items: Sequence[Observation], horizon: int) -> list[Observation]:
    """同一檔之內篩掉重疊窗口。不同檔之間不會互相重疊。"""
    by_code: dict[str, list[Observation]] = {}
    for item in items:
        by_code.setdefault(item.code, []).append(item)
    kept: list[Observation] = []
    for group in by_code.values():
        ordered = sorted(group, key=lambda o: str(o.period))
        keep = set(non_overlapping(range(len(ordered)), horizon))
        kept.extend(o for i, o in enumerate(ordered) if i in keep)
    return kept


@dataclass(frozen=True)
class Finding:
    """一個檢定的結果,原始與去期間化各一份。"""

    name: str
    raw: Comparison
    demeaned: Comparison
    #: 事件組有幾個不同的期間。獨立樣本數更接近這個而不是 n
    periods: int

    @property
    def overstated(self) -> float:
        """筆數是獨立期間數的幾倍。1 代表沒有高估。"""
        return self.raw.n_event / self.periods if self.periods else 0.0


def compare_groups(
    name: str, observations: Sequence[Observation], horizon: int
) -> Finding | None:
    """一個檢定:分組、篩重疊、原始與去期間化各跑一次。

    兩者都跑不是為了讓人挑好看的 —— 去期間化後的那一份是結果,原始那一份
    是為了讓期間叢聚的影響看得見。
    """
    events, controls = pooled(observations, horizon)
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
    return Finding(name=name, raw=raw, demeaned=demeaned, periods=effective_n(events))


def report(findings: Sequence[Finding], coverage: Coverage) -> str:
    """結果表。校正一定做,涵蓋率一定印。"""
    lines = [coverage.describe(), ""]
    if not findings:
        return "\n".join([*lines, "沒有可用的檢定"])
    scored = adjust([f.demeaned for f in findings])
    lookup = {c.name: p for c, p in scored}
    lines.append(
        f"{'檢定':24}{'事件n':>6}{'期間':>5}{'高估':>6}"
        f"{'原始p':>8}{'去期間p':>9}{'校正p':>8}"
    )
    for finding in findings:
        adjusted = lookup[finding.demeaned.name]
        mark = " <-" if adjusted < 0.05 else ""  # noqa: PLR2004
        lines.append(
            f"{finding.name:24}{finding.raw.n_event:>6}{finding.periods:>5}"
            f"{finding.overstated:>5.1f}x{finding.raw.pvalue:>8.3f}"
            f"{finding.demeaned.pvalue:>9.3f}{adjusted:>8.3f}{mark}"
        )
    hits = sum(1 for _, p in scored if p < 0.05)  # noqa: PLR2004
    lines.append("")
    lines.append(f"{len(findings)} 個檢定,BH 校正後顯著:{hits} 個")
    lines.append("註:去期間化後中位數與勝率依構造靠近 0 與 50%,只看 p 值")
    return "\n".join(lines)
