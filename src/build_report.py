"""產生網頁要用的 report.json。

欄位必須跟 web/src/report.ts 的 REQUIRED_KEYS 一致,
`tests/test_report_contract.py` 會檢查。
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from src import cli, holidays
from src.capital import capital_run
from src.disposition_study import (
    PRE_RELEASE_ENTRY,
    Book,
    Timing,
    as_number,
    build_panels,
    event_rate,
    exit_returns,
    pre_release_run,
    summarise,
    tradable_from,
    trading_days,
    win_loss,
)
from src.eventstats import clustered_ci
from src.liquidity import chain_levels
from src.market import ROUND_TRIP_COST_PCT, index_series
from src.portfolio import Sizing, adjusted_marks, index_curve, simulate, summary
from src.regime import MARKET_REGIMES, slice_by
from src.universe import all_actions, all_prices, all_punishes


RAW = Path("data/raw")
OUT = Path("data/out")

#: 出場時點的三種選擇,用來展示「差一天差很多」
EXIT_CHOICES = ((-6, -1, "出關前一日"), (-6, 0, "出關日"), (-6, 1, "出關後一日"))
#: 資金限制的對照組
CAPITAL_LEVELS: tuple[float | None, ...] = (None, 5_000_000, 1_000_000, 500_000)
#: 價格路徑上要畫的區間
PATH_RANGE = range(-6, 6)
MIN_SAMPLES = 3
SECOND = 2
#: #30 的候選門檻:整串第一次處置前 20 日成交金額中位數(百萬元)
CANDIDATE_W2 = 200
#: 網頁上組合回測用的本金。fixed / fraction 跟本金無關,只有 lot 受影響
CANDIDATE_CAPITAL = 1_000_000
#: 組合回測的三種部位大小(#33)和網頁上的說法
SIZING_LABELS: tuple[tuple[Sizing, str], ...] = (
    ("lot", "每筆 1 張"),
    ("fixed", "每筆本金 10%"),
    ("fraction", "每筆淨值 10%"),
)
#: 有編號的處置措施。人工管制撮合之類的不在研究樣本裡,不該掛上它的統計
NUMBERED_MEASURES = ("第一次處置", "第二次處置")
#: 未來交易日用平日推算,往後推這麼多天夠用
PROJECT_DAYS = 40


def _p(values: np.ndarray) -> float | None:
    """Wilcoxon 檢定的 p 值。樣本太少就回 None。"""
    if len(values) < MIN_SAMPLES:
        return None
    return round(float(stats.wilcoxon(values)[1]), 4)


def _projected_days(
    days: pd.DatetimeIndex, closed: set[date] | None = None
) -> list[pd.Timestamp]:
    """已知交易日 + 往後推算的交易日:跳過週末和證交所公告的休市日(#54)。

    closed 是空的(抓不到休市表)時,就只能跳過週末 —— 2026-10-09 國慶補假
    這種日子會被當成交易日,推算出來的買賣點差一天。
    """
    closed = closed or set()
    out = list(days)
    cursor = days.max().date()
    for _ in range(PROJECT_DAYS):
        cursor += timedelta(days=1)
        if cursor.weekday() < 5 and cursor not in closed:  # noqa: PLR2004
            out.append(pd.Timestamp(cursor))
    return out


def _shift(
    seq: list[pd.Timestamp], day: pd.Timestamp, steps: int
) -> pd.Timestamp | None:
    """在交易日序列上位移。找不到就回 None。"""
    nearest = min(range(len(seq)), key=lambda k: abs((seq[k] - day).days))
    target = nearest + steps
    return seq[target] if 0 <= target < len(seq) else None


def _status(today: pd.Timestamp, buy: pd.Timestamp, sell: pd.Timestamp) -> str:
    if today > sell:
        return "已過賣點"
    if today.date() == sell.date():
        return "今天賣出"
    if today >= buy:
        return "持有中"
    return "尚未到買點"


def _trade(
    code: str,
    buy: pd.Timestamp,
    sell: pd.Timestamp,
    days: pd.DatetimeIndex,
    close: pd.DataFrame,
) -> dict[str, Any]:
    """這一檔照「t−6 收盤買、t−1 收盤賣」實際做會怎樣,用跟回測一樣的順延規則(#45)。

    還沒到的日子就是 None。還沒賣出時,報酬用最新收盤算(未實現);
    已經賣出就是實現報酬。報酬都扣掉來回成本,但**不扣大盤** —— 卡片上
    要看的是這一檔自己賺賠多少,跟歷史統計的「超額」不是同一個數字。
    """
    empty: dict[str, Any] = {
        "close": None,
        "closeDay": None,
        "entryPrice": None,
        "entryDay": None,
        "entryDeferred": 0,
        "exitPrice": None,
        "exitDay": None,
        "exitDeferred": 0,
        "tradeReturn": None,
        "tradeState": "尚未到買點",
    }
    if code not in close.columns:
        return empty
    series = close[code].dropna()
    if series.empty:
        return empty
    last = days.max()
    out = dict(empty)
    out["close"] = float(series.iloc[-1])
    out["closeDay"] = str(series.index[-1].date())
    if buy > last:
        return out
    book = Book(days, close, close)
    entry = tradable_from(book, code, buy, sell, buying=True)
    if entry is None:
        # 還沒到賣出日就是還在等;過了賣出日都買不到,這一次就沒有進場
        out["tradeState"] = "漲停買不到,順延中" if sell > last else "漲停買不到,沒進場"
        return out
    entry_px = as_number(close.at[entry, code])
    if entry_px is None or entry_px <= 0:
        return out
    out["entryPrice"] = entry_px
    out["entryDay"] = str(entry.date())
    out["entryDeferred"] = int(days.searchsorted(entry) - days.searchsorted(buy))
    exit_day = (
        tradable_from(book, code, sell, None, buying=False) if sell <= last else None
    )
    price: float | None = None
    if entry == last:
        # 進場就在最新收盤:還沒持有任何一天,報酬只會是 −成本,看起來像在賠(#54)
        out["tradeState"] = "剛進場"
    elif exit_day is None:
        price = out["close"]
        out["tradeState"] = "跌停賣不掉,順延中" if sell <= last else "持有中"
    else:
        price = as_number(close.at[exit_day, code])
        out["exitPrice"] = price
        out["exitDay"] = str(exit_day.date())
        out["exitDeferred"] = int(days.searchsorted(exit_day) - days.searchsorted(sell))
        out["tradeState"] = "已賣出"
    if price is not None:
        out["tradeReturn"] = round(
            (price / entry_px - 1) * 100 - ROUND_TRIP_COST_PCT, 2
        )
    return out


def _current(
    punishes: pd.DataFrame,
    runs: pd.DataFrame,
    seq: list[pd.Timestamp],
    today: pd.Timestamp,
    market_of: dict[str, str],
    prices: pd.DataFrame,
) -> list[dict[str, Any]]:
    """仍在處置期間的個股,附歷史同類事件的統計。

    「同類」包含同一個市場:上櫃的流動性和滑價和上市不同,拿混合的統計掛在
    一張上櫃的卡片上會誤導。同市場的樣本太少時才退回混合,並在欄位標明。
    """
    rows: list[dict[str, Any]] = []
    days = trading_days(prices)
    known_last = days.max()
    close = build_panels(prices)["close"]
    for raw in punishes[punishes.end >= today].sort_values("end").to_dict("records"):
        release = _shift(seq, pd.Timestamp(raw["end"]), 1)
        if release is None:
            continue
        buy = _shift(seq, release, -6)
        sell = _shift(seq, release, -1)
        if buy is None or sell is None:
            continue
        # 不編號的措施(人工管制撮合)不在研究樣本裡,不該掛第一次處置的統計
        if raw["measure"] not in NUMBERED_MEASURES:
            continue
        nth = SECOND if raw["measure"] == "第二次處置" else 1
        # 「同類」要包含同一個市場 —— 上櫃的流動性和滑價和上市不同,
        # 那正是 universe.py 說一定要能分市場看的理由
        mine = market_of.get(str(raw["code"]), "?")
        same = runs[(runs.nth == nth) & (runs.code.map(market_of) == mine)]
        pooled = len(same) < MIN_SAMPLES
        hist = runs[runs.nth == nth] if pooled else same
        stat = summarise(hist, "excess")
        split = win_loss(hist, "excess")
        # summarise/win_loss 樣本不足時回空字典。分市場篩選之後這變得碰得到
        # —— 一個新市場的第一檔就會落在這裡,而缺欄位的卡片比沒有卡片更糟
        if not stat or not split:
            continue
        rows.append(
            {
                "code": int(raw["code"]),
                "market": mine,
                # 同市場樣本不足而退回混合時要講出來,不然讀的人會以為
                # 那是同市場的統計
                "histPooled": pooled,
                "name": str(raw["name"]),
                "measure": str(raw["measure"]),
                "condition": str(raw["condition"]),
                "start": str(pd.Timestamp(raw["start"]).date()),
                "end": str(pd.Timestamp(raw["end"]).date()),
                "daysLeft": int((pd.Timestamp(raw["end"]) - today).days) + 1,
                "release": str(release.date()),
                "buyDay": str(buy.date()),
                "sellDay": str(sell.date()),
                "status": _status(today, buy, sell),
                "projected": bool(release > known_last),
                "histN": stat["樣本數"],
                "histMedian": stat["中位數%"],
                "histWin": stat["勝率%"],
                "histEV": split["期望值%"],
                "histWinAvg": split["賺_平均%"],
                "histLossAvg": split["賠_平均%"],
                "histWorst": stat["最小%"],
                **_trade(str(raw["code"]), buy, sell, days, close),
            }
        )
    return rows


def _flag(
    card: dict[str, Any], w2_of: dict[tuple[str, pd.Timestamp], float]
) -> dict[str, Any]:
    """卡片加上候選標記:W2(百萬元,算不出來是 null)以及符不符合 #30 的條件。

    W2 = 整串第一次處置前 20 日的成交金額中位數(#31)。第二次處置而且
    W2 ≥ CANDIDATE_W2 的才是候選。
    """
    w2 = w2_of.get((str(card["code"]), pd.Timestamp(card["start"])))
    if w2 is None or math.isnan(w2):
        return {**card, "w2": None, "candidate": False}
    second = card["measure"] == "第二次處置"
    return {**card, "w2": round(w2), "candidate": second and w2 >= CANDIDATE_W2}


def _stat_row(label: str, sample: pd.DataFrame) -> dict[str, Any]:
    """一組樣本的筆數、中位數、勝率、按月群集拔靴 95% CI。"""
    values = sample.excess.astype(float)
    months = [f"{pd.Timestamp(d):%Y-%m}" for d in sample.buy_day]
    low, high, _ = clustered_ci(values.tolist(), months)
    return {
        "label": label,
        "n": len(values),
        "median": round(float(values.median()), 2),
        "win": round(float((values > 0).mean() * 100), 1),
        "low": round(low, 2),
        "high": round(high, 2),
    }


def _candidate(
    runs: pd.DataFrame,
    w2_of: dict[tuple[str, pd.Timestamp], float],
    prices: pd.DataFrame,
    index: dict[date, float],
    actions: pd.DataFrame | None,
) -> dict[str, Any]:
    """#30 的候選:第二次處置 × 整串第一次處置前 20 日成交金額中位數 ≥ 2 億。

    還沒驗證(門檻是看過資料才定的、滑價還沒實測)。網頁上一定要跟警語一起出現。
    報酬跟網頁其他地方同一套:漲跌停順延、還原除權息、扣加權指數。
    """
    w2 = pd.Series(
        [
            w2_of.get((str(c), pd.Timestamp(st)), float("nan"))
            for c, st in zip(runs.code, runs.start, strict=True)
        ],
        index=runs.index,
    )
    second = runs[runs.nth == SECOND]
    picked = second[w2.loc[second.index] >= CANDIDATE_W2]
    days = trading_days(prices)
    marks = adjusted_marks(prices, actions)
    trades = picked[["code", "buy_day", "sell_day", "buy", "sell", "gross"]].assign(
        code=picked.code.astype(str), prepay=True
    )
    portfolio = [
        {
            "label": label,
            **summary(
                simulate(
                    trades,
                    marks[sorted(set(trades.code))],
                    CANDIDATE_CAPITAL,
                    sizing=mode,
                ).equity
            ),
        }
        for mode, label in SIZING_LABELS
    ]
    portfolio.append({"label": "加權指數買進持有", **summary(index_curve(index, days))})
    months = (days.max() - days.min()).days / 30.44
    return {
        "minW2": CANDIDATE_W2,
        "capital": CANDIDATE_CAPITAL,
        "perMonth": round(len(picked) / months, 1) if months else 0.0,
        "rows": [
            _stat_row("全部處置", runs),
            _stat_row("第二次處置", second),
            _stat_row("第二次 × 流動性 ≥ 2 億", picked),
        ],
        "portfolio": portfolio,
    }


def _offenders(numbered: pd.DataFrame, limit: int = 12) -> list[dict[str, Any]]:
    """反覆被處置的個股,依次數排序。"""
    rows: list[dict[str, Any]] = []
    for (code, name), group in numbered.groupby(["code", "name"]):
        rows.append(
            {
                "code": int(str(code)),
                "name": str(name),
                "total": int(group.shape[0]),
                "second": int((group.nth == SECOND).sum()),
            }
        )
    rows.sort(key=lambda row: -int(row["total"]))
    return rows[:limit]


def market_return(index: dict[date, float], days: pd.DatetimeIndex) -> float:
    """研究期間內加權指數買進持有的報酬 %。

    只取研究期間(第一個到最後一個交易日)。指數快取比研究期間長(從 2016
    開始),拿快取的第一天當起點、卻用研究期間的天數年化,會把大盤灌成 +514%、
    年化 30.8% —— 實際同期是 +311.7%、23.3%(#33 的組合回測對出來的)。
    """
    series = pd.Series({pd.Timestamp(k): v for k, v in index.items()}).sort_index()
    series = series.loc[days.min() : days.max()]
    return float((series.iloc[-1] / series.iloc[0] - 1) * 100)


def build(today: pd.Timestamp) -> dict[str, Any]:
    """讀出所有資料,算出網頁要的每一塊。"""
    # 全市場(上市 + 上櫃)。原本只讀 prices.csv / punishes.csv,所以網頁顯示
    # 951 筆而程式跑出 2,265 筆 —— 兩邊對不上,而網頁是給人看的那一份([#23])
    prices = all_prices()
    punishes = all_punishes()
    # 注意股公告目前只有上市。櫃買中心的注意股端點還沒接,所以這個數字
    # 是上市的,不是全市場的 —— coverage 裡會標明
    notices = pd.read_csv(OUT / "notices.csv", parse_dates=["day"])
    # 代號 -> 市場。轉上市的股票兩邊都有公告,以上市為準(它現在在哪就算哪)
    market_of = {
        str(row["code"]): str(row["market"])
        for row in punishes.sort_values("market").to_dict("records")
    }
    index = index_series(RAW / "prices")
    days = trading_days(prices)
    numbered = punishes[punishes.nth > 0]

    actions = all_actions()
    # 每一筆處置的 W2(#30、#31):整串第一次處置前的流動性水位
    levels = chain_levels(punishes, prices, days)
    w2_of = {
        (str(c), pd.Timestamp(st)): float(v)
        for c, st, v in zip(punishes.code, punishes.start, levels.w2, strict=True)
    }
    raw_runs = pre_release_run(
        numbered, prices, index, all_punishes=punishes, actions=actions
    )
    runs = raw_runs[
        raw_runs.knowable & raw_runs.truly_released & raw_runs.excess.notna()
    ]

    span = (days.max() - days.min()).days + 1
    market = market_return(index, days)

    years = []
    for period in MARKET_REGIMES:
        values = slice_by(runs, period).excess.dropna().to_numpy()
        if len(values) < MIN_SAMPLES:
            continue
        years.append(
            {
                "name": period.name,
                "n": len(values),
                "median": round(float(np.median(values)), 2),
                "win": round(float((values > 0).mean() * 100), 1),
                "p": _p(values),
                "bear": "空頭" in period.name,
            }
        )

    exits = []
    for entry, exit_, label in EXIT_CHOICES:
        variant = pre_release_run(
            numbered,
            prices,
            index,
            Timing(entry=entry, exit=exit_),
            all_punishes=punishes,
            actions=actions,
        )
        variant = variant[variant.knowable & variant.truly_released]
        values = variant.excess.dropna().to_numpy()
        exits.append(
            {
                "label": label,
                "n": len(values),
                "median": round(float(np.median(values)), 2),
                "win": round(float((values > 0).mean() * 100), 1),
                "p": _p(values),
            }
        )

    second = runs[runs.nth == SECOND]
    caps: list[dict[str, Any]] = []
    for level in CAPITAL_LEVELS:
        result = capital_run(second, days, capital=level)
        caps.append(
            {
                "capital": level,
                "taken": result.taken,
                "total": len(second),
                "ret": result.return_pct,
                "ann": result.annualised_pct,
                "days": result.exposure_days,
                "bp": result.return_per_exposure_day_bp,
                "concurrent": result.max_concurrent,
            }
        )
    caps.append(
        {
            "capital": "market",
            "taken": None,
            "total": None,
            "ret": round(market, 1),
            "ann": round(((1 + market / 100) ** (365.25 / span) - 1) * 100, 1),
            "days": span,
            "bp": round(market / span * 100, 1),
            "concurrent": None,
        }
    )

    after = exit_returns(numbered, prices, index)
    last = days.max().date()
    closed = holidays.load(
        sorted({last.year, (last + timedelta(days=PROJECT_DAYS * 2)).year}),
        RAW / "holidays",
        today=today.date(),
    )
    seq = _projected_days(days, closed)

    return {
        "generated": str(today.date()),
        "path": _path(punishes, prices, index, actions),
        "coverage": {
            "from": str(days.min().date()),
            "to": str(days.max().date()),
            "notices": len(notices),
            "noticesMarket": "twse",
            "punishes": len(punishes),
            "tradingDays": len(days),
            "studied": len(runs),
            "codes": int(prices.code.nunique()),
            "markets": _by_market(prices, punishes, runs),
            "dropped": {
                "lookahead": int((~raw_runs.knowable).sum()),
                "fakeRelease": int(
                    (raw_runs.knowable & ~raw_runs.truly_released).sum()
                ),
                # 漲停一路順延到賣出日都買不到,或跌停順延到資料結束都賣不掉(#45)
                "unfilled": int(raw_runs.attrs.get("unfilled", 0)),
            },
        },
        "current": [
            _flag(card, w2_of)
            for card in _current(punishes, runs, seq, today, market_of, prices)
        ],
        "candidate": _candidate(runs, w2_of, prices, index, actions),
        "headline": summarise(runs, "excess"),
        "winloss": win_loss(runs, "excess"),
        "winlossSecond": win_loss(second, "excess"),
        "years": years,
        "exits": exits,
        "caps": caps,
        "afterRelease": summarise(after, "x5"),
        "rate": event_rate(runs),
        "binomial": _binomial(years),
        "monthly": [
            {"m": str(k), "n": int(v)}
            for k, v in numbered.groupby(numbered.announced.dt.to_period("M"))
            .size()
            .items()
        ],
        "offenders": _offenders(numbered),
        "dist": runs.excess.dropna().round(1).tolist(),
    }


def _binomial(years: list[dict[str, Any]]) -> float | None:
    """全部期間中位數都為正的話,那件事在虛無假設下的機率。

    **有任何一個期間不是正的就回 None** —— 原本是直接 0.5 ** len(years),
    從來沒檢查過符號。今天七個剛好都正,所以答案碰巧對;哪天有一個翻負,
    頁面還是會印「七個期間全部為正 … 0.5⁷」,而上面的表格就擺著那個負數。
    """
    if not years or any(float(y["median"]) <= 0 for y in years):
        return None
    return round(0.5 ** len(years), 4)


#: 價格路徑圖的橫軸:相對出關日的交易日偏移
PATH_OFFSETS = tuple(range(-6, 6))


def _path(
    punishes: pd.DataFrame,
    prices: pd.DataFrame,
    index: dict[date, float],
    actions: pd.DataFrame | None = None,
) -> list[dict[str, float]]:
    """以出關日對齊的超額累積報酬路徑。

    這張圖本來是寫死在 render.ts 裡的 12 個點,而且是上市那 951 筆算出來的
    —— 加入上櫃之後它畫的宇集和旁邊每一個數字都不一樣了,又沒有任何測試
    會發現。從資料算出來才不會再漂。

    每個偏移各跑一次 (entry=-6, exit=t),所以是「從 t-6 買進、持有到 t」的
    累積報酬,和圖的說明一致。

    這是價格路徑,不是交易,所以不套用漲跌停順延(#45)。順延的話,
    t−6 那一點的買賣是同一天,一定「買不到」,整個點就消失了。
    """
    out: list[dict[str, float]] = []
    for offset in PATH_OFFSETS:
        timing = Timing(entry=PRE_RELEASE_ENTRY, exit=offset, defer_limits=False)
        runs = pre_release_run(
            punishes[punishes.nth > 0],
            prices,
            index,
            timing=timing,
            all_punishes=punishes,
            actions=actions,
        )
        clean = runs[runs.knowable & runs.truly_released & runs.excess.notna()]
        if len(clean) < MIN_SAMPLES:
            continue
        out.append(
            {
                "t": offset,
                "excess": round(float(clean.excess.median()), 2),
                "n": len(clean),
            }
        )
    return out


def _by_market(
    prices: pd.DataFrame, punishes: pd.DataFrame, runs: pd.DataFrame
) -> dict[str, dict[str, int]]:
    """分市場的檔數、公告數、可回測事件數。

    上櫃的流動性比上市差,一個分不出市場的涵蓋率等於把兩個不同的東西
    當成一個([#23])。事件的市場要從公告那一列認,不是按代號查 ——
    轉上市的股票兩邊都有公告。
    """
    label = {
        (str(row["code"]), pd.Timestamp(row["start"]).date()): str(row["market"])
        for row in punishes.to_dict("records")
    }
    events: dict[str, int] = {}
    for row in runs.to_dict("records"):
        key = (str(row["code"]), pd.Timestamp(row["start"]).date())
        market = label.get(key, "?")
        events[market] = events.get(market, 0) + 1
    out: dict[str, dict[str, int]] = {}
    # "?" 也要列出來。原本只跑兩個市場的名字,所以配不到公告的事件會被
    # 算進 events 然後整個消失 —— 分市場的加總就悄悄對不上總數了
    names = {*prices.market.unique(), *punishes.market.unique(), *events}
    for market in sorted(str(n) for n in names):
        out[market] = {
            "codes": int(prices[prices.market == market].code.nunique()),
            "punishes": int((punishes.market == market).sum()),
            "studied": events.get(market, 0),
        }
    total = sum(v["studied"] for v in out.values())
    if total != len(runs):
        msg = f"分市場的事件數 {total} 和總數 {len(runs)} 對不上:{out}"
        raise ValueError(msg)
    return out


def main() -> None:
    """產生 report.json。"""
    cli.no_args(__doc__)
    report = build(pd.Timestamp.today().normalize())
    path = OUT / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"輸出 {path}:{report['coverage']['studied']} 筆納入研究的事件")


if __name__ == "__main__":
    main()
