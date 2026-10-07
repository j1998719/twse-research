"""事件研究共用的報酬與統計。"""

from __future__ import annotations

import itertools
from datetime import date

import pytest

from src.eventstats import (
    MIN_GROUP,
    Comparison,
    Observation,
    adjust,
    clustered_ci,
    compare,
    contemporaneous,
    demean_by_period,
    effective_n,
    equal_weight_buy_and_hold,
    first_on_or_after,
    median,
    non_overlapping,
    window_excess,
)
from src.market import ROUND_TRIP_COST_PCT


def D(n: int) -> date:
    """第 n 天。用真的 date,因為 horizon_returns 要跟 timedelta 相加。"""
    return date(2026, 1, n)


class TestNonOverlapping:
    def test_相隔夠遠的全部留下(self) -> None:
        assert non_overlapping([0, 5, 10], 4) == [0, 5, 10]

    def test_剛好等於持有期算不重疊(self) -> None:
        assert non_overlapping([0, 4], 4) == [0, 4]

    def test_差一期就重疊要剔掉(self) -> None:
        assert non_overlapping([0, 3], 4) == [0]

    def test_連續每期都有事件時按持有期取樣(self) -> None:
        # 這就是 [#20] 的情況:36 個連續週次、13 週持有期
        assert non_overlapping(range(36), 13) == [0, 13, 26]

    def test_持有期一時全部保留(self) -> None:
        assert non_overlapping([0, 1, 2], 1) == [0, 1, 2]

    def test_輸入沒排序也處理得對(self) -> None:
        assert non_overlapping([10, 0, 5], 4) == [0, 5, 10]

    def test_重複的位置只留一個(self) -> None:
        assert non_overlapping([0, 0, 0], 4) == [0]

    def test_空輸入回空清單(self) -> None:
        assert non_overlapping([], 4) == []

    def test_持有期小於一要出錯(self) -> None:
        with pytest.raises(ValueError, match="至少是 1"):
            non_overlapping([0, 1], 0)

    def test_挑出來的一定互不重疊(self) -> None:
        kept = non_overlapping([0, 1, 2, 7, 8, 20, 21, 22], 5)
        assert all(b - a >= 5 for a, b in itertools.pairwise(kept))


class TestCompare:
    big = [10.0, 12.0, 14.0, 16.0, 18.0]
    small = [1.0, 2.0, 3.0, 4.0, 5.0]

    def test_算出中位數與勝率(self) -> None:
        got = compare("x", self.big, self.small)
        assert got is not None
        assert got.median_event == 14.0
        assert got.median_control == 3.0
        assert got.win_rate_event == 1.0

    def test_偶數筆的中位數取中間兩筆平均(self) -> None:
        got = compare("x", [1.0, 2.0, 3.0, 4.0], self.small)
        assert got is not None
        assert got.median_event == 2.5

    def test_勝率只看大於零(self) -> None:
        got = compare("x", [-1.0, 0.0, 1.0, 2.0], self.small)
        assert got is not None
        assert got.win_rate_event == 0.5

    def test_差很多的兩組會顯著(self) -> None:
        got = compare("x", self.big, self.small)
        assert got is not None
        assert got.pvalue < 0.05

    def test_一樣的兩組不顯著(self) -> None:
        got = compare("x", self.big, list(self.big))
        assert got is not None
        assert got.pvalue > 0.05

    def test_雙尾檢定_反向差異一樣被抓到(self) -> None:
        # 單尾會漏掉「事件組明顯更差」這種情況,那也是資訊
        forward = compare("x", self.big, self.small)
        reverse = compare("x", self.small, self.big)
        assert forward is not None
        assert reverse is not None
        assert forward.pvalue == pytest.approx(reverse.pvalue)

    def test_樣本太少回_None_而不是一個假的檢定(self) -> None:
        few = [1.0] * (MIN_GROUP - 1)
        assert compare("x", few, self.small) is None
        assert compare("x", self.big, few) is None

    def test_剛好到門檻就做(self) -> None:
        enough = [1.0, 2.0, 3.0, 4.0]
        assert len(enough) == MIN_GROUP
        assert compare("x", enough, self.small) is not None

    def test_不重疊的標記會傳下去(self) -> None:
        got = compare("x", self.big, self.small, deduped=True)
        assert got is not None
        assert got.deduped is True

    def test_預設沒有標記為不重疊(self) -> None:
        got = compare("x", self.big, self.small)
        assert got is not None
        assert got.deduped is False


