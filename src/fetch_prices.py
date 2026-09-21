"""抓取期間內每日全市場收盤行情,輸出成一張長表。

用法:.venv/bin/python -m src.fetch_prices 2025-01-01 2026-09-21
"""

from __future__ import annotations

import csv
import sys
from dataclasses import asdict, fields
from datetime import date
from pathlib import Path

from src.prices import Bar, fetch_day, parse_day, weekdays


RAW = Path("data/raw/prices")
OUT = Path("data/out")


def main() -> None:
    """抓取期間內每個交易日的全市場行情並輸出成一張長表。"""
    start = date.fromisoformat(sys.argv[1])
    end = date.fromisoformat(sys.argv[2])
    days = weekdays(start, end)
    print(f"要處理 {len(days)} 個平日(非交易日會自動跳過)", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "prices.csv"
    names = [f.name for f in fields(Bar)]

    traded = 0
    rows = 0
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=names)
        writer.writeheader()
        for i, day in enumerate(days, 1):
            try:
                payload = fetch_day(day, RAW)
            except (OSError, ValueError) as exc:
                # 單日失敗不該中斷整批,記下來跳過就好
                print(f"  {day} 失敗({type(exc).__name__}),略過", flush=True)
                continue
            if payload is None:
                continue
            bars = parse_day(payload, day)
            for bar in bars:
                writer.writerow(asdict(bar))
            traded += 1
            rows += len(bars)
            if i % 20 == 0 or i == len(days):
                print(
                    f"  [{i}/{len(days)}] {day} 累計 {traded} 交易日 / {rows} 列",
                    flush=True,
                )

    print(f"\n完成:{traded} 個交易日、{rows} 列,輸出 {path}", flush=True)


if __name__ == "__main__":
    main()
