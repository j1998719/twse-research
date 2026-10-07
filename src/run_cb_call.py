"""可轉債強制贖回對標的股的影響:跑 #61 事前登記的 2 個檢定。

事件 = 一檔債的贖回欄位第一次出現在看板上那天(公司實際宣布的強制贖回;提前天數
中位 19 天),只取價內的(標的股價 ≥ 轉換價):持有人會轉換成股票,大量新股流入。
價外的(通常是餘額太少的清償條款)只描述,不進檢定。

下一個交易日收盤進場,持有 5 / 20 個交易日。報酬跟 #22 框架同一套(扣成本、扣等權
宇集、漲跌停順延、還原除權息)。比較對象是安慰劑:有發過可轉債的標的股 × 同期隨機
交易日,Mann-Whitney 雙尾,一次 BH(#60 的教訓,不跟 0 比)。
形成 2017–2021、驗證 2022 起。

用法:.venv/bin/python -m src.run_cb_call
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from src import cli
from src.cbboard import load_boards
from src.events.chips import first_only
from src.run_cb import BOARDS, Data
from src.run_chip_signals import placebo_hits, scored, summarize


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from src.cbboard import Board
    from src.events.chips import Hit


@dataclass(frozen=True)
class Row:
    """一個持有期:事件和安慰劑的摘要,以及事件 vs 安慰劑的 Mann-Whitney p。"""

    horizon: int
    event: dict[str, float]
    placebo: dict[str, float]
    p: float

    def apart(self) -> bool:
        """事件和安慰劑的群集 CI 不重疊。"""
        e, b = self.event, self.placebo
        return e["high"] < b["low"] or e["low"] > b["high"]


#: 形成期最後一天(含)
FORMATION_END = pd.Timestamp("2021-12-31")
HORIZONS = (5, 20)
ALPHA = 0.05


def call_events(
    boards: Sequence[Board], days: pd.DatetimeIndex
) -> tuple[list[Hit], list[Hit]]:
    """(價內, 價外)的強制贖回事件,以標的股代號表示。

    看板第一天就已經有贖回欄位的債是左設限,排除。同一檔標的 60 個交易日內只算第一次。
    """
    seen: set[str] = set()
    itm: list[Hit] = []
    otm: list[Hit] = []
    trading = set(days)
    for i, board in enumerate(boards):
        day = pd.Timestamp(board.day)
        for bond in board.bonds:
            if bond.call_start is None or bond.code in seen:
                continue
            seen.add(bond.code)
            if i == 0 or day not in trading:
                continue
            inside = (
                bond.stock_price is not None
                and bond.conversion_price is not None
                and bond.stock_price >= bond.conversion_price
            )
            (itm if inside else otm).append((bond.underlying, day))
    return first_only(itm, days), first_only(otm, days)


def main() -> int:
    """2 個檢定、BH、群集 CI 與安慰劑比較、樣本外、價外描述。"""
    cli.no_args(__doc__)
    boards = load_boards(BOARDS)
    data = Data(boards)
    days = pd.DatetimeIndex([pd.Timestamp(d) for d in data.days])
    itm, otm = call_events(boards, days)
    underlyings = sorted(
        {b.underlying for board in boards for b in board.bonds} & set(data.closes)
    )
    print(
        f"強制贖回事件:價內 {len(itm)}、價外 {len(otm)};有發過可轉債的標的 {len(underlyings)} 檔\n"
    )

    def anywhere(_c: str, _d: pd.Timestamp) -> bool:
        return True

    def run(
        hits: list[Hit],
        keep: Callable[[str, pd.Timestamp], bool],
        lo: pd.Timestamp,
        hi: pd.Timestamp,
    ) -> list[Row]:
        base = placebo_hits(underlyings, days[(days >= lo) & (days <= hi)])
        out = []
        for h in HORIZONS:
            ev = scored([x for x in hits if keep(*x)], h, days, data.excess, anywhere)
            null = scored(base, h, days, data.excess, anywhere)
            s, s0 = summarize(ev, data.market_of), summarize(null, data.market_of)
            p = float(
                stats.mannwhitneyu(
                    ev.excess, null.excess, alternative="two-sided"
                ).pvalue
            )
            out.append(Row(h, s, s0, p))
        return out

    def show(
        label: str, rows: list[Row], corrected: Sequence[float] | None
    ) -> list[bool]:
        print(label)
        found = []
        for i, r in enumerate(rows):
            s, s0 = r.event, r.placebo
            q = corrected[i] if corrected is not None else r.p
            ok = q < ALPHA and r.apart()
            found.append(ok)
            print(
                f"  持有 {r.horizon:>2} 日:事件 n={s['n']} 中位數 {s['median']:+.2f}% 勝率 {s['win']:.1f}%"
                f" CI [{s['low']:+.2f},{s['high']:+.2f}]  |  安慰劑 n={s0['n']} {s0['median']:+.2f}%"
                f" CI [{s0['low']:+.2f},{s0['high']:+.2f}]  |  差 {s['median'] - s0['median']:+.2f}"
                f"  {'BH ' if corrected is not None else ''}p={q:.4f}  {'找到了' if ok else '—'}"
            )
        return found

    first = pd.Timestamp(data.days[0])
    formation = run(itm, lambda _c, d: d <= FORMATION_END, first, FORMATION_END)
    q = list(multipletests([r.p for r in formation], method="fdr_bh")[1])
    found = show("形成組(2017–2021,價內,⚠️ 小樣本先導),一次 BH:", formation, q)

    last = pd.Timestamp(data.days[-1])
    if any(found):
        later = run(itm, lambda _c, d: d > FORMATION_END, FORMATION_END, last)
        show(
            "\n驗證組(2022 起,只看「找到了」的持有期,不再校正):",
            [r for r, f in zip(later, found, strict=True) if f],
            None,
        )
    else:
        print("\n形成組沒有「找到了」,照登記不跑驗證組。")
    show(
        "\n描述(不是檢定):價外的強制贖回,全期",
        run(otm, lambda _c, _d: True, first, last),
        None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
