"""大戶持股排行:每一檔普通股的大戶持股比例、人數與每日收盤。

給不寫程式的人看的頁面,所以只回答一個問題:哪些股票的大戶拿得多、
這一週有沒有變多。

「大戶」的門檻沒有標準答案 —— 有人看 400 張、有人看 1,000 張 —— 所以這裡
把 400 張以上的四個級距都分開輸出,讓網頁自己加總。集保快照的分級是固定的
(見 tdcc.py 的「全市場快照」那一段):

    12  400,001 - 600,000 股
    13  600,001 - 800,000 股
    14  800,001 - 1,000,000 股
    15  1,000,001 股以上

快照只有最新一週,所以「比上週」要靠 fetch_tdcc 每週存下來的檔案。
只有一份快照的時候,週變化就是 null,不是 0。

用法:.venv/bin/python -m src.build_bigholders
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pandas as pd

from src.adjust import LongTerm, adjusted_closes, long_term
from src.fetch_tdcc import ARCHIVE
from src.tdcc import SNAPSHOT_TOTAL_LEVEL, parse_snapshot, snapshot_day
from src.tpex import is_common_stock
from src.universe import all_prices


if TYPE_CHECKING:
    from src.tdcc import Band

#: 400 張以上的四個級距,由小到大。網頁用索引對應門檻,順序不能動
BIG_LEVELS = (12, 13, 14, 15)
#: 跟 BIG_LEVELS 一一對應的門檻(張)
THRESHOLDS = (400, 600, 800, 1000)

OUT = Path("data/out/bigholders.json")
#: 除權息、減資、變更面額的還原因子(code, day, factor)。還沒有這份就不算均線
ACTIONS = Path("data/out/corporate_actions.csv")
#: 2016 起的日線(fetch_history)。prices.csv 只從 2020 開始,不夠算十年線
HISTORY = Path("data/out/long_prices.csv")
TAIPEI = ZoneInfo("Asia/Taipei")


def latest_snapshots(archive: Path = ARCHIVE) -> list[Path]:
    """最新的兩份快照,新的在前。檔名帶資料日期,所以照檔名排就是照日期排。"""
    return sorted(archive.glob("dispersion_*.csv"), reverse=True)[:2]


def last_two_closes(prices: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """每一檔最近兩個交易日的收盤,算出漲跌幅。

    用每一檔**自己的**最後兩天,而不是全市場的最後一天 —— 停牌的股票
    最後一筆可能在幾天前,硬用全市場日期的話它會整列消失。
    """
    out: dict[str, dict[str, Any]] = {}
    if prices.empty:
        return out
    tail = prices.dropna(subset=["close"]).sort_values("day").groupby("code").tail(2)
    for code, rows in tail.groupby("code"):
        last = rows.iloc[-1]
        prev = rows.iloc[-2] if len(rows) > 1 else None
        change = None
        if prev is not None and prev["close"]:
            change = round((last["close"] / prev["close"] - 1) * 100, 2)
        volume = last.get("volume")
        out[str(code)] = {
            "name": str(last["name"]),
            "market": str(last["market"]),
            "day": last["day"].date().isoformat(),
            "close": float(last["close"]),
            "change": change,
            # 成交股數換成張,台股習慣看張
            "lots": None if pd.isna(volume) else round(volume / 1000),
        }
    return out


def _levels(bands: dict[int, Band]) -> tuple[list[float], list[int]]:
    """四個大戶級距的 (佔比, 人數)。

    缺的級距補 0 —— 集保每一級都會列,缺了代表那一級沒有人,不是資料壞掉。
    """
    pct = [bands[lv].pct if lv in bands else 0.0 for lv in BIG_LEVELS]
    people = [bands[lv].people if lv in bands else 0 for lv in BIG_LEVELS]
    return pct, people


def _long_fields(lt: LongTerm | None) -> dict[str, float | None]:
    """五年線、十年線,以及收盤價離它們幾 %。算不出來的是 null。"""
    if lt is None:
        return {"ma5y": None, "ma10y": None, "gap5y": None, "gap10y": None}
    return {
        "ma5y": None if lt.ma5y is None else round(lt.ma5y, 2),
        "ma10y": None if lt.ma10y is None else round(lt.ma10y, 2),
        "gap5y": lt.gap(lt.ma5y),
        "gap10y": lt.gap(lt.ma10y),
    }


def load_long_term(
    actions: Path = ACTIONS, history: Path = HISTORY
) -> dict[str, LongTerm] | None:
    """還原因子和長期日線都有才算均線,缺一個就回 None。"""
    if not actions.exists() or not history.exists():
        return None
    events = pd.read_csv(actions, dtype={"code": str}, parse_dates=["day"])
    prices = pd.read_csv(history, dtype={"code": str}, parse_dates=["day"])
    return long_term(adjusted_closes(prices[["code", "day", "close"]], events))


def build(
    now_text: str,
    prev_text: str | None,
    quotes: dict[str, dict[str, Any]],
    long: dict[str, LongTerm] | None = None,
) -> dict[str, Any]:
    """組出網頁要的 JSON。

    只留普通股,而且要有收盤價 —— 沒有收盤價的多半是興櫃或已下市,
    沒有名稱也沒有行情,放進表格只會是一列看不懂的代號。
    """
    now = parse_snapshot(now_text)
    prev = parse_snapshot(prev_text) if prev_text else {}
    rows: list[dict[str, Any]] = []
    for code, bands in sorted(now.items()):
        quote = quotes.get(code)
        if quote is None or not is_common_stock(code):
            continue
        total = bands.get(SNAPSHOT_TOTAL_LEVEL)
        if total is None or total.people <= 1:
            # 減資、變更面額換發股票的期間,集保把全部股票記在一個持有人名下
            # (2601 益航 2026-10-02:股東 1 人、千張級距 100%)。那不是大戶,
            # 是換發中的暫時狀態,放進來會排在大戶持股第一名
            continue
        pct, people = _levels(bands)
        prev_pct = _levels(prev[code])[0] if code in prev else None
        rows.append(
            {
                "code": code,
                **quote,
                "holders": None if total is None else total.people,
                "pct": pct,
                "people": people,
                "prevPct": prev_pct,
                **_long_fields(None if long is None else long.get(code)),
            }
        )
    day = snapshot_day(now_text)
    prev_day = snapshot_day(prev_text) if prev_text else None
    return {
        "generated": datetime.now(tz=TAIPEI).date().isoformat(),
        "day": None if day is None else day.isoformat(),
        "prevDay": None if prev_day is None else prev_day.isoformat(),
        "thresholds": list(THRESHOLDS),
        # 均線一律用還原股價算(Jordan 2026-10-06)。還原資料還沒有的時候
        # 整塊不算,不拿原始收盤價頂替
        "maReady": long is not None,
        "rows": rows,
    }


def main() -> int:
    """讀最新兩份快照和行情,寫出 bigholders.json。"""
    snaps = latest_snapshots()
    if not snaps:
        print(f"{ARCHIVE} 裡沒有集保快照,先跑 src.fetch_tdcc", file=sys.stderr)
        return 1
    now_text = snaps[0].read_text(encoding="utf-8")
    prev_text = snaps[1].read_text(encoding="utf-8") if len(snaps) > 1 else None
    prices = all_prices()
    quotes = last_two_closes(prices)
    if not quotes:
        print("沒有行情資料,先跑 src.fetch_prices 和 src.fetch_tpex", file=sys.stderr)
        return 1
    long = load_long_term()
    if long is None:
        print(f"沒有 {ACTIONS} 或 {HISTORY},這次不算長期均線")
    report = build(now_text, prev_text, quotes, long)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    print(
        f"寫出 {OUT}:{len(report['rows'])} 檔,快照 {report['day']},前一份 {report['prevDay']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
