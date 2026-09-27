"""驗收測試:框架必須重現 [#13] 的主要發現。

一個沒辦法重現既有結論的框架不能用。這個測試把處置股研究的乾淨樣本餵進
框架的 Event / Window / resolve_window,然後比對 report.json 裡的數字。

對不上就是兩種情況之一:框架有 bug,或原本的結論有問題。兩種都要查。

需要完整的 data/,所以在沒有資料的環境會自動跳過。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.backtest import pre_release_run, trading_days
from src.market import index_series
from src.study import Event, Window, one_sample, resolve_window


OUT = Path("data/out")
RAW = Path("data/raw")
#: [#13] 的主要發現:出關前六個交易日買、前一日賣
PRE_RELEASE = Window(entry=-6, exit=-1)

pytestmark = pytest.mark.skipif(
    not (OUT / "report.json").exists(), reason="需要完整的 data/"
)


@pytest.fixture(scope="module")
def reproduced() -> dict[str, object]:
    """用框架重跑一次,回傳算出來的統計量與窗口比對結果。"""
    prices = pd.read_csv(OUT / "prices.csv", parse_dates=["day"])
    punishes = pd.read_csv(
        OUT / "punishes.csv", parse_dates=["announced", "start", "end"]
    )
    runs = pre_release_run(
        punishes[punishes.nth > 0],
        prices,
        index_series(RAW / "prices"),
        all_punishes=punishes,
    )
    # 餵進框架的是**未過濾**的全部事件。原本這裡先用 runs.knowable 篩過,
    # 等於把舊管線已經清乾淨的資料交給框架去確認它是乾淨的 —— 把
    # resolve_window 裡的 knowable 檢查整行刪掉,測試照樣全過。
    usable_only = runs[runs.truly_released & runs.excess.notna()]
    days = sorted(day.date() for day in trading_days(prices))

    kept = []
    for row in usable_only.to_dict("records"):
        announced = row["announced"]
        event = Event(
            code=str(row["code"]),
            happened=row["release"],
            knowable=announced if isinstance(announced, date) else row["release"],
            tags={
                "excess": float(row["excess"]),
                "buy_day": row["buy_day"],
                "sell_day": row["sell_day"],
            },
        )
        window = resolve_window(event, days, PRE_RELEASE)
        if window is not None:
            kept.append((event, window))

    values = [float(event.tags["excess"]) for event, _ in kept]
    expected_blocked = int((~usable_only.knowable).sum())
    median, pvalue = one_sample(values)
    return {
        "n": len(values),
        "median": round(median, 2),
        "win": round(sum(1 for v in values if v > 0) / len(values) * 100, 1),
        "pvalue": pvalue,
        "blocked": len(usable_only) - len(kept),
        "expected_blocked": expected_blocked,
        "window_mismatches": [
            event.code
            for event, window in kept
            if window != (event.tags["buy_day"], event.tags["sell_day"])
        ],
    }


@pytest.fixture(scope="module")
def headline() -> dict[str, float]:
    """report.json 裡公布的那組數字。"""
    loaded: dict[str, float] = json.loads(
        (OUT / "report.json").read_text(encoding="utf-8")
    )["headline"]
    return loaded


def test_樣本數對得上(reproduced: dict, headline: dict) -> None:
    assert reproduced["n"] == headline["樣本數"]


def test_中位數對得上(reproduced: dict, headline: dict) -> None:
    assert reproduced["median"] == headline["中位數%"]


def test_勝率對得上(reproduced: dict, headline: dict) -> None:
    assert reproduced["win"] == headline["勝率%"]


def test_顯著(reproduced: dict) -> None:
    assert reproduced["pvalue"] < 0.0001


def test_框架算出的窗口和原本管線一天都不差(reproduced: dict) -> None:
    """只比對統計量不夠 —— 兩組不同的窗口也可能湊出同一個中位數。"""
    assert reproduced["window_mismatches"] == []


def test_偷看未來的事件被框架自己擋掉(reproduced: dict) -> None:
    """這個測試才是驗收 look-ahead 守衛的那一個。

    餵進去的是未過濾的事件,框架必須自己擋掉進場點早於公告的那些 —— 數量
    要和舊管線的 knowable 旗標算出來的一致。把 resolve_window 裡那行檢查
    刪掉,這裡就會紅。
    """
    assert reproduced["blocked"] > 0
    assert reproduced["blocked"] == reproduced["expected_blocked"]
