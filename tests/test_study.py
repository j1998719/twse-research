"""事件研究框架。測的重點是每一道守衛真的擋得住。"""

from __future__ import annotations

from datetime import date

import pytest

from src.eventstats import Observation
from src.study import (
    PILOT_BELOW,
    Coverage,
    Event,
    Window,
    compare_groups,
    one_sample,
    pooled,
    report,
    resolve_window,
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

    def test_knowable_剛好等於進場日是可以的(self) -> None:
        got = resolve_window(self._event(date(2026, 1, 7)), DAYS, Window(-6, -1))
        assert got is not None

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
        cov = Coverage(codes=20, universe=1000, events=100, usable=90, span=None)
        assert cov.ratio == pytest.approx(0.02)

    def test_涵蓋率低就是先導測試(self) -> None:
        cov = Coverage(codes=20, universe=1000, events=100, usable=90, span=None)
        assert cov.pilot is True
        assert "先導測試" in cov.describe()

    def test_涵蓋率高就不標先導(self) -> None:
        cov = Coverage(codes=900, universe=1000, events=100, usable=90, span=None)
        assert cov.pilot is False
        assert "先導測試" not in cov.describe()

    def test_剛好在門檻上不算先導(self) -> None:
        cov = Coverage(
            codes=int(1000 * PILOT_BELOW),
            universe=1000,
            events=1,
            usable=1,
            span=None,
        )
        assert cov.pilot is False

    def test_宇集是零時不會除以零(self) -> None:
        cov = Coverage(codes=0, universe=0, events=0, usable=0, span=None)
        assert cov.ratio == 0.0

    def test_被擋掉的事件數看得出來(self) -> None:
        cov = Coverage(codes=5, universe=10, events=100, usable=71, span=None)
        assert "71/100" in cov.describe()

    def test_期間會印出來(self) -> None:
        cov = Coverage(
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


class TestPooled:
    def test_事件組與對照組分開(self) -> None:
        items = [
            _obs("a", 0, 1.0, event=True),
            _obs("a", 10, 2.0, event=False),
        ]
        events, controls = pooled(items, horizon=1)
        assert [o.excess for o in events] == [1.0]
        assert [o.excess for o in controls] == [2.0]

    def test_同一檔之內篩掉重疊窗口(self) -> None:
        items = [_obs("a", i, 1.0, event=True) for i in range(6)]
        events, _ = pooled(items, horizon=3)
        assert len(events) == 2

    def test_不同檔之間不會互相篩掉(self) -> None:
        # a 和 b 的窗口在時間上重疊,但它們是不同的股票,各自獨立
        items = [
            _obs("a", 0, 1.0, event=True),
            _obs("b", 0, 1.0, event=True),
            _obs("c", 0, 1.0, event=True),
        ]
        events, _ = pooled(items, horizon=13)
        assert len(events) == 3

    def test_持有期一時全部保留(self) -> None:
        items = [_obs("a", i, 1.0, event=True) for i in range(5)]
        events, _ = pooled(items, horizon=1)
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
        got = compare_groups("x", self._items(), horizon=1)
        assert got is not None
        assert got.raw.n_event == 12
        assert got.demeaned.n_event == 12

    def test_去期間化會拿掉期間的共同水位(self) -> None:
        # 兩組都隨期間上升,去期間化後那個共同趨勢應該消失
        got = compare_groups("x", self._items(), horizon=1)
        assert got is not None
        assert abs(got.demeaned.median_event) < abs(got.raw.median_event)

    def test_回報事件組的獨立期間數(self) -> None:
        got = compare_groups("x", self._items(), horizon=1)
        assert got is not None
        assert got.periods == 12
        assert got.overstated == pytest.approx(1.0)

    def test_同一期間多筆時高估倍數大於一(self) -> None:
        items = [_obs(c, 0, 1.0 + i, event=True) for i, c in enumerate("abcdef")]
        items += [_obs(c, 0, 0.0, event=False) for c in "ghijkl"]
        got = compare_groups("x", items, horizon=1)
        assert got is not None
        assert got.periods == 1
        assert got.overstated == pytest.approx(6.0)

    def test_樣本太少時回_None(self) -> None:
        assert compare_groups("x", [_obs("a", 0, 1.0, event=True)], 1) is None


class TestReport:
    def _finding(self):
        out: list[Observation] = []
        for period in range(12):
            out.append(_obs("a", period, 5.0, event=True))
            out.append(_obs("b", period, 1.0, event=False))
        return compare_groups("試驗", out, horizon=1)

    def test_涵蓋率一定印在最前面(self) -> None:
        cov = Coverage(codes=20, universe=1000, events=12, usable=12, span=None)
        finding = self._finding()
        assert finding is not None
        text = report([finding], cov)
        assert text.startswith("20/1000")

    def test_先導測試的警告會出現(self) -> None:
        cov = Coverage(codes=20, universe=1000, events=12, usable=12, span=None)
        finding = self._finding()
        assert finding is not None
        assert "先導測試" in report([finding], cov)

    def test_校正後的_p_一定出現(self) -> None:
        cov = Coverage(codes=900, universe=1000, events=12, usable=12, span=None)
        finding = self._finding()
        assert finding is not None
        text = report([finding], cov)
        assert "校正p" in text
        assert "BH 校正後顯著" in text

    def test_沒有檢定時也不會炸(self) -> None:
        cov = Coverage(codes=0, universe=10, events=0, usable=0, span=None)
        assert "沒有可用的檢定" in report([], cov)

    def test_高估倍數會印出來(self) -> None:
        cov = Coverage(codes=2, universe=2, events=12, usable=12, span=None)
        finding = self._finding()
        assert finding is not None
        assert "高估" in report([finding], cov)
