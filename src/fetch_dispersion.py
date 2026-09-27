"""抓一批股票的集保股權分散歷史。

查詢頁只有約 52 週,而且 SYNCHRONIZER_TOKEN 是一次性的 —— 一檔一週要兩個
請求。所以這支只跑指定的少數幾檔,不要拿來掃全市場。

每檔存成一個 JSON,已經有的週次會跳過,可以重複執行把漏掉的補齊。
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

from src.tdcc import BIG_BAND, available_weeks, fetch_week


ARCHIVE = Path("data/raw/tdcc/history")
#: 失敗重試幾次。查詢頁偶爾會回半截的內容
RETRIES = 4
#: 每個請求之間歇一下,不要打人家的站
PAUSE = 0.8
#: 命令列參數個數:程式名 + 清單檔
ARGC = 2


def _as_date(stamp: str) -> date:
    return date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))


def _path(code: str) -> Path:
    return ARCHIVE / f"{code}.json"


def load(code: str) -> dict[str, dict[str, dict[str, float]]]:
    """讀已經抓好的部分。沒有就回空的。"""
    path = _path(code)
    if not path.exists():
        return {}
    loaded: dict[str, dict[str, dict[str, float]]] = json.loads(
        path.read_text(encoding="utf-8")
    )
    return loaded


def fetch_code(code: str, weeks: list[str]) -> int:
    """把這一檔缺的週次補齊,回傳這次新抓到幾週。"""
    have = load(code)
    missing = [w for w in weeks if w not in have]
    if not missing:
        print(f"{code}: 已經齊了({len(have)} 週)")
        return 0
    got = 0
    for stamp in missing:
        day = _as_date(stamp)
        for _ in range(RETRIES):
            try:
                week = fetch_week(day, code)
            except (OSError, ValueError):
                time.sleep(PAUSE * 3)
                continue
            if week.big is not None:
                have[stamp] = {
                    key: {
                        "people": band.people,
                        "shares": band.shares,
                        "pct": band.pct,
                    }
                    for key, band in week.bands.items()
                }
                got += 1
                break
            time.sleep(PAUSE * 3)
        time.sleep(PAUSE)
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    _path(code).write_text(json.dumps(have, ensure_ascii=False), encoding="utf-8")
    missing_after = [w for w in weeks if w not in have]
    note = f",還缺 {len(missing_after)} 週" if missing_after else ""
    print(f"{code}: +{got} 週,共 {len(have)} 週{note}", flush=True)
    return got


def main(argv: list[str]) -> int:
    """用法:python -m src.fetch_dispersion <代號清單檔>"""
    if len(argv) != ARGC:
        print(__doc__, file=sys.stderr)
        print("用法:python -m src.fetch_dispersion <代號清單檔>", file=sys.stderr)
        return 2
    codes = [
        line.strip()
        for line in Path(argv[1]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    weeks = [f"{d:%Y%m%d}" for d in available_weeks()]
    print(f"{len(codes)} 檔 × {len(weeks)} 週,千張級距是「{BIG_BAND}」", flush=True)
    for code in codes:
        fetch_code(code, weeks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
