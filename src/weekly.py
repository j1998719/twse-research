"""每一檔、每一週的大戶比例與人數,加上同一週的還原收盤價(#49)。

爸爸要的篩選是「過去 n 週大戶增加多少、但股價沒什麼動」。週資料有兩個來源,
級距的寫法不一樣(見 tdcc.py):

* 全市場快照(data/raw/tdcc/)用分級編號:12、13、14、15 = 400、600、800、1000 張以上
* 單檔查詢頁往回補的(data/raw/tdcc_weeks/,fetch_tdcc_history)用級距文字

這裡把兩邊對齊成同一個形狀:每週每檔 [400+, 600+, 800+, 1000+] 四級各自的佔比
與人數(跟 bigholders.json 的 pct / people 同一個順序,網頁一樣從某一級往上加總)。
同一週兩邊都有時用全市場快照。

股價變動要跟大戶變化用**同一段期間**:每一週取集保資料日期當天(或之前最後一個
交易日)的還原收盤價 —— 還原過才不會把除權息的跳空當成股價下跌。
"""

from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING, Any

import pandas as pd

from src.tdcc import parse_snapshot, snapshot_day


if TYPE_CHECKING:
    from pathlib import Path

#: 400 張以上的四個級距(全市場快照的分級編號),由小到大。網頁用索引對應門檻,順序不能動
BIG_LEVELS = (12, 13, 14, 15)
#: 跟 BIG_LEVELS 一一對應的級距文字(單檔查詢頁的寫法)
BIG_LABELS = (
    "400,001-600,000",
    "600,001-800,000",
    "800,001-1,000,000",
    "1,000,001以上",
)

#: 一檔一週:([四級佔比], [四級人數])
Week = tuple[list[float], list[int]]


def from_snapshot(text: str) -> dict[str, Week]:
    """全市場快照 → 代號 -> 四級。缺的級距是 0(那一級沒有人)。"""
    out: dict[str, Week] = {}
    for code, bands in parse_snapshot(text).items():
        pct = [bands[lv].pct if lv in bands else 0.0 for lv in BIG_LEVELS]
        people = [bands[lv].people if lv in bands else 0 for lv in BIG_LEVELS]
        out[code] = (pct, people)
    return out


def from_history(data: dict[str, dict[str, list[float]]]) -> dict[str, Week]:
    """單檔查詢頁補回來的一週 → 代號 -> 四級。級距值是 [人數, 股數, 佔比]。"""
    out: dict[str, Week] = {}
    for code, bands in data.items():
        rows = [bands.get(label) for label in BIG_LABELS]
        pct = [float(r[2]) if r else 0.0 for r in rows]
        people = [int(r[0]) if r else 0 for r in rows]
        out[code] = (pct, people)
    return out


def load_weeks(
    archive: Path, history: Path, max_weeks: int = 9
) -> tuple[list[date], dict[date, dict[str, Week]]]:
    """最近 max_weeks 週(新的在前)與每週的資料。快照優先於單檔歷史。"""
    weeks: dict[date, dict[str, Week]] = {}
    for path in sorted(history.glob("*.json")) if history.exists() else []:
        try:
            day = date.fromisoformat(
                f"{path.stem[:4]}-{path.stem[4:6]}-{path.stem[6:8]}"
            )
            weeks[day] = from_history(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, json.JSONDecodeError):
            continue
    for path in archive.glob("dispersion_*.csv"):
        text = path.read_text(encoding="utf-8")
        snap_day = snapshot_day(text)
        if snap_day is not None:
            weeks[snap_day] = {**weeks.get(snap_day, {}), **from_snapshot(text)}
    order = sorted(weeks, reverse=True)[:max_weeks]
    return order, {d: weeks[d] for d in order}


def week_closes(
    adjusted: pd.DataFrame, days: list[date]
) -> dict[str, list[float | None]]:
    """每檔在每個週次日期(當天或之前最後一個交易日)的還原收盤價,順序同 days。"""
    if adjusted.empty or not days:
        return {}
    wide = adjusted.pivot_table(
        index="day", columns="code", values="adj_close"
    ).sort_index()
    targets = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    at = wide.reindex(wide.index.union(targets)).ffill().loc[targets]
    out: dict[str, list[float | None]] = {}
    for code in at.columns:
        values = at[code].tolist()
        out[str(code)] = [None if pd.isna(v) else round(float(v), 3) for v in values]
    return out


def fields(
    code: str,
    days: list[date],
    weeks: dict[date, dict[str, Week]],
    closes: dict[str, list[float | None]],
) -> dict[str, list[Any]]:
    """一檔的週資料,順序同 days(新的在前)。那一週沒有這檔就是 null。"""
    pct: list[Any] = []
    people: list[Any] = []
    for d in days:
        hit = weeks[d].get(code)
        pct.append(None if hit is None else [round(p, 2) for p in hit[0]])
        people.append(None if hit is None else hit[1])
    return {
        "weekPct": pct,
        "weekPeople": people,
        "weekClose": list(closes.get(code, [None] * len(days))),
    }
