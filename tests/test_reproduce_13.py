"""驗收測試:框架必須重現處置股研究公布的數字。

一個沒辦法重現既有結論的框架不能用。這個測試把處置股研究的乾淨樣本餵進
框架的 Event / Window / resolve_window,然後比對 report.json 裡的數字。

**現在比的是全市場**(上市 + 上櫃,2,265 筆)。原本只有上市的 951 筆、
中位數 +1.65%、勝率 58.7% 那一組,由 test_上市子集的歷史基準沒有跑掉 釘住
—— 舊結論不會被新資料悄悄改掉,兩組數字都在。

對不上就是兩種情況之一:框架有 bug,或原本的結論有問題。兩種都要查。

需要完整的 data/,所以在沒有資料的環境會自動跳過。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src.backtest import pre_release_run, trading_days
from src.events.disposition import events as disposition_events
from src.eventstats import window_excess
from src.market import index_series
from src.run_wholemarket import closes_by_code
from src.study import Event, Window, one_sample, resolve_window
from src.universe import all_prices, all_punishes


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
    prices = all_prices()
    punishes = all_punishes()
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


@pytest.fixture(scope="module")
def via_adapter() -> dict[str, int]:
    """完全走轉接層的事件篩選,不在測試裡手刻。"""
    prices = all_prices()
    punishes = all_punishes()
    runs = pre_release_run(
        punishes[punishes.nth > 0],
        prices,
        index_series(RAW / "prices"),
        all_punishes=punishes,
    )
    events = disposition_events(runs)
    days = sorted(day.date() for day in trading_days(prices))
    passed = [e for e in events if resolve_window(e, days, PRE_RELEASE) is not None]
    return {
        "all": len(events),
        "knowable": len(passed),
        # excess 算不出來的也要排除,才和 expected 的條件一致 ——
        # 今天兩者剛好重合,但那是巧合而不是保證
        "clean": sum(
            1 for e in passed if e.tags["truly_released"] and e.tags["has_excess"]
        ),
        "expected": int(
            (runs.knowable & runs.truly_released & runs.excess.notna()).sum()
        ),
    }


def test_轉接層加框架篩出的事件和舊管線一致(via_adapter: dict) -> None:
    """轉接層決定 knowable,框架擋掉進場過早的 —— 兩段合起來要等於舊管線。"""
    assert via_adapter["clean"] == via_adapter["expected"]


def test_框架擋掉的偷看未來事件數看得出來(via_adapter: dict) -> None:
    """框架自己擋下來的 look-ahead 筆數。

    只看上市的時候是 31 筆([#13] 當初手工找到的數字);加上上櫃之後變 68。
    寫死一個數字是刻意的:它變動就代表資料或守衛的行為變了,那要有人知道。
    """
    assert via_adapter["all"] - via_adapter["knowable"] == 68


@pytest.fixture(scope="module")
def both_benchmarks() -> dict[str, float]:
    """同一組事件,用兩種基準各算一次。

    舊管線用市值加權的加權指數,而且是每日再平衡的水位相除;框架主張基準要
    和個股同一種持有方式(等權買進持有),理由寫在 eventstats 裡。招牌數字
    到底吃不吃這個差別,要算出來才知道。
    """
    prices = all_prices()
    punishes = all_punishes()
    runs = pre_release_run(
        punishes[punishes.nth > 0],
        prices,
        index_series(RAW / "prices"),
        all_punishes=punishes,
    )
    events = [
        e
        for e in disposition_events(runs)
        if e.tags["truly_released"] and e.tags["has_excess"]
    ]
    days = sorted(day.date() for day in trading_days(prices))
    # eventdata.load_closes 只讀上市的 prices.csv —— 用它的話上櫃股配不到
    # 價格,兩種基準就會算在不同的樣本上,比的不是基準而是樣本
    closes = closes_by_code(prices)

    old: list[float] = []
    new: list[float] = []
    for event in events:
        span = resolve_window(event, days, PRE_RELEASE)
        if span is None or event.code not in closes:
            continue
        got = window_excess(closes[event.code], closes, *span)
        if got is None:
            continue
        old.append(float(event.tags["old_excess"]))  # type: ignore[arg-type]
        new.append(got)
    return {
        "n": len(old),
        "old_median": round(one_sample(old)[0], 2),
        "new_median": round(one_sample(new)[0], 2),
        "old_win": round(sum(1 for v in old if v > 0) / len(old) * 100, 1),
        "new_win": round(sum(1 for v in new if v > 0) / len(new) * 100, 1),
        "new_p": one_sample(new)[1],
    }


def test_兩種基準配到同一組事件(both_benchmarks: dict) -> None:
    """全市場。兩種基準必須算在同一批事件上,否則比的不是基準而是樣本。"""
    assert both_benchmarks["n"] == 2265


def test_換成框架的基準結論不變(both_benchmarks: dict) -> None:
    """方向要一致,而且要一樣顯著。

    這個測試把**報酬的定義**釘住。原本只比對統計量的話,改掉基準或拿掉交易
    成本,report.json 和重算的那一邊會一起移動,沒有任何測試會發現。
    """
    assert both_benchmarks["new_median"] > 0
    assert both_benchmarks["new_p"] < 0.0001
    assert both_benchmarks["new_win"] > 50


def test_兩種基準的差距不大(both_benchmarks: dict) -> None:
    """實測 +1.87% vs +1.98% —— 基準的選擇不是這個發現的來源。

    差距擴大到 1 個百分點以上就要回頭查:那代表結論開始依賴基準怎麼算,
    而不是事件本身。
    """
    gap = both_benchmarks["new_median"] - both_benchmarks["old_median"]
    assert abs(gap) < 1.0


@pytest.fixture(scope="module")
def listed_only() -> dict[str, float]:
    """只用上市那一半重跑,當歷史基準。

    這是 [#13] 當初公布的那組數字。加入上櫃之後 report.json 變成全市場,
    但舊結論不該因此無人看管 —— 它變動就代表上市那半邊的資料或算法動了。
    """
    prices = all_prices()
    punishes = all_punishes()
    listed = punishes[punishes.market == "twse"]
    runs = pre_release_run(
        listed[listed.nth > 0],
        prices,
        index_series(RAW / "prices"),
        all_punishes=punishes,
    )
    clean = runs[runs.knowable & runs.truly_released & runs.excess.notna()]
    values = clean.excess.dropna().tolist()
    median, _ = one_sample(values)
    return {
        "n": len(values),
        "median": round(median, 2),
        "win": round(sum(1 for v in values if v > 0) / len(values) * 100, 1),
    }


def test_上市子集的歷史基準沒有跑掉(listed_only: dict) -> None:
    """951 筆、+1.65%、58.7% —— [#13] 公布的那組數字。

    寫死是刻意的。加入上櫃不該讓上市那半邊的數字改變,改變了就是有 bug。
    """
    assert listed_only["n"] == 951
    assert listed_only["median"] == 1.65
    assert listed_only["win"] == 58.7
