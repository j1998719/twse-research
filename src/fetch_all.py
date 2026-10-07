"""抓取指定期間的注意股與處置股,輸出 CSV。

用法:.venv/bin/python -m src.fetch_all 2025-01-01 2026-09-21
"""

from __future__ import annotations

import csv
from dataclasses import asdict, fields
from datetime import date
from pathlib import Path
from typing import Any

from src import cli
from src.twse import (
    NOTICE_URL,
    PUNISH_URL,
    Notice,
    Punish,
    fetch,
    parse_notices,
    parse_punishes,
)


RAW = Path("data/raw")
OUT = Path("data/out")


def year_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """切成一年一段。證交所單次查詢接受整年,但跨年要分開問。"""
    chunks: list[tuple[date, date]] = []
    year = start.year
    while year <= end.year:
        first = max(start, date(year, 1, 1))
        last = min(end, date(year, 12, 31))
        chunks.append((first, last))
        year += 1
    return chunks


def unique_punishes(rows: list[Punish]) -> list[Punish]:
    """去掉重複的處置公告,保留第一次出現的順序(#59)。

    證交所按年分段查詢時,處置期間跨年的那幾筆(12 月底公告、1 月初結束)
    兩段都會回來。2020–2026 有 28 筆,頭條樣本因此多算了 20 筆一模一樣的交易。
    同一檔、同一天公告、同一段期間、同一種措施就是同一筆。
    """
    seen: set[tuple[object, ...]] = set()
    out: list[Punish] = []
    for row in rows:
        key = (row.code, row.announced, row.start, row.end, row.measure)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def write_csv(rows: list[Any], path: Path) -> None:
    """把 dataclass 清單寫成 CSV。空清單不會產生檔案。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    names = [f.name for f in fields(rows[0])]
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=names)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def main() -> None:
    """抓取指定期間的注意股與處置股並輸出 CSV。"""
    start, end = cli.date_range(__doc__)

    notices: list[Notice] = []
    punishes: list[Punish] = []

    for first, last in year_chunks(start, end):
        n = parse_notices(fetch(NOTICE_URL, first, last, RAW))
        p = parse_punishes(fetch(PUNISH_URL, first, last, RAW))
        print(f"{first} ~ {last}:注意 {len(n)} 筆、處置 {len(p)} 筆")
        notices.extend(n)
        punishes.extend(p)

    notices.sort(key=lambda r: (r.day, r.code))
    punishes = unique_punishes(punishes)
    punishes.sort(key=lambda r: (r.announced, r.code))

    write_csv(notices, OUT / "notices.csv")
    write_csv(punishes, OUT / "punishes.csv")
    print(f"\n合計:注意股 {len(notices)} 筆、處置股 {len(punishes)} 筆(僅上市普通股)")


if __name__ == "__main__":
    main()
