"""抓除權息、減資、變更面額,輸出還原股價用的因子表。

用法:.venv/bin/python -m src.fetch_actions 2016-01-01 2026-10-06

輸出 data/out/corporate_actions.csv(code, day, factor, kind)。

**任何一段抓失敗就不寫檔** —— 少了一次除權息,那一檔的還原價在那天之前
全部錯,而均線看起來還是一個正常的數字。寧可保留上一份完整的,也不要
寫出一份缺洞的。
"""

from __future__ import annotations

import csv
import sys
from dataclasses import asdict, fields
from datetime import date, timedelta
from pathlib import Path

from src.corpactions import SOURCES, Action, Source, cached, merge, parse


RAW = Path("data/raw/actions")
OUT = Path("data/out/corporate_actions.csv")
ARGC = 3


def windows(source: Source, start: date, end: date) -> list[tuple[date, date]]:
    """查詢的期間切法。

    上市一次查一年就好;櫃買的除權息表有人回報過一次最多 100 列,
    所以一律按月查,再用 totalCount 檢查有沒有被截斷。
    """
    out: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        if source.tpex:
            nxt = (cursor.replace(day=1) + timedelta(days=32)).replace(day=1)
        else:
            nxt = date(cursor.year + 1, 1, 1)
        out.append((cursor, min(nxt - timedelta(days=1), end)))
        cursor = nxt
    return out


def collect(start: date, end: date, *, today: date) -> tuple[list[Action], list[str]]:
    """所有來源的事件,以及失敗的期間。"""
    groups: list[tuple[Source, list[Action]]] = []
    failed: list[str] = []
    for source in SOURCES:
        actions: list[Action] = []
        for lo, hi in windows(source, start, end):
            try:
                actions.extend(parse(cached(source, lo, hi, RAW, today=today), source))
            except (OSError, ValueError) as exc:
                failed.append(f"{source.kind} {lo}~{hi}: {type(exc).__name__} {exc}")
        print(f"  {source.kind}: {len(actions)} 筆", flush=True)
        groups.append((source, actions))
    return merge(groups), failed


def main(argv: list[str]) -> int:
    """抓完全部來源才寫檔。"""
    if len(argv) != ARGC:
        print(__doc__, file=sys.stderr)
        return 2
    start = date.fromisoformat(argv[1])
    end = date.fromisoformat(argv[2])
    actions, failed = collect(start, end, today=date.today())  # noqa: DTZ011
    if failed:
        print(f"有 {len(failed)} 段失敗,不寫檔(保留上一份):", file=sys.stderr)
        for line in failed[:20]:
            print(f"  {line}", file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=[f.name for f in fields(Action)])
        writer.writeheader()
        writer.writerows(asdict(a) for a in actions)
    print(f"寫出 {OUT}:{len(actions)} 筆事件、{len({a.code for a in actions})} 檔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
