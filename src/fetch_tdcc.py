"""存一份集保全市場股權分散快照。

這個來源只有最新一週,舊的拿不回來 —— 所以每週存檔的價值完全來自持續性,
今天沒存的那一週永遠補不回來。

以資料日期命名,重複執行不會重覆寫入,可以安心每天跑。
"""

from __future__ import annotations

import sys
from pathlib import Path

from src import cli
from src.tdcc import fetch_snapshot, snapshot_day


ARCHIVE = Path("data/raw/tdcc")


def main() -> int:
    """抓一份快照存起來。已經有同一個資料日期的檔案就不動它。"""
    cli.no_args(__doc__)
    text = fetch_snapshot()
    day = snapshot_day(text)
    if day is None:
        print("快照裡讀不到資料日期,不存檔", file=sys.stderr)
        return 1
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    target = ARCHIVE / f"dispersion_{day:%Y%m%d}.csv"
    if target.exists():
        print(f"{target} 已經有了,跳過")
        return 0
    target.write_text(text, encoding="utf-8")
    print(f"存好 {target}({len(text):,} 字元,資料日期 {day})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
