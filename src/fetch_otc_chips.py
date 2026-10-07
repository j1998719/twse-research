"""抓取期間內每日的上櫃三大法人買賣超,輸出成一張長表。

用法:.venv/bin/python -m src.fetch_otc_chips 2020-01-01 2026-10-07

輸出 data/out/otc_chips.csv,欄位跟上市的 chips.csv 一樣。分開兩個檔,是因為
chips.csv 是 run_chips 研究的輸入,混進上櫃會改到那份研究的樣本。
"""

from __future__ import annotations

import csv
import sys
from dataclasses import asdict, fields
from datetime import date
from pathlib import Path

from src.chips import Chips, fetch_otc_chips, parse_otc_chips
from src.prices import weekdays


RAW = Path("data/raw/chips")
OUT = Path("data/out/otc_chips.csv")
ARGC = 3


def main(argv: list[str]) -> int:
    """逐日抓。有失敗的日子回 1。"""
    if len(argv) != ARGC:
        print(__doc__, file=sys.stderr)
        return 2
    days = weekdays(date.fromisoformat(argv[1]), date.fromisoformat(argv[2]))
    failed: list[str] = []
    rows = 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=[f.name for f in fields(Chips)])
        writer.writeheader()
        for i, day in enumerate(days, 1):
            try:
                payload = fetch_otc_chips(day, RAW)
            except (OSError, ValueError) as exc:
                failed.append(f"{day} {type(exc).__name__}")
                continue
            if payload is None:
                continue
            for item in parse_otc_chips(payload, day):
                writer.writerow(asdict(item))
                rows += 1
            if i % 100 == 0 or i == len(days):
                print(f"  [{i}/{len(days)}] {day} 累計 {rows} 列", flush=True)
    print(f"寫出 {OUT}:{rows} 列")
    if failed:
        print(f"有 {len(failed)} 天失敗:{', '.join(failed[:10])}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
