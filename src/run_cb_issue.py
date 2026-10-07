"""可轉債新發行(第一次掛牌)對標的股的影響:跑 #62 事前登記的 2 個檢定。

事件 = 一檔債第一次出現在可轉債條款看板上那天。發行時套利盤常見「買債、空股」
避險,加上未來的股本稀釋,所以推論標的股可能偏弱(還沒驗證)。⚠️ 掛牌前董事會決議、
申報生效都已經公告過,這裡測的是「掛牌之後」,不是公告效果。

流程跟 #61 一樣(run_cb_call 的 Setting / registered):下一個交易日收盤進場、持有
5 / 20 個交易日、跟同期安慰劑比、一次 BH、形成 2017–2021 / 驗證 2022 起。

用法:.venv/bin/python -m src.run_cb_issue
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from src import cli
from src.cbboard import load_boards
from src.events.chips import first_only
from src.run_cb import BOARDS
from src.run_cb_call import Setting, registered


if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.cbboard import Board
    from src.events.chips import Hit


def issue_events(boards: Sequence[Board], days: pd.DatetimeIndex) -> list[Hit]:
    """每檔債第一次出現在看板上的那天(以標的代號表示)。

    看板第一天就在的債是左設限,排除。同一檔標的 60 個交易日內只算第一檔。
    """
    seen: set[str] = set()
    hits: list[Hit] = []
    trading = set(days)
    for i, board in enumerate(boards):
        day = pd.Timestamp(board.day)
        for bond in board.bonds:
            if bond.code in seen:
                continue
            seen.add(bond.code)
            if i > 0 and day in trading:
                hits.append((bond.underlying, day))
    return first_only(hits, days)


def main() -> int:
    """2 個檢定(持有 5 / 20 日)、BH、跟安慰劑比、樣本外。"""
    cli.no_args(__doc__)
    boards = load_boards(BOARDS)
    setting = Setting.load(boards)
    hits = issue_events(boards, setting.days)
    print(
        f"新發行事件 {len(hits)} 筆;有發過可轉債的標的 {len(setting.underlyings)} 檔\\n"
    )
    registered(setting, hits, "新債掛牌")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
