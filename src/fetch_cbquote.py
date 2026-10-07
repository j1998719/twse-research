"""回填可轉債每日成交行情(櫃買 rsta0113,#64)。

跟條款看板同一個端點、同一套回填(fetch_cbboard.fetch_month):一個月一個列表請求、
逐檔下載、每份先解析驗過才存、gzip、已存在就跳過(可中斷續跑)、每個請求停 0.8 秒。
存成 data/raw/cbquote/年/RSta0113.YYYYMMDD-C.csv.gz。歷史從 2017-01 開始。

用法:.venv/bin/python -m src.fetch_cbquote 2017-01-01 2026-10-07
"""

from __future__ import annotations

import sys
from pathlib import Path

from src import cli
from src.cbboard import months
from src.cbquote import parse_quotes, quote_path
from src.fetch_cbboard import HISTORY_START, fetch_month


RAW = Path("data/raw/cbquote")
FILE_CODE = "rsta0113"


def main(argv: list[str]) -> int:
    """逐月回填。單月失敗不中斷,最後回報。"""
    start, end = cli.date_range(__doc__, argv[1:])
    failed: list[str] = []
    saved = skipped = 0
    for month in months(max(start, HISTORY_START), end):
        try:
            got, had, bad = fetch_month(
                month, RAW, FILE_CODE, lambda raw: parse_quotes(raw).day, quote_path
            )
        except (OSError, ValueError) as exc:
            failed.append(f"{month:%Y-%m} 列表 {type(exc).__name__}: {exc}")
            print(f"  {month:%Y-%m} 列表失敗:{exc}", flush=True)
            continue
        saved, skipped = saved + got, skipped + had
        failed.extend(bad)
        print(f"  {month:%Y-%m} 新存 {got}、已有 {had}、失敗 {len(bad)}", flush=True)
    print(f"完成:新存 {saved} 份、已有 {skipped} 份、失敗 {len(failed)} 件")
    for line in failed:
        print(f"  失敗 {line}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
