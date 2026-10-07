"""回填櫃買中心的可轉債條款看板(RSdrs001)日存檔(#26)。

用法:.venv/bin/python -m src.fetch_cbboard 2017-01-01 2026-10-07

一個月一個列表請求(`POST /www/zh-tw/bond/cbDaily`,
`date=YYYY/MM/DD&fileCode=cbdrs001`),回那個月每個交易日的看板路徑;再逐檔
下載。**列表請求一定要帶 Referer**,少了會被擋 —— 第二輪誤判「觀測站拒絕自動
存取」就是同一個原因。歷史從 2017-01-17 開始,更早的月份列表是空的。

存成 data/raw/cbboard/年/RSdrs001.YYYYMMDD-C.csv.gz(原始位元組 gzip)。
已經存在的檔案跳過,所以中斷了直接重跑就好。

每一份下載下來都先過 `cbboard.parse` 才存:0 byte 的回應、導向來的錯誤頁、
DATADATE 跟列表日期對不上的,一律**不存**並記成失敗 —— 存進去就會在之後被
讀成「那天沒有資料」。

對櫃買客氣一點:每個請求之間至少停 PAUSE 秒,失敗會退避重試。
"""

from __future__ import annotations

import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src import cli
from src.cbboard import board_path, months, parse, parse_listing
from src.net import TLS
from src.tpex import UA


if TYPE_CHECKING:
    from collections.abc import Callable


HOST = "https://www.tpex.org.tw"
LISTING_URL = f"{HOST}/www/zh-tw/bond/cbDaily"
REFERER = f"{HOST}/zh-tw/bond/info/statistics-cb/day.html"
RAW = Path("data/raw/cbboard")
#: 每個請求之間的停頓(秒)
PAUSE = 0.8
#: 一個請求最多試幾次
TRIES = 4
#: 研究期間的起點:更早的月份列表是空的(第五輪實測)
HISTORY_START = date(2017, 1, 1)


def _request(url: str, data: bytes | None = None) -> bytes:
    """打一次請求,失敗退避重試。最後一次還失敗就把例外丟出去。"""
    headers = {**UA, "Referer": REFERER}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    attempt = 0
    while True:
        # S310:網址由本模組的常數與列表回的路徑拼成,不是任意的外部輸入
        req = urllib.request.Request(url, data=data, headers=headers)  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=60, context=TLS) as resp:  # noqa: S310
                body: bytes = resp.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            attempt += 1
            if attempt >= TRIES:
                raise
            time.sleep(PAUSE * 5 * 2**attempt)
            continue
        time.sleep(PAUSE)
        return body


def listing(month: date, file_code: str = "cbdrs001") -> list[tuple[date, str]]:
    """一個月的 (資料日期, 檔案路徑)。file_code:cbdrs001 看板、rsta0113 日行情(#64)。"""
    form = urllib.parse.urlencode({"date": f"{month:%Y/%m/%d}", "fileCode": file_code})
    payload: dict[str, Any] = json.loads(_request(LISTING_URL, form.encode()))
    return parse_listing(payload)


def fetch_month(
    month: date,
    root: Path,
    file_code: str = "cbdrs001",
    read: Callable[[bytes], date] | None = None,
    where: Callable[[Path, date], Path] = board_path,
) -> tuple[int, int, list[str]]:
    """抓一個月。回傳 (新存的份數, 已經有的份數, 失敗說明)。

    read 把原始位元組解成「檔案裡寫的日期」,解不出來要拋 ValueError(BoardError、
    QuoteError 都是);預設是看板。每份先過它才存。
    """
    read = read or (lambda raw: parse(raw).day)
    saved = skipped = 0
    failed: list[str] = []
    for day, path in listing(month, file_code):
        dest = where(root, day)
        if dest.exists():
            skipped += 1
            continue
        try:
            raw = _request(HOST + path)
            stamped = read(raw)
        except (OSError, ValueError) as exc:
            failed.append(f"{day} {type(exc).__name__}: {exc}")
            continue
        if stamped != day:
            failed.append(f"{day} 檔案裡的 DATADATE 是 {stamped}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(gzip.compress(raw))
        saved += 1
    return saved, skipped, failed


def main(argv: list[str]) -> int:
    """逐月回填。單月失敗不中斷,最後回報。"""
    start, end = cli.date_range(__doc__, argv[1:])
    start = max(start, HISTORY_START)
    failed: list[str] = []
    saved = skipped = 0
    for month in months(start, end):
        try:
            got, had, bad = fetch_month(month, RAW)
        except (OSError, ValueError) as exc:
            failed.append(f"{month:%Y-%m} 列表 {type(exc).__name__}: {exc}")
            print(f"  {month:%Y-%m} 列表失敗:{exc}", flush=True)
            continue
        saved += got
        skipped += had
        failed.extend(bad)
        print(
            f"  {month:%Y-%m} 新存 {got}、已有 {had}、失敗 {len(bad)}",
            flush=True,
        )
        for line in bad:
            print(f"    {line}", flush=True)
    print(f"完成:新存 {saved} 份、已有 {skipped} 份、失敗 {len(failed)} 件")
    for line in failed:
        print(f"  失敗 {line}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
