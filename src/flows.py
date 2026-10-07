"""籌碼總覽:每一檔最近的三大法人買賣超與融資融券。

「最近 N 天」用的是**整個市場**的最後 N 個交易日,不是每一檔自己的。
法人沒有進出的股票在那天不會出現在表裡 —— 那天算 0,而不是往前多抓
一天湊滿 N 筆,否則冷門股的「近 5 日」會變成近兩個月。

單位一律換成**張**(法人原始資料是股數,融資融券本來就是張)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd


if TYPE_CHECKING:
    from pathlib import Path

#: 一張 = 1,000 股
LOT = 1000
SHORT_WINDOW = 5
LONG_WINDOW = 20


def _last_days(frame: pd.DataFrame, n: int) -> list[pd.Timestamp]:
    return sorted(frame["day"].unique())[-n:]


def institutional(chips: pd.DataFrame) -> dict[str, dict[str, int]]:
    """外資、投信、自營商近 5 日的買賣超,以及三大法人合計的近 5 日與 20 日(張)。"""
    if chips.empty:
        return {}
    out: dict[str, dict[str, int]] = {}
    short = chips[chips["day"].isin(_last_days(chips, SHORT_WINDOW))]
    long = chips[chips["day"].isin(_last_days(chips, LONG_WINDOW))]
    s = short.groupby("code")[["foreign", "trust", "dealer"]].sum()
    total = (
        (long["foreign"] + long["trust"] + long["dealer"]).groupby(long["code"]).sum()
    )
    for code in total.index:
        row = s.loc[code] if code in s.index else None
        out[str(code)] = {
            "foreign5": 0 if row is None else round(int(row["foreign"]) / LOT),
            "trust5": 0 if row is None else round(int(row["trust"]) / LOT),
            "dealer5": 0 if row is None else round(int(row["dealer"]) / LOT),
            "inst20": round(int(total[code]) / LOT),
        }
    return out


def margin_summary(margin: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """最新的融資、融券餘額,5 個交易日前到現在的增減,以及券資比。

    5 天前那天這檔沒有資料(新上市、停牌)時,增減是 None,不是 0。
    券資比 = 融券餘額 / 融資餘額;融資是 0 的時候算不出來,是 None。
    """
    if margin.empty:
        return {}
    days = _last_days(margin, SHORT_WINDOW + 1)
    latest = margin.loc[margin["day"] == days[-1], ["code", "margin", "short"]]
    before = margin.loc[margin["day"] == days[0], ["code", "margin", "short"]]
    if len(days) <= SHORT_WINDOW:
        before = before.iloc[0:0]  # 不到 6 天的資料,算不出 5 日增減
    joined = latest.merge(before, on="code", how="left", suffixes=("", "_prev"))
    out: dict[str, dict[str, Any]] = {}
    for row in joined.to_dict("records"):
        m, s = int(row["margin"]), int(row["short"])
        known = pd.notna(row["margin_prev"])
        out[str(row["code"])] = {
            "margin": m,
            "marginChg5": m - int(row["margin_prev"]) if known else None,
            "short": s,
            "shortChg5": s - int(row["short_prev"]) if known else None,
            "shortRatio": round(s / m * 100, 2) if m else None,
        }
    return out


#: 籌碼總覽裡每一檔都有的欄位。缺資料的股票整組是 None
FLOW_KEYS = (
    "foreign5",
    "trust5",
    "dealer5",
    "inst20",
    "margin",
    "marginChg5",
    "short",
    "shortChg5",
    "shortRatio",
)


def load_flows(
    chip_files: list[Path], margin_file: Path
) -> dict[str, dict[str, Any]] | None:
    """讀法人與融資融券,合成每檔一組。檔案都不在就回 None(網頁顯示準備中)。"""
    frames = [
        pd.read_csv(p, dtype={"code": str}, parse_dates=["day"], encoding="utf-8-sig")
        for p in chip_files
        if p.exists()
    ]
    if not frames and not margin_file.exists():
        return None
    chips = pd.concat(frames) if frames else pd.DataFrame()
    margin = (
        pd.read_csv(margin_file, dtype={"code": str}, parse_dates=["day"])
        if margin_file.exists()
        else pd.DataFrame()
    )
    inst = institutional(chips)
    marg = margin_summary(margin)
    out: dict[str, dict[str, Any]] = {}
    for code in set(inst) | set(marg):
        merged: dict[str, Any] = dict.fromkeys(FLOW_KEYS)
        merged.update(inst.get(code, {}))
        merged.update(marg.get(code, {}))
        out[code] = merged
    return out