class TestAdjust:
    def _cmp(self, p: float, name: str = "x"):
        return compare(name, [p, p + 1, p + 2, p + 3], [0.0, 0.1, 0.2, 0.3])

    def test_校正後的_p_不會比原始小(self) -> None:
        got = adjust([c for c in (self._cmp(1), self._cmp(2)) if c])
        assert all(adj >= c.pvalue - 1e-12 for c, adj in got)

    def test_算出來的是_BH_而不是_Bonferroni(self) -> None:
        # 只斷言「校正後變大」的話,Bonferroni、Holm、甚至全部回 1.0 的爛
        # 實作都會過。BH 對 [0.01, 0.02, 0.03] 的答案是 [0.03, 0.03, 0.03];
        # Bonferroni 會給 [0.03, 0.06, 0.09]
        got = _adjust_raw([0.01, 0.02, 0.03])
        assert got == pytest.approx([0.03, 0.03, 0.03])

    def test_BH_不會把最大的那個拉到超過一(self) -> None:
        assert max(_adjust_raw([0.5, 0.9, 0.95])) <= 1.0

    def test_只有一個檢定時校正等於沒做(self) -> None:
        only = [c for c in [self._cmp(1)] if c]
        (pair,) = adjust(only)
        assert pair[1] == pytest.approx(pair[0].pvalue)

    def test_空清單回空清單(self) -> None:
        assert adjust([]) == []

    def test_順序不會被打亂(self) -> None:
        # 名字要各不相同,否則就算 adjust 把順序打亂也測不出來
        items = [
            c for c in (self._cmp(1, "a"), self._cmp(5, "b"), self._cmp(9, "c")) if c
        ]
        got = adjust(items)
        assert [c.name for c, _ in got] == ["a", "b", "c"]


