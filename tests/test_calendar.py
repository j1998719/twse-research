"""兩個市場的交易日曆要一致。

[#23] 之後 trading_days 吃的是上市與上櫃的**聯集**,所以其中一邊少一天,
另一邊的交易日偏移就會整個錯開一格 —— 而且完全無聲。

實際踩過:2026-09-21(週一)上市的快取是 0 bytes(抓取失敗被當成非交易日),
上櫃那天有 891 檔在交易。聯集把那天算成交易日,於是上市事件的窗口偏移少一天,
而加權指數那天沒有值,跨過它的窗口超額報酬變成 None、事件被靜靜篩掉。

需要完整的 data/,所以在沒有資料的環境會自動跳過。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


OUT = Path("data/out")
RAW = Path("data/raw/prices")

pytestmark = pytest.mark.skipif(
    not (OUT / "tpex_prices.csv").exists(), reason="需要完整的 data/"
)


@pytest.fixture(scope="module")
def days() -> dict[str, set[str]]:
    """兩個市場各自有資料的日子。"""
    listed = pd.read_csv(OUT / "prices.csv", dtype=str, usecols=["day"])
    otc = pd.read_csv(OUT / "tpex_prices.csv", dtype=str, usecols=["day"])
    return {"twse": set(listed.day.unique()), "otc": set(otc.day.unique())}


def test_上櫃有交易的日子上市不該是空的(days: dict[str, set[str]]) -> None:
    """上櫃在交易而上市整天沒資料,幾乎一定是上市那邊抓失敗。

    真正的休市兩個市場會一起休 —— 它們共用同一份國定假日。
    """
    only_otc = sorted(days["otc"] - days["twse"])
    assert only_otc == []


def test_上市有交易的日子上櫃不該是空的(days: dict[str, set[str]]) -> None:
    only_listed = sorted(days["twse"] - days["otc"])
    assert only_listed == []


def test_空快取都落在真正的休市日(days: dict[str, set[str]]) -> None:
    """寫成 0 bytes 的快取代表「非交易日」,那就不該有另一個市場在交易。

    平日的 stat != OK 可能是限流或暫時性錯誤,和真的休市長得一模一樣。
    這個交叉檢查是唯一分得出來的方法。
    """
    empty = {
        f"{p.stem[9:13]}-{p.stem[13:15]}-{p.stem[15:17]}"
        for p in RAW.glob("mi_index_*.json")
        if p.stat().st_size == 0
    }
    assert sorted(empty & days["otc"]) == []
