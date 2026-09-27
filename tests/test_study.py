"""事件研究框架。測的重點是每一道守衛真的擋得住。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.eventstats import Comparison, Observation
from src.study import (
    PILOT_BELOW,
    Coverage,
    Event,
    Finding,
    Grouping,
    Spec,
    Window,
    anchor_window,
    compare_groups,
    one_sample,
    period_window,
    pooled,
    report,
    resolve_window,
    run_study,
)


class TestEventKnowable:
    """knowable 必填。先後沒有限制 —— 兩種方向都是真實存在的事件型態。"""

    def test_可以晚於發生日_那是資料發布型(self) -> None:
        # 集保:資料日期是 happened,再五天才公布
        got = Event(code="1101", happened=date(2026, 1, 1), knowable=date(2026, 1, 6))
        assert got.knowable > got.happened

    def test_可以早於發生日_那是預定事件型(self) -> None:
        # 處置:出關日是 happened,但公告兩週前就發了。
        # 一開始我把這個當成錯誤擋掉,結果 [#13] 的 951 筆全部被拒 ——
        # 守衛擺錯位置了,該擋的是進場日而不是 happened/knowable 的先後
        got = Event(code="1101", happened=date(2026, 1, 20), knowable=date(2026, 1, 6))
        assert got.knowable < got.happened

    def test_可以相等(self) -> None:
        got = Event(code="1101", happened=date(2026, 1, 1), knowable=date(2026, 1, 1))
        assert got.knowable == got.happened

    def test_沒有預設值_忘記給就是_TypeError(self) -> None:
        """這是整個設計的關鍵:忘記設定不會安靜地變成偷看未來。"""
        with pytest.raises(TypeError):
            Event(code="1101", happened=date(2026, 1, 1))  # type: ignore[call-arg]

    def test_tags_預設是空的而不是共用同一個字典(self) -> None:
        a = Event("1101", date(2026, 1, 1), date(2026, 1, 1))
        b = Event("1102", date(2026, 1, 1), date(2026, 1, 1))
        a.tags["x"] = 1
        assert b.tags == {}


DAYS = [date(2026, 1, d) for d in (5, 6, 7, 8, 9, 12, 13, 14, 15, 16)]


class TestWindow:
    def test_出場在進場之前要出錯(self) -> None:
        with pytest.raises(ValueError, match="之前"):
            Window(entry=-1, exit=-6)

    def test_同一天進出是合法的(self) -> None:
        assert Window(entry=0, exit=0).exit == 0


class TestResolveWindow:
    """進場早於 knowable 一定回 None —— 這是偷看未來的結構性解法。"""

    def _event(self, knowable: date) -> Event:
        # 原點是 1/15,也就是 DAYS 裡的第 8 個
        return Event("1101", happened=date(2026, 1, 15), knowable=knowable)

    def test_算出原點前六天買_前一天賣(self) -> None:
        got = resolve_window(self._event(date(2026, 1, 1)), DAYS, Window(-6, -1))
        assert got == (date(2026, 1, 7), date(2026, 1, 14))

    def test_進場早於_knowable_就回_None(self) -> None:
        # knowable 是 1/9,但窗口要 1/7 進場 —— 那時還不知道這件事
        assert (
            resolve_window(self._event(date(2026, 1, 9)), DAYS, Window(-6, -1)) is None
        )

    def test_進場日等於_knowable_也要擋(self) -> None:
        # knowable 是資訊公開那一天,而公告多半盤後發布 ——
        # 在公告日收盤買進就是偷看未來。實測放寬一天會多收 28 筆事件
        assert (
            resolve_window(self._event(date(2026, 1, 7)), DAYS, Window(-6, -1)) is None
        )

    def test_進場日晚於_knowable_一天就可以(self) -> None:
        got = resolve_window(self._event(date(2026, 1, 6)), DAYS, Window(-6, -1))
        assert got == (date(2026, 1, 7), date(2026, 1, 14))

    def test_窗口往前超出資料範圍回_None(self) -> None:
        assert (
            resolve_window(self._event(date(2026, 1, 1)), DAYS, Window(-20, -1)) is None
        )

    def test_窗口往後超出資料範圍回_None(self) -> None:
        # 負索引在 Python 會從尾端取值,不檢查上下界就會安靜地取到錯的日子
        assert (
            resolve_window(self._event(date(2026, 1, 1)), DAYS, Window(0, 20)) is None
        )

    def test_原點不在交易日上時用之後最近的(self) -> None:
        # 1/10 是週六,原點該落到 1/12
        weekend = Event("1101", happened=date(2026, 1, 10), knowable=date(2026, 1, 1))
        got = resolve_window(weekend, DAYS, Window(0, 0))
        assert got == (date(2026, 1, 12), date(2026, 1, 12))

    def test_原點在所有交易日之後回_None(self) -> None:
        late = Event("1101", happened=date(2030, 1, 1), knowable=date(2026, 1, 1))
        assert resolve_window(late, DAYS, Window(0, 0)) is None


class TestCoverage:
    def test_算出涵蓋比例(self) -> None:
        cov = Coverage(
            label="x", codes=20, universe=1000, events=100, usable=90, span=None
        )
        assert cov.ratio == pytest.approx(0.02)

    def test_涵蓋率低就是先導測試(self) -> None:
        cov = Coverage(
            label="x", codes=20, universe=1000, events=100, usable=90, span=None
        )
        assert cov.pilot is True
        assert "先導測試" in cov.describe()

    def test_涵蓋率高就不標先導(self) -> None:
        cov = Coverage(
            label="x", codes=900, universe=1000, events=100, usable=90, span=None
        )
        assert cov.pilot is False
        assert "先導測試" not in cov.describe()

    def test_剛好在門檻上不算先導(self) -> None:
        cov = Coverage(
            label="x",
            codes=int(1000 * PILOT_BELOW),
            universe=1000,
            events=1,
            usable=1,
            span=None,
        )
        assert cov.pilot is False

    def test_宇集是零時不會除以零(self) -> None:
        cov = Coverage(label="x", codes=0, universe=0, events=0, usable=0, span=None)
        assert cov.ratio == 0.0

    def test_被擋掉的事件數看得出來(self) -> None:
        cov = Coverage(
            label="x", codes=5, universe=10, events=100, usable=71, span=None
        )
        assert "71/100" in cov.describe()

    def test_期間會印出來(self) -> None:
        cov = Coverage(
            label="x",
            codes=5,
            universe=10,
            events=1,
            usable=1,
            span=(date(2020, 1, 1), date(2026, 9, 24)),
        )
        assert "2020-01-01–2026-09-24" in cov.describe()


class TestOneSample:
    def test_全部為正時中位數為正且顯著(self) -> None:
        med, p = one_sample([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
        assert med == 4.0
        assert p < 0.05

    def test_對稱分布不顯著(self) -> None:
        _, p = one_sample([-3.0, -2.0, -1.0, 1.0, 2.0, 3.0])
        assert p > 0.05

    def test_樣本太少時回不顯著而不是丟例外(self) -> None:
        med, p = one_sample([1.0, 2.0])
        assert (med, p) == (0.0, 1.0)

    def test_空輸入不會炸(self) -> None:
        assert one_sample([]) == (0.0, 1.0)


def _obs(code: str, period: int, excess: float, *, event: bool) -> Observation:
    return Observation(code=code, period=period, excess=excess, is_event=event)


WEEKS = list(range(24))


class TestPooled:
    """重疊要在時間尺標上量,不能用觀察在清單裡的位置。"""

    def test_事件組與對照組分開(self) -> None:
        items = [
            _obs("a", 0, 1.0, event=True),
            _obs("a", 10, 2.0, event=False),
        ]
        events, controls = pooled(items, 1, WEEKS)
        assert [o.excess for o in events] == [1.0]
        assert [o.excess for o in controls] == [2.0]

    def test_同一檔之內篩掉重疊窗口(self) -> None:
        # 注意這個 fixture 的 period 剛好等於它在清單裡的位置,所以它**不能**
        # 證明距離是用期間量的。真正在測那件事的是下面兩個
        items = [_obs("a", i, 1.0, event=True) for i in range(6)]
        events, _ = pooled(items, 3, WEEKS)
        assert [o.period for o in events] == [0, 3]

    def test_距離用期間量而不是用清單位置(self) -> None:
        # 兩筆相隔 20 個期間、在清單裡卻是相鄰兩筆。用位置量會砍掉一筆
        items = [
            _obs("a", 0, 1.0, event=True),
            _obs("a", 20, 2.0, event=True),
        ]
        events, _ = pooled(items, 13, WEEKS)
        assert len(events) == 2

    def test_期間是整數時排序不會用字典順序(self) -> None:
        # 字串排序會變成 1, 10, 11, 2, 20, 9 —— 然後保留最擠的兩筆、
        # 丟掉四筆分得很開的
        items = [_obs("a", i, 1.0, event=True) for i in (1, 2, 9, 10, 11, 20)]
        events, _ = pooled(items, 3, WEEKS)
        assert [o.period for o in events] == [1, 9, 20]

    def test_不同檔之間不會互相篩掉(self) -> None:
        items = [_obs(c, 0, 1.0, event=True) for c in "abc"]
        events, _ = pooled(items, 13, WEEKS)
        assert len(events) == 3

    def test_不在時間尺標上的期間直接丟掉(self) -> None:
        # 留著就得猜它的時間位置,猜錯會安靜地砍掉不該砍的事件
        items = [
            _obs("a", 0, 1.0, event=True),
            _obs("a", 999, 2.0, event=True),
        ]
        events, _ = pooled(items, 1, WEEKS)
        assert [o.period for o in events] == [0]

    def test_持有期一時全部保留(self) -> None:
        items = [_obs("a", i, 1.0, event=True) for i in range(5)]
        events, _ = pooled(items, 1, WEEKS)
        assert len(events) == 5


class TestCompareGroups:
    def _items(self) -> list[Observation]:
        # 每個期間都有兩組,去期間化才有意義
        out: list[Observation] = []
        for period in range(12):
            out.append(_obs("a", period, 5.0 + period, event=True))
            out.append(_obs("b", period, 1.0 + period, event=False))
        return out

    def test_原始與去期間化都會算(self) -> None:
        got = compare_groups("x", self._items(), 1, WEEKS)
        assert got is not None
        assert got.raw.n_event == 12
        assert got.demeaned.n_event == 12

    def test_去期間化會拿掉期間的共同水位(self) -> None:
        # 兩組都隨期間上升,去期間化後那個共同趨勢應該消失
        got = compare_groups("x", self._items(), 1, WEEKS)
        assert got is not None
        assert abs(got.demeaned.median_event) < abs(got.raw.median_event)

    def test_回報事件組的獨立期間數(self) -> None:
        got = compare_groups("x", self._items(), 1, WEEKS)
        assert got is not None
        assert got.periods == 12
        assert got.overstated == pytest.approx(1.0)

    def test_同一期間多筆時高估倍數大於一(self) -> None:
        items = [_obs(c, 0, 1.0 + i, event=True) for i, c in enumerate("abcdef")]
        items += [_obs(c, 0, 0.0, event=False) for c in "ghijkl"]
        got = compare_groups("x", items, 1, WEEKS)
        assert got is not None
        assert got.periods == 1
        assert got.overstated == pytest.approx(6.0)

    def test_樣本太少時回_None(self) -> None:
        assert compare_groups("x", [_obs("a", 0, 1.0, event=True)], 1, WEEKS) is None


class TestReport:
    def _finding(self):
        out: list[Observation] = []
        for period in range(12):
            out.append(_obs("a", period, 5.0, event=True))
            out.append(_obs("b", period, 1.0, event=False))
        return compare_groups("試驗", out, 1, WEEKS)

    def test_涵蓋率一定印在最前面(self) -> None:
        cov = Coverage(
            label="x", codes=20, universe=1000, events=12, usable=12, span=None
        )
        finding = self._finding()
        assert finding is not None
        text = report([finding], [cov])
        assert text.startswith("x:20/1000")

    def test_先導測試的警告會出現(self) -> None:
        cov = Coverage(
            label="x", codes=20, universe=1000, events=12, usable=12, span=None
        )
        finding = self._finding()
        assert finding is not None
        assert "先導測試" in report([finding], [cov])

    def test_校正後的_p_一定出現(self) -> None:
        cov = Coverage(
            label="x", codes=900, universe=1000, events=12, usable=12, span=None
        )
        finding = self._finding()
        assert finding is not None
        text = report([finding], [cov])
        assert "校正p" in text
        assert "BH 校正後顯著" in text

    def test_沒有檢定時也不會炸(self) -> None:
        cov = Coverage(label="x", codes=0, universe=10, events=0, usable=0, span=None)
        assert "沒有可用的檢定" in report([], [cov])

    def test_高估倍數會印出來(self) -> None:
        cov = Coverage(label="x", codes=2, universe=2, events=12, usable=12, span=None)
        finding = self._finding()
        assert finding is not None
        assert "高估" in report([finding], [cov])


class TestReportPairing:
    """校正後的 p 值必須按位置配回去,不能按名字。"""

    def _finding(self, *, separated: bool, name: str):
        """separated=True 是完全分離(顯著),False 是交錯(不顯著)。"""
        out: list[Observation] = []
        for period in range(12):
            if separated:
                event, control = 50.0, 0.0
            else:
                # 交錯:兩組的值輪流大小,等級和幾乎相同
                event = float(period)
                control = float(period) + (1 if period % 2 else -1)
            out.append(_obs("a", period, event, event=True))
            out.append(_obs("b", period, control, event=False))
        return compare_groups(name, out, 1, WEEKS)

    @staticmethod
    def _corrected(line: str) -> str:
        """校正後 p 那一欄。

        不能取最後一個 token —— 那是同期 r。之前取錯欄位,結果這個測試在
        斷言「兩個 Spearman r 不相等」,把它要防的 bug 植回去照樣會過。
        """
        return line.removesuffix(" <-").split()[-2]

    def test_兩個同名的檢定不會共用同一個校正_p(self) -> None:
        # 用名字當 key 的話兩列都印最後那一個的值 —— 那會讓一個真正顯著的
        # 結果印成不顯著,也就是防多重比較的機制反而消滅了真結果。
        # 這裡要專門比校正 p 那一欄:兩列在原始 p 欄本來就不同,
        # 直接比整行的話有 bug 也看不出來
        strong = self._finding(separated=True, name="同名")
        weak = self._finding(separated=False, name="同名")
        assert strong is not None
        assert weak is not None
        cov = Coverage(label="x", codes=2, universe=2, events=24, usable=24, span=None)
        rows = [
            line
            for line in report([strong, weak], [cov]).splitlines()
            if line.startswith("同名")
        ]
        assert len(rows) == 2
        assert self._corrected(rows[0]) != self._corrected(rows[1])

    def test_顯著的那一列保留標記(self) -> None:
        strong = self._finding(separated=True, name="強")
        weak = self._finding(separated=False, name="弱")
        assert strong is not None
        assert weak is not None
        cov = Coverage(label="x", codes=2, universe=2, events=24, usable=24, span=None)
        text = report([strong, weak], [cov])
        marked = [line for line in text.splitlines() if line.endswith("<-")]
        assert len(marked) == 1
        assert marked[0].startswith("強")

    def test_顯著個數和表上的標記一致(self) -> None:
        strong = self._finding(separated=True, name="強")
        weak = self._finding(separated=False, name="弱")
        assert strong is not None
        assert weak is not None
        cov = Coverage(label="x", codes=2, universe=2, events=24, usable=24, span=None)
        text = report([strong, weak], [cov])
        marked = sum(1 for line in text.splitlines() if line.endswith("<-"))
        assert f"顯著:{marked} 個" in text


class TestCoverageOf:
    """Coverage 要從事件推導,不能讓呼叫端少報宇集躲掉先導警告。"""

    def _events(self, n: int) -> list[Event]:
        return [
            Event(f"110{i}", date(2026, 1, 1 + i), date(2026, 1, 1)) for i in range(n)
        ]

    def test_檔數與期間都從事件算出來(self) -> None:
        events = self._events(3)
        cov = Coverage.of("x", events, events, universe=10)
        assert cov.codes == 3
        assert cov.usable == 3
        assert cov.span == (date(2026, 1, 1), date(2026, 1, 3))

    def test_被擋掉的事件數看得出來(self) -> None:
        events = self._events(5)
        cov = Coverage.of("x", events, events[:2], universe=10)
        assert (cov.events, cov.usable) == (5, 2)

    def test_同一檔多個事件只算一檔(self) -> None:
        events = [
            Event("1101", date(2026, 1, 1), date(2026, 1, 1)),
            Event("1101", date(2026, 2, 1), date(2026, 1, 1)),
        ]
        cov = Coverage.of("x", events, events, universe=10)
        assert cov.codes == 1

    def test_沒有可用事件時期間是_None(self) -> None:
        cov = Coverage.of("x", self._events(3), [], universe=10)
        assert cov.span is None
        assert cov.codes == 0


class TestIndexAtOrAfterBounds:
    def test_錨點早於所有資料回_None_而不是錨到第一天(self) -> None:
        # 錨到第一天的話,一個比價格資料還早幾年的事件會配到一個
        # 看起來合理、但完全錯誤時期的窗口
        early = Event("1101", date(2019, 1, 1), date(2018, 1, 1))
        assert resolve_window(early, DAYS, Window(0, 1)) is None

    def test_交易日清單是空的回_None(self) -> None:
        event = Event("1101", date(2026, 1, 15), date(2026, 1, 1))
        assert resolve_window(event, [], Window(0, 0)) is None


class TestOneSampleZeros:
    def test_全部是零時不會發警告也不會炸(self) -> None:
        med, p = one_sample([0.0] * 10)
        assert (med, p) == (0.0, 1.0)

    def test_零值會平分到兩側而不是被丟掉(self) -> None:
        # scipy 預設的 wilcox 會丟掉零值,讓有效樣本數悄悄變小、p 被推大
        with_zeros = one_sample([1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        assert with_zeros[1] > 0.05


CLOSES = {
    "up": {d: 100.0 + i * 5 for i, d in enumerate(DAYS)},
    "flat": dict.fromkeys(DAYS, 100.0),
    "down": {d: 100.0 - i * 5 for i, d in enumerate(DAYS)},
}


def _spec(*groupings: Grouping) -> Spec:
    return Spec(
        name="試驗",
        window_of=anchor_window(DAYS, Window(0, 1)),
        horizon=1,
        groupings=groupings,
        universe=10,
    )


class TestRunStudy:
    """框架的單一入口。從這裡進去就自動得到全部守衛。"""

    def _events(self) -> list[Event]:
        # 每一檔在每一個交易日都有一個事件,tags 標記它屬於哪一組
        return [
            Event(code, day, DAYS[0], tags={"kind": code})
            for code in ("up", "flat", "down")
            for day in DAYS[1:-1]
        ]

    def test_跑出結果與涵蓋率(self) -> None:
        spec = _spec(Grouping("漲組", lambda e: e.code == "up"))
        findings, cov = run_study(spec, self._events(), CLOSES, periods=DAYS)
        assert len(findings) == 1
        assert cov.universe == 10
        assert cov.codes == 3

    def test_每個_grouping_各一個_finding(self) -> None:
        spec = _spec(
            Grouping("漲組", lambda e: e.code == "up"),
            Grouping("跌組", lambda e: e.code == "down"),
        )
        findings, _ = run_study(spec, self._events(), CLOSES, DAYS)
        assert [f.name for f in findings] == ["漲組", "跌組"]

    def test_回_None_的事件不參加那個檢定(self) -> None:
        # 例如按處置次數分組時,第三次以上的不歸任何一邊
        def only_up_vs_down(event: Event) -> bool | None:
            if event.code == "flat":
                return None
            return event.code == "up"

        spec = _spec(Grouping("漲對跌", only_up_vs_down))
        findings, _ = run_study(spec, self._events(), CLOSES, DAYS)
        # 兩檔 × 8 個可用事件。回 None 的 flat 一筆都不該進來 ——
        # 寫成「不超過 20」的話,忽略 None 而全部收進來(24 筆)也會過
        got = findings[0].raw
        assert got.n_event + got.n_control == 16

    def test_窗口解不出來的事件不會進樣本(self) -> None:
        # knowable 設在最後一天,所有窗口的進場都早於它
        blocked = [
            Event(code, day, DAYS[-1], tags={})
            for code in ("up", "down")
            for day in DAYS[1:-1]
        ]
        spec = _spec(Grouping("漲組", lambda e: e.code == "up"))
        findings, cov = run_study(spec, blocked, CLOSES, DAYS)
        assert findings == []
        assert cov.usable == 0
        assert cov.events == len(blocked)

    def test_沒有價格的股票不會進樣本(self) -> None:
        ghost = [Event("沒這檔", day, DAYS[0]) for day in DAYS[1:-1]]
        spec = _spec(Grouping("x", lambda _: True))
        _, cov = run_study(spec, ghost, CLOSES, DAYS)
        assert cov.usable == 0

    def test_涵蓋率會標出先導測試(self) -> None:
        spec = _spec(Grouping("漲組", lambda e: e.code == "up"))
        _, cov = run_study(spec, self._events(), CLOSES, DAYS)
        # 3 檔 / 宇集 10 檔 = 30%
        assert cov.pilot is True

    def test_沒有事件時不會炸(self) -> None:
        spec = _spec(Grouping("x", lambda _: True))
        findings, cov = run_study(spec, [], CLOSES, DAYS)
        assert findings == []
        assert cov.span is None


class TestSpecIsFrozen:
    """檢定清單是 tuple —— 事後補一個檢定必須是看得見的改動。"""

    def test_事前登記的檢定數對不上時報表會講出來(self) -> None:
        # tuple 沒有 .append 是 CPython 的事實,測它沒有意義。真正要防的是
        # 看到結果之後砍掉一個持有期讓倖存者顯著 —— 家族變小、校正變鬆
        items: list[Observation] = []
        for period in range(12):
            items.append(_obs("a", period, 5.0, event=True))
            items.append(_obs("b", period, 1.0, event=False))
        found = compare_groups("只跑了一個", items, 1, WEEKS)
        assert found is not None
        cov = Coverage(label="x", codes=2, universe=2, events=24, usable=24, span=None)
        assert "事前登記了 3 個檢定" in report([found], [cov], declared=3)

    def test_數量對得上時不會有那個警告(self) -> None:
        items: list[Observation] = []
        for period in range(12):
            items.append(_obs("a", period, 5.0, event=True))
            items.append(_obs("b", period, 1.0, event=False))
        found = compare_groups("x", items, 1, WEEKS)
        assert found is not None
        cov = Coverage(label="x", codes=2, universe=2, events=24, usable=24, span=None)
        assert "事前登記了" not in report([found], [cov], declared=1)

    def test_spec_本身不能改(self) -> None:
        spec = _spec(Grouping("x", lambda _: True))
        with pytest.raises(AttributeError):
            spec.universe = 1  # type: ignore[misc]


class TestMirrorsPrice:
    """同期強而領先弱 = 價格的鏡像。[#18] 的主要教訓。"""

    def test_同期完全相關時標為鏡像(self) -> None:
        # 事件組全部是正報酬、對照組全部是負的 —— 分組和同期報酬完全相關,
        # 但去期間化後兩組的中位數差是 0
        items: list[Observation] = []
        for period in range(12):
            items.append(_obs("a", period, 10.0, event=True))
            items.append(_obs("b", period, -10.0, event=False))
        found = compare_groups("鏡像", items, 1, WEEKS)
        assert found is not None
        assert found.same_period[0] > 0.9
        assert found.mirrors_price is True

    def test_鏡像會出現在報表的警告裡(self) -> None:
        items: list[Observation] = []
        for period in range(12):
            items.append(_obs("a", period, 10.0, event=True))
            items.append(_obs("b", period, -10.0, event=False))
        found = compare_groups("鏡像", items, 1, WEEKS)
        assert found is not None
        cov = Coverage(label="x", codes=2, universe=2, events=24, usable=24, span=None)
        assert "價格的鏡像" in report([found], [cov])

    def test_同期沒關係時不標鏡像(self) -> None:
        items: list[Observation] = []
        for period in range(12):
            sign = 1.0 if period % 2 else -1.0
            items.append(_obs("a", period, sign, event=True))
            items.append(_obs("b", period, -sign, event=False))
        found = compare_groups("乾淨", items, 1, WEEKS)
        assert found is not None
        assert found.mirrors_price is False

    def test_same_period_是必填的(self) -> None:
        with pytest.raises(TypeError):
            Finding(  # type: ignore[call-arg]
                name="x",
                raw=Comparison("x", 5, 5, 0, 0, 0, 0, 0.5, deduped=True),
                demeaned=Comparison("x", 5, 5, 0, 0, 0, 0, 0.5, deduped=True),
                periods=5,
            )


class TestPeriodWindow:
    """往後幾個期間。時滯從事件的 knowable 推導,不另外給參數。"""

    periods = [date(2026, 1, d) for d in (5, 12, 19, 26)]

    def _event(self, day: date, lag_days: int) -> Event:
        return Event("1101", day, day + timedelta(days=lag_days))

    def test_進場是資訊公開的隔天(self) -> None:
        resolve = period_window(self.periods, 1)
        got = resolve(self._event(date(2026, 1, 5), lag_days=5))
        assert got is not None
        assert got[0] == date(2026, 1, 11)

    def test_同樣的位移也套在出場期間上(self) -> None:
        # 兩端一致持有期才不會少一截
        resolve = period_window(self.periods, 1)
        got = resolve(self._event(date(2026, 1, 5), lag_days=5))
        assert got == (date(2026, 1, 11), date(2026, 1, 18))

    def test_持有期就是期間之間的距離(self) -> None:
        resolve = period_window(self.periods, 2)
        got = resolve(self._event(date(2026, 1, 5), lag_days=5))
        assert got is not None
        assert (got[1] - got[0]).days == 14

    def test_進場一定嚴格晚於_knowable(self) -> None:
        # 時滯給兩個地方決定的話,進場會剛好等於 knowable 而被全部拒掉
        event = self._event(date(2026, 1, 5), lag_days=5)
        got = period_window(self.periods, 1)(event)
        assert got is not None
        assert got[0] > event.knowable

    def test_沒有時滯時進場是事件的隔天(self) -> None:
        resolve = period_window(self.periods, 1)
        got = resolve(self._event(date(2026, 1, 5), lag_days=0))
        assert got == (date(2026, 1, 6), date(2026, 1, 13))

    def test_出場期間不存在時回_None(self) -> None:
        resolve = period_window(self.periods, 2)
        assert resolve(self._event(date(2026, 1, 19), lag_days=5)) is None

    def test_事件的日期不在期間序列上回_None(self) -> None:
        resolve = period_window(self.periods, 1)
        assert resolve(self._event(date(2026, 1, 6), lag_days=5)) is None

    def test_期間有缺口時窗口實際天數會變長(self) -> None:
        # 集保農曆年那一週沒資料 —— 跨過缺口的窗口天數就是比較長
        gappy = [date(2026, 2, 6), date(2026, 2, 13), date(2026, 2, 26)]
        resolve = period_window(gappy, 1)
        normal = resolve(self._event(date(2026, 2, 6), lag_days=5))
        across = resolve(self._event(date(2026, 2, 13), lag_days=5))
        assert normal is not None
        assert across is not None
        assert (normal[1] - normal[0]).days == 7
        assert (across[1] - across[0]).days == 13


class TestRunStudyGuardCannotBeBypassed:
    """換一個窗口解析器也繞不過 knowable 的檢查。"""

    def test_解析器不檢查_knowable_時_run_study_還是會擋(self) -> None:
        def reckless(_: Event) -> tuple[date, date]:
            """故意完全不管 knowable。"""
            return DAYS[0], DAYS[-1]

        events = [Event("up", DAYS[3], DAYS[5])]
        spec = Spec(
            name="x",
            window_of=reckless,
            horizon=1,
            groupings=(Grouping("x", lambda _: True),),
            universe=1,
        )
        _, cov = run_study(spec, events, CLOSES, DAYS)
        # 進場是 DAYS[0],早於 knowable=DAYS[5],所以整筆丟掉
        assert cov.usable == 0

    def test_進場晚於_knowable_就收(self) -> None:
        def fine(_: Event) -> tuple[date, date]:
            """進場晚於 knowable。"""
            return DAYS[6], DAYS[-1]

        events = [Event("up", DAYS[3], DAYS[5])]
        spec = Spec(
            name="x",
            window_of=fine,
            horizon=1,
            groupings=(Grouping("x", lambda _: True),),
            universe=1,
        )
        _, cov = run_study(spec, events, CLOSES, DAYS)
        assert cov.usable == 1
