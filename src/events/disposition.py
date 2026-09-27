"""處置股的事件來源。

以**出關日**對齊,不是公告日 —— 處置長度有 5 日也有 10 日,用公告日對齊會
把兩種混在一起([#13])。

knowable = 公告日。處置公告是盤後發布的,所以框架的嚴格不等式
(進場必須晚於 knowable)剛好對應「公告當天收盤不能買」。沒有公告日的
舊資料退回出關日,那等於不設限 —— 出關日本來就是事先知道的。
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from src.study import Event


if TYPE_CHECKING:
    import pandas as pd


def events(punishes: pd.DataFrame) -> list[Event]:
    """每一次處置變成一個事件,原點是出關日。

    punishes 要有 code / release / announced / nth 這幾欄。
    """
    return [
        Event(
            code=str(row["code"]),
            happened=row["release"],
            knowable=(
                row["announced"]
                if isinstance(row.get("announced"), date)
                else row["release"]
            ),
            tags={
                "nth": int(row["nth"]) if row.get("nth") else 0,
                "truly_released": bool(row.get("truly_released", True)),
                # 舊管線算得出超額報酬嗎。框架自己會算,但比對的時候
                # 兩邊的條件要一致
                "has_excess": row.get("excess") == row.get("excess"),
            },
        )
        for row in punishes.to_dict("records")
    ]
