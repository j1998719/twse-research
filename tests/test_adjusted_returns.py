"""事件研究的報酬要還原持有期間的除權息、減資、面額變更(#59)。

原本用未還原股價:除息那天價格往下跳,算成虧損(股息沒算進來);減資那天
價格往上跳,算成假獲利(5301 寶得利 +38.5%、3308 聯德 +39.5%)。
還原的方式跟均線一樣:因子 = 參考價 / 前一日收盤,買價乘上持有期間
(買進日之後、賣出日當天以前)所有因子的連乘。
"""

from datetime import date

import pandas as pd
import pytest

from src.disposition_study import Timing, pre_release_run


DAYS = pd.bdate_range("2026-02-02", periods=8)
TIMING = Timing(entry=-3, exit=-1)  # D2 收盤買、D4 收盤賣
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


def _prices(closes: list[float]) -> pd.DataFrame:
    frames = [
        pd.DataFrame({"day": DAYS, "code": code, "close": series})
        for code, series in (("1111", closes), ("9999", [50.0] * len(DAYS)))
    ]
    out = pd.concat(frames, ignore_index=True)
    return out.assign(open=out.close, high=out.close, low=out.close)


def _actions(day: int, factor: float, code: str = "1111") -> pd.DataFrame:
    return pd.DataFrame({"code": [code], "day": [DAYS[day]], "factor": [factor]})


def _gross(closes: list[float], actions: pd.DataFrame | None) -> float:
    out = pre_release_run(PUNISH, _prices(closes), timing=TIMING, actions=actions)
    return float(out.iloc[0]["gross"])


CLOSES = [100.0, 100.0, 100.0, 95.0, 95.0, 95.0, 95.0, 95.0]


def test_沒給還原因子就跟以前一樣() -> None:
    assert _gross(CLOSES, None) == pytest.approx(-5.0)


def test_持有期間除息_股息加回來() -> None:
    # D3 除息,參考價 / 前收 = 0.9:買價 100 還原成 90,賣 95 → +5.56%
    assert _gross(CLOSES, _actions(3, 0.9)) == pytest.approx(
        (95 / 90 - 1) * 100, abs=0.01
    )


def test_持有期間減資_假獲利扣掉() -> None:
    # D3 減資,價格翻倍(因子 2):買 100 還原成 200,賣 210 → +5%
    closes = [100.0, 100.0, 100.0, 210.0, 210.0, 210.0, 210.0, 210.0]
    assert _gross(closes, _actions(3, 2.0)) == pytest.approx(5.0)


def test_賣出日當天的事件要算_買進日當天的不算() -> None:
    # 賣出日 D4 除息:收盤賣的已經是除息後的價 → 要還原
    assert _gross(CLOSES, _actions(4, 0.9)) == pytest.approx(
        (95 / 90 - 1) * 100, abs=0.01
    )
    # 買進日 D2 除息:收盤買到的就是除息後的價 → 不還原
    assert _gross(CLOSES, _actions(2, 0.9)) == pytest.approx(-5.0)


def test_別檔的事件不影響() -> None:
    assert _gross(CLOSES, _actions(3, 0.9, code="2222")) == pytest.approx(-5.0)


def test_持有期間有兩個事件_因子相乘() -> None:
    actions = pd.concat([_actions(3, 0.9), _actions(4, 0.5)], ignore_index=True)
    assert _gross(CLOSES, actions) == pytest.approx(
        (95 / (100 * 0.45) - 1) * 100, abs=0.01
    )


def test_框架的收盤序列可以還原() -> None:
    from src.run_wholemarket import closes_by_code

    prices = _prices(CLOSES)
    raw = closes_by_code(prices)
    adj = closes_by_code(prices, _actions(3, 0.9))
    # D3 之前的價格乘上 0.9,之後不動
    assert raw["1111"][DAYS[2].date()] == 100.0
    assert adj["1111"][DAYS[2].date()] == pytest.approx(90.0)
    assert adj["1111"][DAYS[3].date()] == 95.0
    assert adj["9999"] == raw["9999"]


def test_組合回測_持有期間除息_淨值不會在除息日掉一截() -> None:
    from src.portfolio import simulate

    prices = _prices(CLOSES)
    runs = pre_release_run(PUNISH, prices, timing=TIMING, actions=_actions(3, 0.9))
    closes = prices.pivot_table(index="day", columns="code", values="close")
    adjusted = closes.copy()
    adjusted.loc[: DAYS[2], "1111"] *= 0.9
    out = simulate(runs.assign(code=runs.code.astype(str)), adjusted, capital=1_000_000)
    # D2 收盤買 100(一張 10 萬);D3 除息後收 95,還原後等於從 90 漲到 95
    assert out.equity.iloc[3] == pytest.approx(900_000 + 100_000 * 95 / 90)
