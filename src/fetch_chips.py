"""抓取期間內每日三大法人買賣超,輸出成一張長表。

用法:.venv/bin/python -m src.fetch_chips 2020-01-01 2026-09-21
"""

from __future__ import annotations

import csv
import sys
from dataclasses import asdict, fields
from datetime import date
from pathlib import Path

from src.chips import Chips, fetch_chips, parse_chips
from src.prices import weekdays


RAW = Path("data/raw/chips")
OUT = Path("data/out")


def main() -> None:
    """抓取期間內每個交易日的三大法人買賣超。"""
    start = date.fromisoformat(sys.argv[1])
    end = date.fromisoformat(sys.argv[2])
    days = weekdays(start, end)
    print(f"要處理 {len(days)} 個平日(非交易日會自動跳過)", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "chips.csv"
    names = [f.name for f in fields(Chips)]

    traded = 0
    rows = 0
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=names)
        writer.writeheader()
        for i, day in enumerate(days, 1):
            try:
                payload = fetch_chips(day, RAW)
            except (OSError, ValueError) as exc:
                print(f"  {day} 失敗({type(exc).__name__}),略過", flush=True)
                continue
            if payload is None:
                continue
            for bar in parse_chips(payload, day):
                writer.writerow(asdict(bar))
                rows += 1
            traded += 1
            if i % 40 == 0 or i == len(days):
                print(
                    f"  [{i}/{len(days)}] {day} 累計 {traded} 日 / {rows} 列",
                    flush=True,
                )

    print(f"\n完成:{traded} 個交易日、{rows} 列,輸出 {path}", flush=True)


if __name__ == "__main__":
    main()
