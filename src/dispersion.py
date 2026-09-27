"""大戶籌碼的事件定義。

[#18] 證明「千張大戶人數的週變化」不能用:門檻是持股張數,股價漲的時候
原本 900 張的人多買 100 張就跨過去,所以人數是跟著漲的結果(同期
r=0.464 p=0.001,領先 r=0.130 p=0.390)。

這裡測的是不一樣的東西:**轉折**,不是變化量。大戶持股比例從高點回落、
散戶人數創新高,這兩件事在穩懋身上領先價格見頂約兩個月。轉折偵測和
變化量是兩回事,前者還沒被否定。

參數在 [#21] 事前登記過:回看 8 週、回落 2 個百分點。不掃參數 —— 掃的話
檢定數會爆掉,[#14] 就是這樣死的。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import date

    from src.tdcc import Week

#: 回看幾週找高點。事前登記的值,見 [#21]
LOOKBACK = 8
#: 大戶持股比例從高點回落幾個百分點才算轉折
DROP_PP = 2.0


@dataclass(frozen=True)
class Signal:
    """某一週有沒有觸發各個訊號。"""

    day: date
    code: str
    #: 大戶持股比例從前 LOOKBACK 週的高點回落 ≥ DROP_PP 個百分點
    big_rolled_over: bool
    #: 總股東人數創前 LOOKBACK 週新高
    holders_peaked: bool
    #: 大戶持股比例距離前期高點差幾個百分點(正數代表低於高點)
    drop_from_peak: float
    #: 當週的大戶持股比例,方便事後檢查
    big_pct: float

    @property
    def distributing(self) -> bool:
        """兩個訊號同時成立 —— 穩懋實際的形狀:大戶在倒貨給散戶。"""
        return self.big_rolled_over and self.holders_peaked


def _usable(weeks: Iterable[Week]) -> list[Week]:
    """能用的週次,由舊到新。

    讀不到千張級距或總股東人數的週次直接排除,並且把剩下的當成連續的 ——
    跟 tdcc.weekly_changes 一致。中間補一個零會憑空造出轉折。
    """
    return sorted(
        (w for w in weeks if w.big is not None and w.holders is not None),
        key=lambda w: w.day,
    )


def signals(
    weeks: Iterable[Week],
    lookback: int = LOOKBACK,
    drop_pp: float = DROP_PP,
) -> list[Signal]:
    """逐週判斷訊號。

    前 lookback 週沒有足夠的歷史可比,不會出現在結果裡 —— 歷史不足時
    回報「沒觸發」會讓早期的週次看起來是乾淨的對照組,那是假的。

    高點取「前 lookback 週」,不含當週:含當週的話當週永遠是自己的高點,
    回落幅度恆為零,一個事件都不會有。
    """
    usable = _usable(weeks)
    out: list[Signal] = []
    for i in range(lookback, len(usable)):
        now = usable[i]
        prior = usable[i - lookback : i]
        big = now.big
        holders = now.holders
        if big is None or holders is None:  # pragma: no cover - _usable 已經濾掉
            continue
        peak_pct = max(w.big.pct for w in prior if w.big is not None)
        peak_holders = max(w.holders for w in prior if w.holders is not None)
        drop = peak_pct - big.pct
        out.append(
            Signal(
                day=now.day,
                code=now.code,
                big_rolled_over=drop >= drop_pp,
                holders_peaked=holders > peak_holders,
                drop_from_peak=round(drop, 2),
                big_pct=big.pct,
            )
        )
    return out


def triggered(items: Sequence[Signal], name: str) -> list[Signal]:
    """挑出某個訊號成立的週次。

    name 是 Signal 上的布林欄位名,這樣掃三個定義時不用寫三份一樣的迴圈。
    """
    if name not in {"big_rolled_over", "holders_peaked", "distributing"}:
        msg = f"沒有這個訊號:{name}"
        raise ValueError(msg)
    return [s for s in items if getattr(s, name)]
