"""漲停買不到、跌停賣不掉 → 順延(Jordan 2026-10-07,#45)。

8 個交易日,處置在 D4 結束 → D5 出關。Timing(entry=-3, exit=-1):原定 D2 收盤買、
D4 收盤賣。前一天收 100 時,漲停是 110、跌停是 90。
"""

from datetime import date

import pandas as pd
import pytest

from src.backtest import Timing, pre_release_run
from src.market import limit_down


DAYS = pd.bdate_range("2026-02-02", periods=8)
TIMING = Timing(entry=-3, exit=-1)
PUNISH = pd.DataFrame(
    [
        {
            "code": "1111",
            "name": "測試股",
            "nth": 1,
            "measure": "第一次處置",
            "start": date(2026, 2, 2),
            "end": DAYS[4].date(),
        }
    ]
)


def _prices(closes: list[float | None]) -> pd.DataFrame:
    """測試股之外再放一檔每天都有成交的,交易日才不會因為測試股停牌而消失。"""
    frames = [
        pd.DataFrame({"day": DAYS, "code": code, "close": series})
        for code, series in (("1111", closes), ("9999", [50.0] * len(DAYS)))
    ]
    out = pd.concat(frames, ignore_index=True)
    return out.assign(open=out.close, high=out.close, low=out.close)


def _limit_downs(start: float, n: int) -> list[float]:
    """從 start 開始連續 n 天跌停的收盤價(照交易所的檔位)。"""
    out = []
    price = start
    for _ in range(n):
        price = limit_down(price)
        out.append(price)
    return out


def _run(closes: list[float | None], timing: Timing = TIMING) -> pd.DataFrame:
    return pre_release_run(PUNISH, _prices(closes), timing=timing)


def test_沒有漲跌停就照原定日期() -> None:
    out = _run([100, 100, 100, 100, 100, 100, 100, 100])
    row = out.iloc[0]
    assert (row["buy_day"], row["sell_day"]) == (DAYS[2].date(), DAYS[4].date())
    assert (row["buy_deferred"], row["sell_deferred"]) == (0, 0)
    assert out.attrs["unfilled"] == 0


def test_買進日收漲停_順延到隔天買() -> None:
    # D2 收 110 = 漲停 → D3 收 112(漲停 121)買得到
    out = _run([100, 100, 110, 112, 112, 112, 112, 112])
    row = out.iloc[0]
    assert row["buy_day"] == DAYS[3].date()
    assert row["buy"] == 112
    assert row["buy_deferred"] == 1


def test_賣出日收跌停_順延到隔天賣() -> None:
    # D4 收 90 = 跌停(前收 100)→ D5 收 85(跌停 81)賣得掉
    out = _run([100, 100, 100, 100, 90, 85, 85, 85])
    row = out.iloc[0]
    assert row["sell_day"] == DAYS[5].date()
    assert row["sell"] == 85
    assert row["sell_deferred"] == 1
    # 順延之後的報酬是真的賣出價算的,不是原定那天的
    assert row["gross"] == pytest.approx((85 / 100 - 1) * 100, abs=0.01)


def test_連續跌停就一路順延() -> None:
    # D4、D5、D6 連三根跌停,D7 只跌一點
    d4, d5, d6 = _limit_downs(100, 3)
    out = _run([100, 100, 100, 100, d4, d5, d6, d6 - 0.1])
    assert out.iloc[0]["sell_day"] == DAYS[7].date()
    assert out.iloc[0]["sell_deferred"] == 3


def test_一路漲停到賣出日都買不到_算沒進場() -> None:
    out = _run([100, 100, 110, 121, 133, 140, 140, 140])
    assert out.empty
    assert out.attrs["unfilled"] == 1
    # 空的也要有欄位,呼叫端才能照常篩選(build_report 的價格路徑就曾因此壞掉)
    assert {"knowable", "truly_released", "excess"} <= set(out.columns)


def test_跌停到資料結束都賣不掉_算成交不了() -> None:
    out = _run([100, 100, 100, 100, *_limit_downs(100, 4)])
    assert out.empty
    assert out.attrs["unfilled"] == 1


def test_停牌沒有價格也順延() -> None:
    out = _run([100, 100, None, 101, 101, 101, 101, 101])
    assert out.iloc[0]["buy_day"] == DAYS[3].date()


def test_收在漲停賣出不受影響() -> None:
    out = _run([100, 100, 100, 100, 110, 110, 110, 110])
    assert out.iloc[0]["sell_day"] == DAYS[4].date()


def test_關掉順延就是原本的算法() -> None:
    old = Timing(entry=-3, exit=-1, defer_limits=False)
    out = _run([100, 100, 110, 112, 90, 85, 85, 85], timing=old)
    row = out.iloc[0]
    assert (row["buy_day"], row["sell_day"]) == (DAYS[2].date(), DAYS[4].date())
    assert (row["buy"], row["sell"]) == (110, 90)


def test_能不能知道用原定的買進日判斷_不是順延後的() -> None:
    # 公告在 D2 當天(盤後)。原定 D2 收盤買 = 用到未來資訊;漲停順延到 D3
    # 之後公告已經出來了,但這筆還是不能算
    punish = PUNISH.assign(announced=DAYS[2].date())
    out = pre_release_run(
        punish, _prices([100, 100, 110, 112, 112, 112, 112, 112]), timing=TIMING
    )
    assert out.iloc[0]["buy_day"] == DAYS[3].date()
    assert not out.iloc[0]["knowable"]
