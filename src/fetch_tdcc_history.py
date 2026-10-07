"""從集保的單檔查詢頁往回補股權分散表,每天補一點、可以中斷續跑(#49)。

用法:.venv/bin/python -m src.fetch_tdcc_history --weeks 8 --minutes 30

全市場快照只給最新一週,所以「過去 n 週大戶增加多少」要往回補。查詢頁有約
一年的歷史,但一檔一週就要兩個請求(SYNCHRONIZER_TOKEN 一次性,見 tdcc.py),
全市場 8 週約 1.6 萬檔週、3.2 萬個請求 —— 一次跑不完,也不該一次打完。所以:

* 每一次只花 --minutes 分鐘,時間到就停,下一次從還缺的地方接著補
* 最新的週先補,補到一半也已經能算短的 n
* 已經有全市場快照的那一週不補(data/raw/tdcc/ 裡有的資料日期)
* 每個請求之間停 --pause 秒

存成 data/raw/tdcc_weeks/{資料日期}.json:代號 -> 級距文字 -> [人數, 股數, 佔比]。
查到空表的不記錄(可能是那時還沒上市,也可能是暫時性的),下次會再查。
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from src.fetch_tdcc import ARCHIVE
from src.tdcc import available_weeks, fetch_week, parse_snapshot, snapshot_day
from src.tpex import is_common_stock


if TYPE_CHECKING:
    from datetime import date

OUT = Path("data/raw/tdcc_weeks")
#: 大戶頁實際列出的股票(停牌、興櫃、沒有行情的已經濾掉)。有它就只補這些
PAGE = Path("data/out/bigholders.json")
#: 每補這麼多筆就存檔一次,中途被中斷也不會白做
FLUSH_EVERY = 25
#: 失敗時只印前幾筆,不要洗版
SHOW_FAILURES = 5

Weekly = dict[str, dict[str, list[float]]]


def universe(archive: Path = ARCHIVE, page: Path = PAGE) -> list[str]:
    """要補的股票:大戶頁列出的那些;還沒有大戶頁就用最新快照裡的普通股。"""
    if page.exists():
        rows = json.loads(page.read_text(encoding="utf-8")).get("rows") or []
        return sorted({str(r["code"]) for r in rows})
    snaps = sorted(archive.glob("dispersion_*.csv"))
    if not snaps:
        return []
    codes = parse_snapshot(snaps[-1].read_text(encoding="utf-8"))
    return sorted(code for code in codes if is_common_stock(code))


def snapshot_days(archive: Path = ARCHIVE) -> set[date]:
    """已經有全市場快照的資料日期。這些週不用逐檔補。"""
    out = set()
    for path in archive.glob("dispersion_*.csv"):
        day = snapshot_day(path.read_text(encoding="utf-8"))
        if day is not None:
            out.add(day)
    return out


def load(path: Path) -> Weekly:
    """讀一週已經補到的部分。檔案壞了就從頭來,不要讓一個壞檔擋住整個流程。"""
    if not path.exists():
        return {}
    try:
        data: Weekly = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data


def save(path: Path, data: Weekly) -> None:
    """先寫暫存檔再改名:寫到一半被中斷,原本的檔案還在。"""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    tmp.replace(path)


def todo(weeks: list[date], codes: list[str], out: Path) -> list[tuple[date, str]]:
    """還缺的 (週, 代號),最新的週在前。"""
    missing = []
    for day in sorted(weeks, reverse=True):
        have = load(out / f"{day:%Y%m%d}.json")
        missing += [(day, code) for code in codes if code not in have]
    return missing


def backfill(
    missing: list[tuple[date, str]], out: Path, *, minutes: float, pause: float
) -> tuple[int, int, int]:
    """在時間額度內依序補。回傳 (補到, 空表, 失敗) 的筆數。"""
    out.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + minutes * 60
    current: date | None = None
    data: Weekly = {}
    done = empty = failed = 0
    for i, (day, code) in enumerate(missing):
        if time.monotonic() > deadline:
            print(f"時間到,還缺 {len(missing) - i} 筆", flush=True)
            break
        if day != current:
            if current is not None:
                save(out / f"{current:%Y%m%d}.json", data)
            current, data = day, load(out / f"{day:%Y%m%d}.json")
        try:
            week = fetch_week(day, code)
        # IncompleteRead 之類的 HTTPException 不是 OSError:集保偶爾回應到一半就斷
        # (2026-10-07 第一次長跑在第 236 筆整個停掉),一樣算這一筆失敗、下次再查
        except (OSError, ValueError, http.client.HTTPException) as exc:
            failed += 1
            if failed <= SHOW_FAILURES:
                print(f"  {day} {code} 失敗:{type(exc).__name__}", flush=True)
            time.sleep(pause * 4)
            continue
        if week.bands:
            data[code] = {k: [b.people, b.shares, b.pct] for k, b in week.bands.items()}
            done += 1
            if done % FLUSH_EVERY == 0:
                save(out / f"{day:%Y%m%d}.json", data)
        else:
            empty += 1
        time.sleep(pause)
    if current is not None:
        save(out / f"{current:%Y%m%d}.json", data)
    return done, empty, failed


def main(argv: list[str]) -> int:
    """在時間額度內盡量補。補完或時間到都回 0;查詢頁打不開回 1。"""
    parser = argparse.ArgumentParser(
        prog="fetch_tdcc_history", description="往回補集保單檔股權分散表"
    )
    parser.add_argument("--weeks", type=int, default=8, help="往回補幾週(含最新一週)")
    parser.add_argument("--minutes", type=float, default=30, help="這一次最多花幾分鐘")
    parser.add_argument("--pause", type=float, default=0.5, help="每個股票週之間停幾秒")
    args = parser.parse_args(argv)
    try:
        offered = available_weeks()
    except (OSError, http.client.HTTPException) as exc:
        print(f"查詢頁打不開:{exc}", file=sys.stderr)
        return 1
    have_snapshot = snapshot_days()
    weeks = [w for w in offered[: args.weeks] if w not in have_snapshot]
    codes = universe()
    missing = todo(weeks, codes, OUT)
    print(
        f"補 {len(weeks)} 週 × {len(codes)} 檔 = {len(weeks) * len(codes)} 筆,"
        f"還缺 {len(missing)} 筆",
        flush=True,
    )
    if not missing:
        return 0
    done, empty, failed = backfill(missing, OUT, minutes=args.minutes, pause=args.pause)
    print(
        f"這次補了 {done} 筆;空表 {empty} 筆、失敗 {failed} 筆(下次會再查)", flush=True
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
