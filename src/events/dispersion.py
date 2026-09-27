"""大戶籌碼的事件來源。

knowable = 資料日期 + 5 天。集保的股權分散表以週為單位,資料日期是當週的
結算日,實際公布要再過幾天 —— 用資料日期當進場點是偷看未來。

五天是保守的估計:查詢頁最新一週的資料日期是週四或週五,而今天(週日)就
查得到,所以真實時滯大約 2–3 天。多留兩天不會讓結論變好,只會讓它更穩。
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from src.study import Event


if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from src.tdcc import Week

#: 集保資料日期到實際可交易之間的時滯
PUBLISH_LAG = timedelta(days=5)


def events(
    weeks: Iterable[Week],
    tag: Callable[[Week | None, Week], dict[str, object]] | None = None,
) -> list[Event]:
    """一檔股票的每一週變成一個事件。

    tag 收 (前一週, 這一週) 兩個參數 —— 大戶籌碼的研究測的是**變化量**,
    所以標籤幾乎一定要看得到前一週。第一週的前一週是 None。
    """
    ordered = sorted(weeks, key=lambda w: w.day)
    out: list[Event] = []
    for i, week in enumerate(ordered):
        before = ordered[i - 1] if i else None
        out.append(
            Event(
                code=week.code,
                happened=week.day,
                knowable=week.day + PUBLISH_LAG,
                tags={} if tag is None else tag(before, week),
            )
        )
    return out
