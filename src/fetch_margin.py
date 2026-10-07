"""抓取期間內每日的融資融券餘額(上市 + 上櫃),輸出成一張長表。

用法:.venv/bin/python -m src.fetch_margin 2020-01-01 2026-10-07

輸出 data/out/margin.csv(day, code, market, margin, short;單位張)。
單日失敗不中斷,沒進快取的那天下次會再抓。
"""

from __future__ import annotations

import csv
import sys
from dataclasses import asdict, fields
from datetime import date
from pathlib import Path

from src.margin import Margin, cached, parse_otc, parse_twse
from src.prices import weekdays


RAW = Path("data/raw/margin")
OUT = Path("data/out/margin.csv")
ARGC = 3


def main(argv: list[str]) -> int:
    """逐日抓兩個市場。有失敗的日子回 1,讓 update.sh 記下來。"""
    if len(argv) != ARGC:
        print(__doc__, file=sys.stderr)
        return 2
    days = weekdays(date.fromisoformat(argv[1]), date.fromisoformat(argv[2]))
    failed: list[str] = []
    rows = 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=[f.name for f in fields(Margin)])
        writer.writeheader()
        for i, day in enumerate(days, 1):
            for otc, parse in ((False, parse_twse), (True, parse_otc)):
                try:
                    payload = cached(day, RAW, otc=otc)
                except (OSError, ValueError) as exc:
                    failed.append(
                        f"{day} {'otc' if otc else 'twse'} {type(exc).__name__}"
                    )
                    continue
                if payload is None:
                    continue
                for item in parse(payload, day):
                    writer.writerow(asdict(item))
                    rows += 1
            if i % 100 == 0 or i == len(days):
                print(f"  [{i}/{len(days)}] {day} 累計 {rows} 列", flush=True)
    print(f"寫出 {OUT}:{rows} 列")
    if failed:
        print(f"有 {len(failed)} 筆失敗:{', '.join(failed[:10])}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
