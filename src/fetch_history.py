"""長期均線用的日線:上市加上櫃,只留代號、日期、收盤。

用法:.venv/bin/python -m src.fetch_history 2016-01-01 2026-10-06

十年線要約 2,400 個交易日,處置股研究的 prices.csv 只從 2020 開始。
不直接把那份拉長,是因為 build_report 用它的第一天當「資料期間」,
也拿它算全市場的統計 —— 拉長會改到處置股報告。所以另外輸出一份
data/out/long_prices.csv,快取跟 fetch_prices、fetch_tpex 共用,
2020 以後的日子不會重抓。
"""

from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

from src.fetch_prices import RAW as TWSE_RAW
from src.fetch_tpex import RAW as TPEX_RAW
from src.prices import fetch_day, parse_day, weekdays
from src.tpex import cached_quotes, parse_quotes


OUT = Path("data/out/long_prices.csv")
ARGC = 3


def main(argv: list[str]) -> int:
    """逐日抓兩個市場。單日失敗記下來,最後回報。"""
    if len(argv) != ARGC:
        print(__doc__, file=sys.stderr)
        return 2
    days = weekdays(date.fromisoformat(argv[1]), date.fromisoformat(argv[2]))
    failed: list[str] = []
    rows = 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["code", "day", "close", "market"])
        for i, day in enumerate(days, 1):
            try:
                listed = fetch_day(day, TWSE_RAW)
                otc = cached_quotes(day, TPEX_RAW / "prices")
            except (OSError, ValueError) as exc:
                failed.append(f"{day} {type(exc).__name__}")
                continue
            for bar in parse_day(listed, day) if listed else []:
                if bar.close is not None:
                    writer.writerow([bar.code, day, bar.close, "twse"])
                    rows += 1
            for quote in parse_quotes(otc, day) if otc else []:
                if quote.close is not None:
                    writer.writerow([quote.code, day, quote.close, "otc"])
                    rows += 1
            if i % 100 == 0 or i == len(days):
                print(f"  [{i}/{len(days)}] {day} 累計 {rows} 列", flush=True)
    print(f"寫出 {OUT}:{rows} 列")
    if failed:
        # 缺幾天對 2,400 日的平均影響很小,但要讓人看得到
        print(f"有 {len(failed)} 天失敗:{', '.join(failed[:10])}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
