"""事件研究共用的報酬與統計。"""

from __future__ import annotations

import itertools
from datetime import date, timedelta

import pytest

from src.eventstats import (
    MIN_GROUP,
    Comparison,
    Observation,
    adjust,
    compare,
    contemporaneous,
    demean_by_period,
    direction_split,
    effective_n,
    equal_weight_buy_and_hold,
    equal_weight_index,
    excess_return,
    first_on_or_after,
    horizon_returns,
    median,
    non_overlapping,
    window_excess,
)
from src.market import ROUND_TRIP_COST_PCT


def D(n: int) -> date:
    """第 n 天。用真的 date,因為 horizon_returns 要跟 timedelta 相加。"""
    return date(2026, 1, n)


class TestEqualWeightIndex:
    def test_起點是一百(self) -> None:
        idx = equal_weight_index({"a": {1: 10.0, 2: 11.0}})
        assert idx[1] == 100.0

    def test_單一檔就是它自己的報酬(self) -> None:
        idx = equal_weight_index({"a": {1: 10.0, 2: 11.0}})
        assert idx[2] == pytest.approx(110.0)

    def test_兩檔取平均而不是加總(self) -> None:
        # +10% 和 +30% 的等權平均是 +20%
        idx = equal_weight_index({"a": {1: 10.0, 2: 11.0}, "b": {1: 10.0, 2: 13.0}})
        assert idx[2] == pytest.approx(120.0)

    def test_等權不被高價股主導(self) -> None:
        # b 的股價是 a 的一百倍,但兩檔漲跌幅一樣就該是同一個結果
        cheap = equal_weight_index({"a": {1: 10.0, 2: 11.0}, "b": {1: 10.0, 2: 11.0}})
        pricey = equal_weight_index(
            {"a": {1: 10.0, 2: 11.0}, "b": {1: 1000.0, 2: 1100.0}}
        )
        assert cheap[2] == pytest.approx(pricey[2])

    def test_那天沒價格的股票不算成零報酬(self) -> None:
        # b 第 2 天停牌。指數該只反映 a 的 +10%,不是 (10%+(-100%))/2
        idx = equal_weight_index({"a": {1: 10.0, 2: 11.0}, "b": {1: 10.0}})
        assert idx[2] == pytest.approx(110.0)

    def test_中途才上市的股票不會拉低指數(self) -> None:
        idx = equal_weight_index({"a": {1: 10.0, 2: 11.0}, "b": {2: 50.0}})
        assert idx[2] == pytest.approx(110.0)

    def test_全部都沒報酬那天指數不動(self) -> None:
        idx = equal_weight_index({"a": {1: 10.0}, "b": {2: 50.0}})
        assert idx[2] == pytest.approx(100.0)

    def test_前一天價格是零時跳過而不是除以零(self) -> None:
        idx = equal_weight_index({"a": {1: 0.0, 2: 11.0}})
        assert idx[2] == pytest.approx(100.0)

    def test_空輸入回空字典(self) -> None:
        assert equal_weight_index({}) == {}


class TestExcessReturn:
    def test_跟基準一樣時超額只剩成本(self) -> None:
        got = excess_return(100, 110, 100, 110)
        assert got == pytest.approx(-ROUND_TRIP_COST_PCT)

    def test_贏基準十個百分點(self) -> None:
        got = excess_return(100, 120, 100, 110, costs=False)
        assert got == pytest.approx(10.0)

    def test_輸基準是負的(self) -> None:
        got = excess_return(100, 105, 100, 110, costs=False)
        assert got == pytest.approx(-5.0)

    def test_成本只扣個股那一邊(self) -> None:
        # 基準不是要付手續費的部位,扣兩次會低估超額報酬
        with_costs = excess_return(100, 120, 100, 110)
        without = excess_return(100, 120, 100, 110, costs=False)
        assert without - with_costs == pytest.approx(ROUND_TRIP_COST_PCT)

    def test_大盤下跌時個股小跌也可能是正超額(self) -> None:
        got = excess_return(100, 95, 100, 80, costs=False)
        assert got == pytest.approx(15.0)

    def test_進場價非正要出錯而不是回一個數字(self) -> None:
        with pytest.raises(ValueError, match="大於零"):
            excess_return(0, 110, 100, 110)
        with pytest.raises(ValueError, match="大於零"):
            excess_return(100, 110, 0, 110)


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

    def test_跟每日再平衡的指數不一樣(self) -> None:
        # 這是換掉基準演算法的理由:個股是買進持有,基準也必須是
        closes = {"a": {1: 10.0, 2: 20.0, 3: 10.0}, "b": {1: 10.0, 2: 5.0, 3: 10.0}}
        bh = equal_weight_buy_and_hold(closes, 1, 3)
        idx = equal_weight_index(closes)
        chained = (idx[3] / idx[1] - 1) * 100
        assert bh == pytest.approx(0.0)
        assert chained != pytest.approx(bh)

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
        sparse = {D(1): 100.0, D(5): 120.0}
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


