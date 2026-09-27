"""大戶籌碼的事件定義。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.dispersion import DROP_PP, LOOKBACK, signals, triggered
from src.tdcc import BIG_BAND, Band, Week


def _week(i: int, pct: float, holders: int) -> Week:
    """第 i 週。股數隨便給,這些測試只看比例和股東人數。"""
    return Week(
        day=date(2026, 1, 5) + timedelta(weeks=i),
        code="9999",
        bands={
            BIG_BAND: Band(people=50, shares=1_000_000, pct=pct),
            "total": Band(people=holders, shares=2_000_000, pct=100.0),
        },
    )


def _flat(n: int, pct: float = 50.0, holders: int = 100_000) -> list[Week]:
    return [_week(i, pct, holders) for i in range(n)]


class TestSignalsWindow:
    def test_歷史不足的週次不會出現在結果裡(self) -> None:
        # 回報「沒觸發」會讓早期週次看起來是乾淨的對照組,那是假的
        assert signals(_flat(LOOKBACK)) == []
        assert len(signals(_flat(LOOKBACK + 1))) == 1

    def test_每多一週就多一個判斷(self) -> None:
        assert len(signals(_flat(LOOKBACK + 5))) == 5

    def test_高點不含當週(self) -> None:
        # 含當週的話當週永遠是自己的高點,回落幅度恆為零
        weeks = [*_flat(LOOKBACK, pct=60.0), _week(LOOKBACK, 50.0, 100000)]
        (sig,) = signals(weeks)
        assert sig.drop_from_peak == 10.0

    def test_順序打亂也會先排好(self) -> None:
        weeks = [*_flat(LOOKBACK, pct=60.0), _week(LOOKBACK, 50.0, 100000)]
        assert signals(list(reversed(weeks))) == signals(weeks)


class TestBigRolledOver:
    def test_回落超過門檻就觸發(self) -> None:
        weeks = [*_flat(LOOKBACK, pct=55.0), _week(LOOKBACK, 52.0, 100000)]
        (sig,) = signals(weeks)
        assert sig.big_rolled_over is True
        assert sig.drop_from_peak == 3.0

    def test_剛好等於門檻算觸發(self) -> None:
        weeks = [*_flat(LOOKBACK, pct=55.0), _week(LOOKBACK, 55.0 - DROP_PP, 100000)]
        (sig,) = signals(weeks)
        assert sig.big_rolled_over is True

    def test_差一點點不觸發(self) -> None:
        weeks = [*_flat(LOOKBACK, pct=55.0), _week(LOOKBACK, 53.5, 100000)]
        (sig,) = signals(weeks)
        assert sig.big_rolled_over is False

    def test_比例上升時不觸發而且回落幅度是負的(self) -> None:
        weeks = [*_flat(LOOKBACK, pct=50.0), _week(LOOKBACK, 55.0, 100000)]
        (sig,) = signals(weeks)
        assert sig.big_rolled_over is False
        assert sig.drop_from_peak == -5.0

    def test_比的是前期高點而不是前一週(self) -> None:
        # 高點在窗口開頭,之後一路下滑 —— 跟前一週比只差 1,跟高點差 4
        weeks = [_week(i, 58.0 - i, 100_000) for i in range(LOOKBACK + 1)]
        (sig,) = signals(weeks)
        assert sig.drop_from_peak == float(LOOKBACK)
        assert sig.big_rolled_over is True

    def test_高點滑出窗口之後就不算了(self) -> None:
        # 第 0 週是 60,之後都是 50。窗口滑過去以後高點變成 50,回落歸零
        weeks = [_week(0, 60.0, 100_000)] + [
            _week(i, 50.0, 100_000) for i in range(1, LOOKBACK + 3)
        ]
        got = signals(weeks)
        assert got[0].drop_from_peak == 10.0
        assert got[-1].drop_from_peak == 0.0
        assert got[-1].big_rolled_over is False


class TestHoldersPeaked:
    def test_創新高就觸發(self) -> None:
        weeks = [*_flat(LOOKBACK, holders=100000), _week(LOOKBACK, 50.0, 120000)]
        (sig,) = signals(weeks)
        assert sig.holders_peaked is True

    def test_持平不算新高(self) -> None:
        weeks = [*_flat(LOOKBACK, holders=100000), _week(LOOKBACK, 50.0, 100000)]
        (sig,) = signals(weeks)
        assert sig.holders_peaked is False

    def test_下降不算新高(self) -> None:
        weeks = [*_flat(LOOKBACK, holders=100000), _week(LOOKBACK, 50.0, 90000)]
        (sig,) = signals(weeks)
        assert sig.holders_peaked is False


class TestDistributing:
    def test_兩個都成立才算出貨(self) -> None:
        weeks = [
            *_flat(LOOKBACK, pct=55.0, holders=100000),
            _week(LOOKBACK, 52.0, 120000),
        ]
        (sig,) = signals(weeks)
        assert sig.distributing is True

    def test_只有大戶回落不算(self) -> None:
        weeks = [
            *_flat(LOOKBACK, pct=55.0, holders=100000),
            _week(LOOKBACK, 52.0, 90000),
        ]
        (sig,) = signals(weeks)
        assert sig.big_rolled_over is True
        assert sig.distributing is False

    def test_只有散戶湧入不算(self) -> None:
        weeks = [
            *_flat(LOOKBACK, pct=55.0, holders=100000),
            _week(LOOKBACK, 55.0, 120000),
        ]
        (sig,) = signals(weeks)
        assert sig.holders_peaked is True
        assert sig.distributing is False


class TestMissingWeeks:
    def test_讀不到大戶的週次排除掉(self) -> None:
        weeks = _flat(LOOKBACK + 1)
        weeks.insert(3, Week(day=date(2026, 2, 1), code="9999", bands={}))
        # 排除之後剩 LOOKBACK+1 週,只產生一個判斷
        assert len(signals(weeks)) == 1

    def test_沒有合計那一列的週次也排除(self) -> None:
        bare = Week(
            day=date(2026, 2, 1),
            code="9999",
            bands={BIG_BAND: Band(people=50, shares=1, pct=50.0)},
        )
        weeks = [*_flat(LOOKBACK + 1), bare]
        assert len(signals(weeks)) == 1

    def test_全部都讀不到就回空清單(self) -> None:
        assert signals([Week(day=date(2026, 2, 1), code="x", bands={})]) == []

    def test_沒有資料時回空清單(self) -> None:
        assert signals([]) == []


class TestTriggered:
    def test_挑出各個訊號成立的週次(self) -> None:
        weeks = [
            *_flat(LOOKBACK, pct=55.0, holders=100000),
            _week(LOOKBACK, 52.0, 120000),
            _week(LOOKBACK + 1, 55.0, 90000),
        ]
        got = signals(weeks)
        assert len(triggered(got, "big_rolled_over")) == 1
        assert len(triggered(got, "holders_peaked")) == 1
        assert len(triggered(got, "distributing")) == 1

    def test_打錯訊號名稱要出錯而不是回空清單(self) -> None:
        # 回空清單的話,打錯字會變成「零個事件」這種看起來合理的結果
        with pytest.raises(ValueError, match="沒有這個訊號"):
            triggered([], "big_rolled_ovr")


class TestMissingWeeksAffectLookback:
    """讀不到的週次被排除後,剩下的當成連續 —— 回看窗會往更早伸。

    這是 _usable 的文件裡寫明的行為,但沒有測試釘住。實際資料上 20 檔一週
    都沒丟,所以目前成本是零;哪天遇到歷史稀疏的股票就會有差。
    """

    def test_中途缺一週會把更舊的觀察拉進回看窗(self) -> None:
        # 第 0 週是 60%,之後都是 50%。正常情況下第 9 週的回看窗是第 1-8 週,
        # 高點 50、回落 0。但如果第 4 週讀不到,窗口就往前伸到第 0 週,
        # 高點變成 60、回落 10
        clean = [_week(0, 60.0, 100_000)] + [
            _week(i, 50.0, 100_000) for i in range(1, LOOKBACK + 2)
        ]
        assert signals(clean)[-1].drop_from_peak == 0.0

        holed = list(clean)
        holed[4] = Week(day=clean[4].day, code="9999", bands={})
        # 少一週之後總數剛好是 LOOKBACK+1,只剩一個判斷,而且看得到第 0 週
        (sig,) = signals(holed)
        assert sig.drop_from_peak == 10.0

    def test_排除掉的週次不會被當成零(self) -> None:
        # 當成 0% 的話回落會變成 50 個百分點,憑空造出一個巨大的轉折
        weeks = [_week(i, 50.0, 100_000) for i in range(LOOKBACK + 2)]
        weeks[3] = Week(day=weeks[3].day, code="9999", bands={})
        assert all(s.drop_from_peak == 0.0 for s in signals(weeks))
