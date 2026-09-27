"""把上市與上櫃併成一個宇集。

[#23]:研究的預設應該是全市場。上市的 1,166 次處置加上上櫃的 1,819 次,
合計 2,985 個可定價的事件 —— 原本只用上市那 1,166 個,也就是漏掉的比用到的多。

合併的時候要小心兩件事:

* **兩邊的欄位形狀要先對齊。** tpex.normalise 負責把上櫃轉成上市的欄位。
* **market 欄不能省。** 上櫃的流動性比上市差,處置的衝擊理論上更大但滑價也
  更貴,所以結論一定要能分市場看。混在一起而分不出來,等於把兩個不同的東西
  當成一個。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from src.tpex import normalise


if TYPE_CHECKING:
    from datetime import date

OUT = Path("data/out")
#: 上市與上櫃的行情、處置公告
LISTED_PRICES = OUT / "prices.csv"
OTC_PRICES = OUT / "tpex_prices.csv"
LISTED_PUNISHES = OUT / "punishes.csv"
OTC_PUNISHES = OUT / "tpex_punishes.csv"


def all_prices(listed: Path = LISTED_PRICES, otc: Path = OTC_PRICES) -> pd.DataFrame:
    """兩個市場的行情併成一張表,多一個 market 欄。

    代號在兩個市場之間不會重複(轉上市的股票代號不變,但同一天只會出現在
    一邊),所以直接接起來就好 —— 但還是檢查一次,重複代號會讓後面的
    pivot 安靜地取到錯的價格。
    """
    frames = []
    for path, market in ((listed, "twse"), (otc, "otc")):
        if not path.exists():
            continue
        frame = pd.read_csv(path, dtype={"code": str}, parse_dates=["day"])
        frame["market"] = market
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True)
    clashes = merged.groupby(["day", "code"]).size()
    if (clashes > 1).any():
        codes = clashes[clashes > 1].index.get_level_values("code").unique()
        msg = f"同一天同一個代號出現在兩個市場:{list(codes)[:5]}"
        raise ValueError(msg)
    return merged


def all_punishes(
    listed: Path = LISTED_PUNISHES, otc: Path = OTC_PUNISHES
) -> pd.DataFrame:
    """兩個市場的處置公告併成一張表。

    上市那份本來就是這個形狀;上櫃的要先過 tpex.normalise。
    解不出日期的列會被丟掉 —— 猜一個日期比少一筆事件糟得多。
    """
    frames = []
    if listed.exists():
        twse = pd.read_csv(
            listed, dtype={"code": str}, parse_dates=["announced", "start", "end"]
        )
        twse["market"] = "twse"
        frames.append(twse)
    if otc.exists():
        raw = pd.read_csv(otc, dtype=str).fillna("")
        rows = [
            x
            for x in (
                normalise({str(k): str(v) for k, v in row.items()})
                for row in raw.to_dict("records")
            )
            if x
        ]
        if rows:
            frames.append(pd.DataFrame(rows))
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True)
    for column in ("announced", "start", "end"):
        merged[column] = pd.to_datetime(merged[column])
    return merged


def summary(prices: pd.DataFrame, punishes: pd.DataFrame) -> dict[str, object]:
    """合併後的宇集長什麼樣。跟結果一起報,不能只報 p 值([#22] 的守衛 6)。

    空表也要能用:抓取失敗或第一次執行時應該印出「什麼都沒有」,而不是丟一個
    KeyError 讓人以為程式壞了。
    """
    return {
        "codes": 0 if prices.empty else int(prices.code.nunique()),
        "codes_by_market": _by_market(prices, "code"),
        "rows": len(prices),
        "events": len(punishes),
        "events_by_market": _by_market(punishes, None),
        "span": _span(prices),
    }


def _by_market(frame: pd.DataFrame, count: str | None) -> dict[str, int]:
    """分市場數。count 給欄名就數那一欄的不重複值,不給就數列數。"""
    if frame.empty or "market" not in frame.columns:
        return {}
    return {
        str(market): int(group[count].nunique() if count else len(group))
        for market, group in frame.groupby("market")
    }


def _span(prices: pd.DataFrame) -> tuple[date, date] | None:
    if prices.empty:
        return None
    return (prices.day.min().date(), prices.day.max().date())