class TestContemporaneous:
    def test_完全同向是正一(self) -> None:
        r, _ = contemporaneous([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
        assert r == pytest.approx(1.0)

    def test_完全反向是負一(self) -> None:
        r, _ = contemporaneous([1, 2, 3, 4, 5], [5, 4, 3, 2, 1])
        assert r == pytest.approx(-1.0)

    def test_用的是等級相關_不受非線性影響(self) -> None:
        # 立方是單調的,Spearman 應該還是 1,Pearson 不會
        r, _ = contemporaneous([1, 2, 3, 4, 5], [1, 8, 27, 64, 125])
        assert r == pytest.approx(1.0)

    def test_強相關會給出小的_p(self) -> None:
        _, p = contemporaneous(list(range(10)), list(range(10)))
        assert p < 0.01


def _adjust_raw(pvalues: list[float]) -> list[float]:
    """繞過 Comparison,直接對一串 p 值做校正,方便釘住 BH 的實際數值。"""
    fake = [
        Comparison(
            name=str(i),
            n_event=5,
            n_control=5,
            median_event=0.0,
            median_control=0.0,
            win_rate_event=0.0,
            win_rate_control=0.0,
            pvalue=p,
            deduped=False,
        )
        for i, p in enumerate(pvalues)
    ]
    return [adj for _, adj in adjust(fake)]


class TestFirstOnOrAfter:
    series = {1: 10.0, 3: 30.0, 5: 50.0}

    def test_當天就有值時回當天(self) -> None:
        assert first_on_or_after(self.series, 3) == (3, 30.0)

    def test_當天沒值時回之後最近的(self) -> None:
        assert first_on_or_after(self.series, 2) == (3, 30.0)

    def test_全部都在之前回_None_而不是最後一筆(self) -> None:
        # 回最後一筆會讓出場日落在窗口外面,而且看不出來
        assert first_on_or_after(self.series, 6) is None

    def test_比最早的還早時回最早的(self) -> None:
        assert first_on_or_after(self.series, 0) == (1, 10.0)

    def test_空序列回_None(self) -> None:
        assert first_on_or_after({}, 1) is None


class TestEqualWeightBuyAndHold:
    def test_單一檔就是它自己的報酬(self) -> None:
        got = equal_weight_buy_and_hold({"a": {1: 10.0, 2: 11.0}}, 1, 2)
        assert got == pytest.approx(10.0)

    def test_兩檔取平均(self) -> None:
        closes = {"a": {1: 10.0, 2: 11.0}, "b": {1: 10.0, 2: 13.0}}
        assert equal_weight_buy_and_hold(closes, 1, 2) == pytest.approx(20.0)

    def test_窗口端點缺價格的股票不算(self) -> None:
        closes = {"a": {1: 10.0, 2: 11.0}, "b": {1: 10.0}}
        assert equal_weight_buy_and_hold(closes, 1, 2) == pytest.approx(10.0)

    def test_是買進持有而不是每日再平衡(self) -> None:
        # a 漲一倍再跌回來、b 腰斬再漲回來 —— 買進持有的答案是 0%。
        # 每日再平衡會一直砍贏家補輸家,答案不會是 0。個股那一邊是買進持有,
        # 基準也必須是,不然長窗口上會有固定方向的偏差
        closes = {
            "a": {D(1): 10.0, D(2): 20.0, D(3): 10.0},
            "b": {D(1): 10.0, D(2): 5.0, D(3): 10.0},
        }
        assert equal_weight_buy_and_hold(closes, D(1), D(3)) == pytest.approx(0.0)

    def test_中間那幾天的價格完全不影響結果(self) -> None:
        # 買進持有只看兩端。這是它和再平衡最直接的區別
        calm = {"a": {D(1): 10.0, D(2): 10.0, D(3): 11.0}}
        wild = {"a": {D(1): 10.0, D(2): 99.0, D(3): 11.0}}
        assert equal_weight_buy_and_hold(calm, D(1), D(3)) == pytest.approx(
            equal_weight_buy_and_hold(wild, D(1), D(3))
        )

    def test_沒有任何股票兩端都有價格時回_None(self) -> None:
        assert equal_weight_buy_and_hold({"a": {1: 10.0}}, 1, 2) is None

    def test_起點價格是零時跳過(self) -> None:
        assert equal_weight_buy_and_hold({"a": {1: 0.0, 2: 10.0}}, 1, 2) is None


def _obs(code: str, period: int, excess: float, *, event: bool) -> Observation:
    return Observation(code=code, period=period, excess=excess, is_event=event)


class TestDemeanByPeriod:
    def test_同一期間的中位數被扣掉(self) -> None:
        items = [
            _obs("a", 1, 10.0, event=True),
            _obs("b", 1, 20.0, event=False),
            _obs("c", 1, 30.0, event=False),
        ]
        got = demean_by_period(items)
        assert [o.excess for o in got] == pytest.approx([-10.0, 0.0, 10.0])

    def test_不同期間各自扣自己的中位數(self) -> None:
        items = [
            _obs("a", 1, 100.0, event=True),
            _obs("b", 1, 100.0, event=False),
            _obs("c", 2, 5.0, event=True),
            _obs("d", 2, 5.0, event=False),
        ]
        got = demean_by_period(items)
        assert [o.excess for o in got] == pytest.approx([0.0, 0.0, 0.0, 0.0])

    def test_期間之間的水位差會被消掉(self) -> None:
        # 這就是要修的問題:事件組全在好的期間、對照組全在壞的期間
        items = [
            _obs("a", 1, 20.0, event=True),
            _obs("b", 1, 20.0, event=True),
            _obs("c", 2, -20.0, event=False),
            _obs("d", 2, -20.0, event=False),
        ]
        got = demean_by_period(items)
        events = [o.excess for o in got if o.is_event]
        controls = [o.excess for o in got if not o.is_event]
        assert median(events) == pytest.approx(median(controls))

    def test_其他欄位不會被動到(self) -> None:
        (got,) = demean_by_period([_obs("a", 7, 1.0, event=True)])
        assert (got.code, got.period, got.is_event) == ("a", 7, True)

    def test_每期只有一筆時全部歸零(self) -> None:
        items = [_obs("a", 1, 5.0, event=True), _obs("b", 2, -5.0, event=False)]
        assert [o.excess for o in demean_by_period(items)] == pytest.approx([0.0, 0.0])

    def test_空輸入回空清單(self) -> None:
        assert demean_by_period([]) == []


class TestEffectiveN:
    def test_數的是不同期間而不是筆數(self) -> None:
        items = [
            _obs("a", 1, 0.0, event=True),
            _obs("b", 1, 0.0, event=True),
            _obs("c", 2, 0.0, event=True),
        ]
        assert len(items) == 3
        assert effective_n(items) == 2

    def test_全部同一期間時只有一個(self) -> None:
        items = [_obs(c, 1, 0.0, event=True) for c in "abcdefghij"]
        assert effective_n(items) == 1

    def test_空輸入是零(self) -> None:
        assert effective_n([]) == 0


class TestWindowExcess:
    """個股對宇集買進持有等權的超額報酬。"""

    closes = {
        "a": {D(1): 100.0, D(2): 110.0, D(3): 120.0},
        "b": {D(1): 100.0, D(2): 100.0, D(3): 100.0},
    }

    def test_贏基準的部分(self) -> None:
        # a 從 100 到 120 = +20%;基準是 a 和 b 的平均 = +10%
        got = window_excess(self.closes["a"], self.closes, D(1), D(3), costs=False)
        assert got == pytest.approx(10.0)

    def test_輸基準是負的(self) -> None:
        got = window_excess(self.closes["b"], self.closes, D(1), D(3), costs=False)
        assert got == pytest.approx(-10.0)

    def test_成本只扣個股那一邊(self) -> None:
        plain = window_excess(self.closes["a"], self.closes, D(1), D(3), costs=False)
        costed = window_excess(self.closes["a"], self.closes, D(1), D(3))
        assert plain is not None
        assert costed is not None
        assert plain - costed == pytest.approx(ROUND_TRIP_COST_PCT)

    def test_指定的日期沒開盤就用之後最近的(self) -> None:
        # 105 而不是 120:漲幅超過 10% 會被當成漲停買不到(#58),這裡只測日期往後滑
        sparse = {D(1): 100.0, D(5): 105.0}
        closes = {"x": sparse}
        got = window_excess(sparse, closes, D(2), D(4), costs=False)
        # 進場滑到 D(5)、出場也滑到 D(5),同一天進出 = 0%
        assert got == pytest.approx(0.0)

    def test_出場日之後沒有價格就回_None(self) -> None:
        got = window_excess(self.closes["a"], self.closes, D(1), D(9))
        assert got is None

    def test_基準算不出來時回_None_而不是當成零(self) -> None:
        # 當成 0 會把個股的原始報酬誤報成超額報酬
        lonely = {D(1): 100.0, D(9): 200.0}
        got = window_excess(lonely, {"x": lonely}, D(1), D(9))
        assert got is not None  # 自己就是宇集,算得出來
        got2 = window_excess(lonely, {"y": {D(1): 1.0}}, D(1), D(9))
        assert got2 is None


class TestClusteredCi:
    """按群集重抽 —— 事件叢聚時把它們當獨立樣本會把 p 算得太小。"""

    def test_明確為正的資料下界也為正(self) -> None:
        values = [5.0] * 40
        clusters = [f"m{i % 10}" for i in range(40)]
        low, _high, nonpos = clustered_ci(values, clusters, draws=200)
        assert low > 0
        assert nonpos == 0.0

    def test_明確為負的資料上界也為負(self) -> None:
        values = [-5.0] * 40
        clusters = [f"m{i % 10}" for i in range(40)]
        _low, high, nonpos = clustered_ci(values, clusters, draws=200)
        assert high < 0
        assert nonpos == 1.0

    def test_下界不會超過上界(self) -> None:
        values = [float(i % 7) - 3 for i in range(80)]
        clusters = [f"m{i % 12}" for i in range(80)]
        low, high, _ = clustered_ci(values, clusters, draws=200)
        assert low <= high

    def test_全部在同一個群集時區間會很寬(self) -> None:
        # 群集少代表資訊少。這正是要表達的事
        many = clustered_ci([1.0, 5.0] * 20, [f"m{i}" for i in range(40)], draws=200)
        few = clustered_ci([1.0, 5.0] * 20, ["m"] * 40, draws=200)
        assert few == (0.0, 0.0, 1.0)  # 群集不足,不做拔靴
        assert many[0] > 0

    def test_同一個群集裡的相關性有被保留(self) -> None:
        # 同一個月的觀察要一起被抽中或一起落選。如果是逐筆重抽,
        # 40 筆的區間會比 4 個群集窄很多
        values = [10.0] * 20 + [-10.0] * 20
        by_cluster = ["up"] * 20 + ["down"] * 20
        low, high, _ = clustered_ci(values, by_cluster, draws=200)
        # 兩個群集不足門檻
        assert (low, high) == (0.0, 0.0)

    def test_可重現_同樣的輸入給同樣的答案(self) -> None:
        values = [float(i % 5) for i in range(60)]
        clusters = [f"m{i % 10}" for i in range(60)]
        first = clustered_ci(values, clusters, draws=200)
        second = clustered_ci(values, clusters, draws=200)
        assert first == second

    def test_不同的_seed_給不同的答案(self) -> None:
        values = [float(i % 5) for i in range(60)]
        clusters = [f"m{i % 10}" for i in range(60)]
        a = clustered_ci(values, clusters, draws=200, seed=1)
        b = clustered_ci(values, clusters, draws=200, seed=2)
        assert a != b

    def test_長度不一致要出錯(self) -> None:
        with pytest.raises(ValueError, match="zip"):
            clustered_ci([1.0, 2.0], ["m"], draws=10)
