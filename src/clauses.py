"""把處置回溯到觸發它的注意公告,並依條款性質分組。

處置公告只寫「連續三次」「十日內六次」,看不出是哪一款注意把它送進去的。
要往前找那幾則注意,解析裡面的款次。

回溯的窗口跟著處置條件走 —— 「連續三次」只該看前三個營業日,
用固定的三十天會把無關的注意也算進來。
"""

from __future__ import annotations

import re

import pandas as pd


#: 公告文字裡的款次標記,例如「﹝第一款﹞」
CLAUSE_MARK = re.compile(r"﹝第([一二三四五六七八九十]+)款﹞")

ZH_NUMBER = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
    "十三": 13,
    "十四": 14,
}

#: 處置條件 -> 該往前看幾個營業日。條件文字裡寫的就是它的計算窗口
CONDITION_WINDOW = {
    "連續三次": 3,
    "連續五次": 5,
    "最近十個營業日已有六次": 10,
    "最近三十個營業日已有十二次": 30,
    # 上櫃的寫法
    "連續3個營業日": 3,
    "連續5個營業日": 5,
    "最近10個營業日內有6個營業日": 10,
    "最近30個營業日內有12個營業日": 30,
}
#: 條件沒對上時的預設窗口。三十是規則裡最長的回看期間
DEFAULT_WINDOW = 30

#: 依性質分組。分十三款的話每組只剩幾十筆,統計不出東西
FAMILIES: dict[str, frozenset[int]] = {
    "估值": frozenset({6}),
    "價格動能": frozenset({1, 2, 3, 4, 11}),
    "籌碼": frozenset({5, 9, 10, 12, 13}),
    "其他": frozenset({7, 8, 14}),
}


def clauses_in(text: str) -> set[int]:
    """一則注意公告觸發了哪幾款。一則可能同時踩到多款。"""
    return {ZH_NUMBER[zh] for zh in CLAUSE_MARK.findall(str(text)) if zh in ZH_NUMBER}


def window_for(condition: str) -> int:
    """這個處置條件該往前看幾個營業日。

    「及當日沖銷標準」是附加條件,不影響回看的長度,所以先去掉再比對。
    """
    base = str(condition).split("及")[0].strip()
    return CONDITION_WINDOW.get(base, DEFAULT_WINDOW)


def family_of(clause: int) -> str:
    """這一款屬於哪一組。"""
    for name, members in FAMILIES.items():
        if clause in members:
            return name
    return "其他"


def triggering_notices(
    notices: pd.DataFrame,
    days: pd.DatetimeIndex,
    code: object,
    announced: pd.Timestamp,
    window: int,
) -> pd.DataFrame:
    """公告日往前 window 個營業日內,這一檔的注意公告。

    含公告日當天 —— 最後一次注意跟處置公告常常是同一天。
    """
    where = int(days.searchsorted(announced, side="right"))
    start_at = where - window
    start_at = max(start_at, 0)
    if where <= 0:
        return notices.iloc[0:0]
    span = days[start_at:where]
    if len(span) == 0:
        return notices.iloc[0:0]
    return notices[
        (notices["code"] == code)
        & (notices["day"] >= span[0])
        & (notices["day"] <= span[-1])
    ]


def dominant_family(counts: dict[str, int]) -> str | None:
    """哪一組出現最多次。平手或都沒有就回 None,不要硬選一個。"""
    if not counts:
        return None
    top = max(counts.values())
    winners = [name for name, n in counts.items() if n == top]
    return winners[0] if len(winners) == 1 else None


def classify(
    punishes: pd.DataFrame,
    notices: pd.DataFrame,
    days: pd.DatetimeIndex,
) -> pd.DataFrame:
    """每一次處置加上「是由哪些款累積而成」。

    回傳原本的欄位加上:
      clauses       觸發的款次(排序後的 tuple)
      families      各組出現次數
      family        出現最多的那一組;平手或找不到是 None
      notice_count  回溯窗口內找到幾則注意
    """
    rows: list[dict[str, object]] = []
    for record in punishes.to_dict("records"):
        # to_dict 的鍵型別是 Hashable,轉成 str 才好往下傳
        raw: dict[str, object] = {str(k): v for k, v in record.items()}
        window = window_for(str(raw.get("condition", "")))
        found = triggering_notices(
            notices, days, raw["code"], pd.Timestamp(str(raw["announced"])), window
        )
        clauses: set[int] = set()
        counts: dict[str, int] = {}
        for reason in found["reason"]:
            for clause in clauses_in(reason):
                clauses.add(clause)
                name = family_of(clause)
                counts[name] = counts.get(name, 0) + 1
        rows.append(
            {
                **raw,
                "clauses": tuple(sorted(clauses)),
                "families": counts,
                "family": dominant_family(counts),
                "notice_count": len(found),
            }
        )
    return pd.DataFrame(rows)
