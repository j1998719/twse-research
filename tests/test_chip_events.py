"""籌碼事件(#60,事前登記見 issue)。

- H1 / H2:投信 / 外資連續 5 個交易日買超,事件日 = 剛好連到第 5 天那天
- H3:過去 20 日股價漲 ≥ 10% 而且融資餘額減少 ≥ 10%
- H4:券資比 ≥ 30% 而且融券餘額比 5 日前多
- 都只算「第一次」:同一檔前 60 個交易日內出現過同一種條件就不算
"""

import pandas as pd
import pytest

from src.events.chips import first_only, rally_on_margin_cut, short_squeeze, streak


DAYS = pd.bdate_range("2026-01-05", periods=120)


def _flows(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"day": DAYS[: len(values)], "code": "A", "trust": values})


def test_連續_5_天買超_第_5_天是事件日() -> None:
    got = streak(_flows([1, 1, 1, 1, 1, 1, 1]), "trust", days=DAYS)
    assert got == [("A", DAYS[4])]


def test_中間斷掉就重算() -> None:
    got = streak(_flows([1, 1, 1, 0, 1, 1, 1, 1, 1]), "trust", days=DAYS)
    assert got == [("A", DAYS[8])]


def test_賣超或零都不算買超() -> None:
    assert streak(_flows([1, 1, -5, 1, 1, 1, 1]), "trust", days=DAYS) == []


def test_只算第一次_前_60_個交易日內有過就不算() -> None:
    hits = [("A", DAYS[10]), ("A", DAYS[50]), ("A", DAYS[71]), ("B", DAYS[50])]
    # A 的 DAYS[50] 離 DAYS[10] 只有 40 天 → 不算;DAYS[71] 離 DAYS[10] 61 天,
    # 但離 DAYS[50] 只有 21 天 —— 看的是「條件出現過」,DAYS[50] 雖然被丟掉,
    # 條件確實出現過 → 也不算
    assert first_only(hits, DAYS) == [("A", DAYS[10]), ("B", DAYS[50])]


def test_只算第一次_被丟掉的那次也算出現過() -> None:
    hits = [("A", DAYS[0]), ("A", DAYS[50]), ("A", DAYS[100])]
    # DAYS[100] 離 DAYS[50] 50 天(條件出現過),所以也不算
    assert first_only(hits, DAYS) == [("A", DAYS[0])]


def test_籌碼沉澱_股價漲_融資減() -> None:
    closes = pd.DataFrame({"A": [100.0] * 20 + [111.0] * 5}, index=DAYS[:25])
    margin = pd.DataFrame({"A": [1000.0] * 20 + [890.0] * 5}, index=DAYS[:25])
    # 第 20 天:比 20 天前漲 11%、融資少 11% → 事件
    assert rally_on_margin_cut(closes, margin) == [("A", DAYS[20])]


def test_籌碼沉澱_只漲沒減融資不算() -> None:
    closes = pd.DataFrame({"A": [100.0] * 20 + [111.0] * 5}, index=DAYS[:25])
    margin = pd.DataFrame({"A": [1000.0] * 25}, index=DAYS[:25])
    assert rally_on_margin_cut(closes, margin) == []


def test_軋空_券資比_30_趴以上而且融券增加() -> None:
    margin = pd.DataFrame({"A": [1000.0] * 10}, index=DAYS[:10])
    short = pd.DataFrame({"A": [200.0] * 5 + [350.0] * 5}, index=DAYS[:10])
    # DAYS[5]:券資比 35%,融券比 5 日前(200)多 → 事件;之後融券沒有再增加
    assert short_squeeze(margin, short) == [("A", DAYS[5])]


def test_軋空_券資比不夠不算() -> None:
    margin = pd.DataFrame({"A": [1000.0] * 10}, index=DAYS[:10])
    short = pd.DataFrame({"A": [100.0] * 5 + [250.0] * 5}, index=DAYS[:10])
    assert short_squeeze(margin, short) == []


def test_快取版的超額報酬跟框架的_window_excess_一樣() -> None:
    from datetime import date

    from src.eventstats import window_excess
    from src.run_chip_signals import Excess

    days = [date(2026, 3, d) for d in range(2, 10)]
    a = dict(
        zip(days, [100.0, 110.0, 111.0, 113.0, 112.0, 99.0, 95.0, 96.0], strict=True)
    )
    b = dict(zip(days, [50.0, 51.0, 52.0, 50.0, 49.0, 50.0, 51.0, 53.0], strict=True))
    closes = {"A": a, "B": b}
    # 進場日漲停(順延)、出場日跌停(順延)都要一樣
    for entry, exit_ in ((days[1], days[5]), (days[0], days[3]), (days[2], days[7])):
        assert Excess(closes)("A", entry, exit_) == pytest.approx(
            window_excess(a, closes, entry, exit_)
        )


def test_安慰劑_隨機挑_而且可以重現() -> None:
    from src.run_chip_signals import placebo_hits

    days = pd.bdate_range("2026-01-05", periods=40)
    a = placebo_hits(["A", "B", "C"], days, 50, seed=1)
    assert a == placebo_hits(["A", "B", "C"], days, 50, seed=1)
    assert len(a) == 50
    assert {c for c, _ in a} <= {"A", "B", "C"}
    assert all(d in days for _, d in a)


def test_還沒上市的日期_不是報酬為零而是算不出來() -> None:
    # 安慰劑會抽到還沒上市的日期:順延會把進場和出場都推到上市第一天,算成 0% 再扣成本
    # = 剛好 −0.585%。可轉債的安慰劑有 13.7% 是這種假的觀察值(#62 抓到的)
    from datetime import date

    from src.eventstats import window_excess
    from src.run_chip_signals import Excess

    late = {date(2024, 6, 12): 100.0, date(2024, 6, 13): 101.0}
    other = {date(2016, 5, d): 50.0 for d in range(2, 30)} | {
        date(2024, 6, 12): 50.0,
        date(2024, 6, 13): 50.0,
    }
    closes = {"N": late, "O": other}
    assert Excess(closes)("N", date(2016, 5, 9), date(2016, 6, 6)) is None
    assert window_excess(late, closes, date(2016, 5, 9), date(2016, 6, 6)) is None
