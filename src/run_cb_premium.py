"""可轉債深度折價對標的股的影響:跑 #64 事前登記的 2 個檢定。

折溢價 = 債價 ÷ 轉換價值 − 1,轉換價值 = 100 × 標的收盤 ÷ 當天實際有效的轉換價
(events.cb.Ledger,#26 第七輪)。債價有成交用收市、沒成交用參考價(標記 traded)。

事件:有成交的那天折溢價 ≤ −2%(大約最低的 2.5%,大於來回成本),同一檔標的 60
個交易日只算一次。推論的機制:套利盤「買債、賣股」→ 標的偏弱(雙尾檢定)。
流程跟 #61~#63 一樣(run_cb_call.family):下一個交易日收盤進場、持有 5 / 20 日、
跟安慰劑比、一次 BH、2017–2021 形成 / 2022 起驗證。

用法:.venv/bin/python -m src.run_cb_premium
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from src import cli
from src.cbboard import UNDERLYING_LEN, load_boards
from src.cbquote import load_quotes
from src.events.cb import Ledger
from src.events.chips import first_only
from src.run_cb import BOARDS
from src.run_cb_call import Setting, family


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import date

    from src.cbquote import QuoteDay
    from src.events.chips import Hit

QUOTES = Path("data/raw/cbquote")
#: 深度折價的門檻(事前登記)
DISCOUNT = -0.02


def premiums(
    quote_days: Sequence[QuoteDay],
    conversion: Callable[[str, date], float | None],
    stock: dict[str, dict[date, float]],
) -> pd.DataFrame:
    """每個「債 × 日」的折溢價。缺轉換價或標的收盤就跳過。"""
    rows = []
    for qd in quote_days:
        for q in qd.quotes:
            price = q.close if q.close is not None else q.reference
            conv = conversion(q.code, qd.day)
            close = stock.get(q.code[:UNDERLYING_LEN], {}).get(qd.day)
            if not price or not conv or not close:
                continue
            parity = 100 * close / conv
            rows.append((q.code, qd.day, q.close is not None, price / parity - 1))
    return pd.DataFrame(rows, columns=["code", "day", "traded", "prem"])


def discount_events(
    frame: pd.DataFrame, days: pd.DatetimeIndex, threshold: float = DISCOUNT
) -> list[Hit]:
    """有成交而且折溢價 ≤ threshold 的那天(以標的代號表示),60 個交易日只算一次。"""
    hit = frame[frame.traded & (frame.prem <= threshold)]
    trading = set(days)
    found = [
        (str(code)[:UNDERLYING_LEN], pd.Timestamp(day))
        for code, day in zip(hit.code, hit.day, strict=True)
        if pd.Timestamp(day) in trading
    ]
    return first_only(found, days)


def main() -> int:
    """2 個檢定(持有 5 / 20 日)、BH、跟安慰劑比、樣本外。"""
    cli.no_args(__doc__)
    boards = load_boards(BOARDS)
    setting = Setting.load(boards)
    ledger = Ledger(boards)
    frame = premiums(load_quotes(QUOTES), ledger.conversion_price, setting.data.raw)
    hits = discount_events(frame, setting.days)
    traded = frame[frame.traded]
    print(
        f"折溢價:{len(frame):,} 個「債 × 日」(有成交 {len(traded):,});"
        f"折價 ≤ {DISCOUNT:.0%} 的事件 {len(hits)} 筆\n"
    )
    family(setting, {"深度折價 ≤ −2%": hits})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
