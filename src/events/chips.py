"""籌碼面的事件來源(#60,事前登記見 issue)。

三大法人當天收盤後公布、融資融券當天晚上公布,所以事件日當天收盤之後才知道:
knowable = 事件日,框架的嚴格不等式讓進場最早是下一個交易日收盤。

四種事件:
- H1 / H2:投信 / 外資連續 5 個交易日買超,事件日 = 剛好連到第 5 天
- H3 籌碼沉澱:過去 20 日(還原)股價漲 ≥ 10% 而且融資餘額減少 ≥ 10%
- H4 軋空:券資比 ≥ 30% 而且融券餘額比 5 個交易日前多

都只算「第一次」:同一檔前 60 個交易日內出現過同一種條件就不算,避免同一段
行情重複計數(#21 的死法是期間叢聚)。
"""

from __future__ import annotations

import pandas as pd


#: 連續買超幾天
STREAK = 5
#: 「第一次」:前幾個交易日內出現過就不算
COOLDOWN = 60
#: H3:回看幾個交易日、漲多少、融資減多少
RALLY_DAYS = 20
RALLY_MIN = 0.10
MARGIN_CUT = -0.10
#: H4:券資比門檻、融券要比幾天前多
SHORT_RATIO = 0.30
SHORT_LOOKBACK = 5

Hit = tuple[str, pd.Timestamp]


def first_only(
    hits: list[Hit], days: pd.DatetimeIndex, cooldown: int = COOLDOWN
) -> list[Hit]:
    """同一檔,前 cooldown 個交易日內條件出現過就不算。被丟掉的那次也算「出現過」。"""
    pos = {day: i for i, day in enumerate(days)}
    kept: list[Hit] = []
    last: dict[str, int] = {}
    for code, day in sorted(hits, key=lambda h: (h[0], h[1])):
        at = pos[day]
        if code not in last or at - last[code] > cooldown:
            kept.append((code, day))
        last[code] = at
    return sorted(kept, key=lambda h: (h[1], h[0]))


def streak(
    flows: pd.DataFrame, column: str, days: pd.DatetimeIndex, k: int = STREAK
) -> list[Hit]:
    """某一類法人連續 k 個交易日買超(> 0),剛好連到第 k 天的那天。

    沒有那一天的資料(沒成交、不在名單)就算中斷 —— 連續要真的每天都買。
    """
    wide = flows.pivot_table(index="day", columns="code", values=column).reindex(days)
    buying = (wide > 0).astype(int)
    # 連續天數 = 累計買超天數 − 上一次中斷時的累計(遇到沒買超就歸零)
    total = buying.cumsum()
    run = total - total.where(buying == 0).ffill().fillna(0)
    return _hits(run == k, days)


def _hits(mask: pd.DataFrame, days: pd.DatetimeIndex) -> list[Hit]:
    """寬表裡為真的 (代號, 日期),再只留「第一次」。"""
    rows, cols = mask.fillna(False).to_numpy(dtype=bool).nonzero()
    index = pd.DatetimeIndex(mask.index)
    names = [str(c) for c in mask.columns]
    found = [(names[int(c)], index[int(r)]) for r, c in zip(rows, cols, strict=True)]
    return first_only(found, days)


def rally_on_margin_cut(closes: pd.DataFrame, margin: pd.DataFrame) -> list[Hit]:
    """H3:過去 RALLY_DAYS 個交易日,還原收盤漲 ≥ 10%、融資餘額減 ≥ 10%。

    closes、margin 都是 交易日 × 代號 的寬表,索引要一樣。
    """
    rose = closes / closes.shift(RALLY_DAYS) - 1 >= RALLY_MIN
    cut = margin / margin.shift(RALLY_DAYS) - 1 <= MARGIN_CUT
    both = rose & cut.reindex_like(rose).fillna(False)
    return _hits(both, pd.DatetimeIndex(closes.index))


def short_squeeze(margin: pd.DataFrame, short: pd.DataFrame) -> list[Hit]:
    """H4:券資比(融券 ÷ 融資)≥ 30%,而且融券餘額比 SHORT_LOOKBACK 個交易日前多。"""
    ratio = short / margin.where(margin > 0)
    rising = short > short.shift(SHORT_LOOKBACK)
    return _hits((ratio >= SHORT_RATIO) & rising, pd.DatetimeIndex(margin.index))