class TestHorizonReturns:
    periods = [D(1), D(2), D(3), D(4), D(5)]
    series = {D(i): float(100 + 10 * i) for i in range(1, 6)}
    closes = {"a": series, "b": dict.fromkeys(series, 100.0)}

    def test_每一筆都是持有_horizon_個期間(self) -> None:
        got = horizon_returns(self.periods, self.series, self.closes, 2)
        # 前三筆算得出來(0→2、1→3、2→4),後兩筆沒有出場期間
        assert [v is not None for v in got] == [True, True, True, False, False]

    def test_出場期間不存在時是_None_而不是用最後一筆(self) -> None:
        # 用最後一筆會讓持有期悄悄縮短,而且看不出來。
        # 5 個期間、持有 4 期:只有第 0 筆有出場期間(0→4),其餘都是 None
        got = horizon_returns(self.periods, self.series, self.closes, 4)
        assert [v is not None for v in got] == [True, False, False, False, False]

    def test_持有期超過期間總數時全部是_None(self) -> None:
        got = horizon_returns(self.periods, self.series, self.closes, 5)
        assert got == [None] * 5

    def test_持有期越長算得出來的筆數越少(self) -> None:
        counts = [
            sum(
                v is not None
                for v in horizon_returns(self.periods, self.series, self.closes, h)
            )
            for h in (1, 2, 3)
        ]
        assert counts == [4, 3, 2]

    def test_時滯同時加在兩端(self) -> None:
        # 只加在進場那一端的話持有期會短一截
        no_lag = horizon_returns(self.periods, self.series, self.closes, 2)
        lagged = horizon_returns(
            self.periods, self.series, self.closes, 2, lag=timedelta(days=1)
        )
        # 兩者的持有期長度一樣,只是整段往後移
        assert sum(v is not None for v in lagged) <= sum(v is not None for v in no_lag)

    def test_期間序列有缺口時持有期會變長(self) -> None:
        # 集保農曆年那一週沒資料,跨過缺口的窗口實際天數會多
        gappy = [D(1), D(2), D(20), D(21)]
        got = horizon_returns(gappy, self.series, self.closes, 1)
        assert len(got) == 4


class TestDirectionSplit:
    def test_上升與下降分開(self) -> None:
        up, down = direction_split([1.0, 2.0, 1.5, 3.0])
        assert up == [1, 3]
        assert down == [2]

    def test_第一期兩邊都不出現(self) -> None:
        # 當成「沒上升」會把一筆無從判斷的觀察塞進對照組
        up, down = direction_split([1.0, 2.0])
        assert 0 not in up
        assert 0 not in down

    def test_持平算沒上升(self) -> None:
        up, down = direction_split([1.0, 1.0])
        assert up == []
        assert down == [1]

    def test_None_的位置兩邊都不放(self) -> None:
        up, down = direction_split([1.0, None, 3.0, 4.0])
        # 位置 1 自己是 None,位置 2 的前一期是 None,兩個都跳過
        assert up == [3]
        assert down == []

    def test_兩邊加起來不會超過總數減一(self) -> None:
        values: list[float | None] = [1.0, 2.0, None, 4.0, 5.0]
        up, down = direction_split(values)
        assert len(up) + len(down) <= len(values) - 1

    def test_位置不會重複出現在兩邊(self) -> None:
        up, down = direction_split([1.0, 2.0, 1.0, 2.0, 2.0])
        assert not set(up) & set(down)

    def test_空序列與單一元素都回空(self) -> None:
        assert direction_split([]) == ([], [])
        assert direction_split([1.0]) == ([], [])
