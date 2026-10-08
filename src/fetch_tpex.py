"""抓上櫃的每日行情與處置公告。

[#23]:現有研究只涵蓋 2,957 檔普通股裡的 1,105 檔(37.4%),缺的 1,852 檔
全是上櫃。這支把那一半補起來。

用法:.venv/bin/python -m src.fetch_tpex 2020-01-01 2026-09-23

行情一天一個請求,七年約 1,750 個。抓過的日子有快取,中斷可以直接重跑。
處置公告一次抓完整段期間,只要一個請求。
"""

from __future__ import annotations

import csv
import sys
from dataclasses import asdict, fields
from pathlib import Path
from typing import TYPE_CHECKING

from src import cli
from src.prices import weekdays
from src.tpex import (
    Quote,
    cached_quotes,
    fetch_disposals,
    parse_disposals,
    parse_quotes,
)


if TYPE_CHECKING:
    from datetime import date


RAW = Path("data/raw/tpex")
OUT = Path("data/out")


def fetch_prices(start: date, end: date) -> int:
    """抓期間內每個交易日的全櫃買行情,輸出成一張長表。回傳列數。"""
    days = weekdays(start, end)
    print(f"行情:{len(days)} 個平日(非交易日自動跳過)", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "tpex_prices.csv"
    names = [f.name for f in fields(Quote)]
    traded = 0
    rows = 0
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=names)
        writer.writeheader()
        for i, day in enumerate(days, 1):
            try:
                payload = cached_quotes(day, RAW / "prices")
            except (OSError, ValueError) as exc:
                # 單日失敗不中斷整批 —— 重跑時快取會跳過已成功的
                print(f"  {day} 失敗({type(exc).__name__}),略過", flush=True)
                continue
            if payload is None:
                continue
            for quote in parse_quotes(payload, day):
                writer.writerow(asdict(quote))
                rows += 1
            traded += 1
            if i % 100 == 0 or i == len(days):
                print(
                    f"  [{i}/{len(days)}] {day} 累計 {traded} 交易日 / {rows} 列",
                    flush=True,
                )
    print(f"行情完成:{traded} 個交易日、{rows} 列 → {path}", flush=True)
    return rows


def fetch_punishes(start: date, end: date) -> int:
    """抓期間內的處置公告。一個請求就拿完。回傳列數。"""
    payload = fetch_disposals(start, end)
    rows = list(parse_disposals(payload))
    if not rows:
        print("處置公告:沒有資料", flush=True)
        return 0
    path = OUT / "tpex_punishes.csv"
    names = sorted(rows[0])
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)
    codes = len({r["證券代號"] for r in rows})
    print(f"處置公告:{len(rows)} 列、{codes} 檔 → {path}", flush=True)
    return len(rows)


def main(argv: list[str]) -> int:
    """抓行情與處置公告。"""
    start, end = cli.date_range(__doc__, argv[1:])
    # 處置公告七年一個請求,回應很大,伺服器偶爾中途斷線(2026-10-08 兩次)。
    # 斷了也要照樣抓行情 —— 以前公告一失敗就整支結束,行情跟著漏掉(#37)。
    # 上一份 tpex_punishes.csv 只在成功時覆蓋,所以失敗時保留舊的
    failed = False
    try:
        fetch_punishes(start, end)
    except (OSError, ValueError) as exc:
        print(f"處置公告失敗({type(exc).__name__}),保留上一份", flush=True)
        failed = True
    fetch_prices(start, end)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
