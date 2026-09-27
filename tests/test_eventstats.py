"""事件研究共用的報酬與統計。"""

from __future__ import annotations

import itertools

import pytest

from src.eventstats import (
    MIN_GROUP,
    adjust,
    compare,
    contemporaneous,
    equal_weight_index,
    excess_return,
    non_overlapping,
)
from src.market import ROUND_TRIP_COST_PCT


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
    def _cmp(self, p: float):
        return compare("x", [p, p + 1, p + 2, p + 3], [0.0, 0.1, 0.2, 0.3])

    def test_校正後的_p_不會比原始小(self) -> None:
        got = adjust([c for c in (self._cmp(1), self._cmp(2)) if c])
        assert all(adj >= c.pvalue - 1e-12 for c, adj in got)

    def test_多個檢定時會被拉高(self) -> None:
        # [#14] 的形狀:單獨看顯著,一起校正就不顯著
        singles = [c for c in [self._cmp(1)] if c]
        many = [c for c in (self._cmp(i) for i in range(1, 11)) if c]
        one = adjust(singles)[0][1]
        batch = max(adj for _, adj in adjust(many))
        assert batch >= one

    def test_只有一個檢定時校正等於沒做(self) -> None:
        only = [c for c in [self._cmp(1)] if c]
        (pair,) = adjust(only)
        assert pair[1] == pytest.approx(pair[0].pvalue)

    def test_空清單回空清單(self) -> None:
        assert adjust([]) == []

    def test_順序不會被打亂(self) -> None:
        items = [c for c in (self._cmp(1), self._cmp(5), self._cmp(9)) if c]
        got = adjust(items)
        assert [c.name for c, _ in got] == [c.name for c in items]


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
