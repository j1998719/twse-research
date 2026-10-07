"""可轉債的稀釋 / 新股供給對標的股的影響:跑 #63 事前登記的 4 個檢定。

- D 重設:轉換價下降 ≥ 5%,而且對不上前後 60 天內任何除權息 / 減資的還原因子
  (±1 個百分點)。看板上 2,464 次轉換價下降裡,77% 對得上除權息,是反稀釋的機械
  調整,不是重設。⚠️ 這是推論出來的分法,重設公告的來源還沒接
- E 大量轉換:月底餘額比上一次少 ≥ 20%,不在強制贖回期、不在賣回日前後 45 天
  (賣回是公司買回,不是轉換)

事件日 = 新數字第一次出現在看板上那天;流程跟 #61 / #62 一樣,但 D、E 的 4 個檢定
一次 BH(run_cb_call.family)。

用法:.venv/bin/python -m src.run_cb_supply
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from src import cli
from src.cbboard import load_boards
from src.events.chips import first_only
from src.run_cb import BOARDS
from src.run_cb_call import Setting, family
from src.universe import all_actions


if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.cbboard import Board
    from src.events.chips import Hit

#: D:轉換價至少降多少才算重設候選
RESET_MIN = -0.05
#: D:跟除權息因子差多少以內算「是除權息調整」、找多遠
FACTOR_TOL = 0.01
FACTOR_WINDOW = 60
#: E:餘額至少少多少;賣回日前後幾天不算
DRAIN_MIN = -0.20
PUT_WINDOW = 45


def reset_events(
    boards: Sequence[Board], days: pd.DatetimeIndex, actions: pd.DataFrame
) -> list[Hit]:
    """D:對不上除權息因子的轉換價下降(≥ 5%),第一次出現在看板上那天。"""
    factors: dict[str, list[tuple[pd.Timestamp, float]]] = {}
    for code, day, factor in zip(
        actions.code, actions.day, actions.factor, strict=True
    ):
        factors.setdefault(str(code), []).append((pd.Timestamp(day), float(factor)))
    trading = set(days)
    prev: dict[str, float] = {}
    hits: list[Hit] = []
    for i, board in enumerate(boards):
        day = pd.Timestamp(board.day)
        for bond in board.bonds:
            now, before = bond.conversion_price, prev.get(bond.code)
            if now is not None:
                prev[bond.code] = now
            if i == 0 or now is None or before is None or day not in trading:
                continue
            ratio = now / before
            if ratio - 1 > RESET_MIN:
                continue
            near = [
                f
                for d, f in factors.get(bond.underlying, [])
                if abs((d - day).days) <= FACTOR_WINDOW
            ]
            if not any(abs(ratio - f) <= FACTOR_TOL for f in near):
                hits.append((bond.underlying, day))
    return first_only(hits, days)


def conversion_events(boards: Sequence[Board], days: pd.DatetimeIndex) -> list[Hit]:
    """E:月底餘額少 ≥ 20%(不在贖回期、不在賣回日附近),第一次出現在看板上那天。"""
    trading = set(days)
    prev: dict[str, int] = {}
    hits: list[Hit] = []
    for i, board in enumerate(boards):
        day = pd.Timestamp(board.day)
        for bond in board.bonds:
            now, before = bond.outstanding, prev.get(bond.code)
            if now is not None:
                prev[bond.code] = now
            if i == 0 or now is None or not before or day not in trading:
                continue
            near_put = (
                bond.put_start is not None
                and abs((pd.Timestamp(bond.put_start) - day).days) <= PUT_WINDOW
            )
            if (
                now / before - 1 <= DRAIN_MIN
                and bond.call_start is None
                and not near_put
            ):
                hits.append((bond.underlying, day))
    return first_only(hits, days)


def main() -> int:
    """D、E 各 2 個持有期,4 個檢定一次 BH;跟安慰劑比;樣本外。"""
    cli.no_args(__doc__)
    boards = load_boards(BOARDS)
    setting = Setting.load(boards)
    actions = all_actions()
    if actions is None:
        print(
            "沒有還原因子表(corporate_actions.csv),分不出重設和除權息調整;先跑 fetch_actions"
        )
        return 1
    groups = {
        "D 重設": reset_events(boards, setting.days, actions),
        "E 大量轉換": conversion_events(boards, setting.days),
    }
    for label, hits in groups.items():
        print(f"{label}:{len(hits)} 個事件")
    print()
    family(setting, groups)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
