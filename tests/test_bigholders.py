from datetime import date
from pathlib import Path

import pandas as pd

from src.build_bigholders import LEVELS, build, last_two_closes, latest_snapshots


HEADER = "資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\r\n"


def _snapshot(day: str, rows: dict[str, dict[int, tuple[int, float]]]) -> str:
    """rows: 代號 -> 分級 -> (人數, 佔比)。股數用不到,隨便填。"""
    lines = [HEADER]
    for code, levels in rows.items():
        for level, (people, pct) in levels.items():
            # 代號照真實 feed 用空白補齊,確認有 strip
            lines.append(f"{day},{code:<6},{level},{people},1000,{pct}\r\n")
    return "".join(lines)


NOW = _snapshot(
    "20261002",
    {
        "3105": {
            12: (10, 2.0),
            13: (5, 1.5),
            14: (3, 1.0),
            15: (48, 49.69),
            17: (125_535, 100.0),
        },
        "0050": {15: (100, 80.0), 17: (500_000, 100.0)},
        "9999": {15: (1, 10.0), 17: (10, 100.0)},
    },
)
PREV = _snapshot(
    "20260925", {"3105": {12: (9, 1.5), 15: (47, 49.0), 17: (125_000, 100.0)}}
)

QUOTE = {
    "name": "穩懋",
    "market": "otc",
    "day": "2026-10-05",
    "close": 120.0,
    "change": 1.5,
    "lots": 3000,
}


def test_只留有行情的普通股() -> None:
    out = build(NOW, None, {"3105": QUOTE, "0050": QUOTE})
    # 0050 是 ETF、9999 沒有行情
    assert [r["code"] for r in out["rows"]] == ["3105"]


def test_15個級距照順序輸出() -> None:
    row = build(NOW, None, {"3105": QUOTE})["rows"][0]
    assert len(row["pct"]) == len(LEVELS)
    assert row["pct"][11:] == [2.0, 1.5, 1.0, 49.69]
    assert row["people"][11:] == [10, 5, 3, 48]
    assert row["holders"] == 125_535
    # 集保總股數(分級 17 的股數):佔市值比例的門檻要用(#55)
    assert row["shares"] == 1000
    assert row["name"] == "穩懋"


def test_沒有前一份快照時週變化是_null_不是_0() -> None:
    out = build(NOW, None, {"3105": QUOTE})
    assert out["prevDay"] is None
    assert out["rows"][0]["prevPct"] is None


def test_前一週缺的級距補_0() -> None:
    out = build(NOW, PREV, {"3105": QUOTE})
    assert out["day"] == "2026-10-02"
    assert out["prevDay"] == "2026-09-25"
    assert out["rows"][0]["prevPct"][11:] == [1.5, 0.0, 0.0, 49.0]


def test_前一週沒有這一檔時是_null() -> None:
    out = build(NOW, PREV, {"3105": QUOTE, "9999": QUOTE})
    by = {r["code"]: r for r in out["rows"]}
    assert by["9999"]["prevPct"] is None


def _prices(rows: list[tuple[str, str, float | None, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["day", "code", "close", "volume"])
    frame["day"] = pd.to_datetime(frame["day"])
    frame["name"] = "名稱"
    frame["market"] = "twse"
    return frame


def test_漲跌幅用每一檔自己的最後兩天() -> None:
    prices = _prices(
        [
            ("2026-10-01", "2330", 100.0, 5_000_000),
            ("2026-10-02", "2330", 110.0, 8_000_000),
            # 停牌:最後一筆比全市場早,不能因此消失
            ("2026-09-29", "1101", 40.0, 1_000),
            ("2026-09-30", "1101", 38.0, 2_000),
        ]
    )
    out = last_two_closes(prices)
    assert out["2330"]["change"] == 10.0
    assert out["2330"]["lots"] == 8000
    assert out["2330"]["day"] == "2026-10-02"
    assert out["1101"]["change"] == -5.0


def test_沒成交的那天不算() -> None:
    prices = _prices(
        [
            ("2026-10-01", "2330", 100.0, 5_000_000),
            ("2026-10-02", "2330", None, 0),
        ]
    )
    out = last_two_closes(prices)
    assert out["2330"]["close"] == 100.0
    assert out["2330"]["change"] is None


def test_沒有行情回空的() -> None:
    assert last_two_closes(pd.DataFrame()) == {}


def test_快照新的在前只取兩份(tmp_path: Path) -> None:
    for stamp in ("20260918", "20261002", "20260925"):
        (tmp_path / f"dispersion_{stamp}.csv").write_text("", encoding="utf-8")
    names = [p.name for p in latest_snapshots(tmp_path)]
    assert names == ["dispersion_20261002.csv", "dispersion_20260925.csv"]
    assert date(2026, 10, 2).strftime("%Y%m%d") in names[0]


def test_沒有還原資料時均線整塊是空的() -> None:
    out = build(NOW, None, {"3105": QUOTE})
    assert out["maReady"] is False
    row = out["rows"][0]
    assert (row["ma5y"], row["ma10y"], row["gap5y"], row["gap10y"]) == (None,) * 4


def test_均線與距離() -> None:
    from src.adjust import LongTerm

    lt = LongTerm(day="2026-10-05", close=90.0, ma5y=100.0, ma10y=80.0)
    out = build(NOW, None, {"3105": QUOTE}, {"3105": lt})
    row = out["rows"][0]
    assert out["maReady"] is True
    assert (row["ma5y"], row["gap5y"]) == (100.0, -10.0)
    assert (row["ma10y"], row["gap10y"]) == (80.0, 12.5)


def test_沒有還原因子檔就不算(tmp_path: Path) -> None:
    from src.build_bigholders import load_long_term

    history = tmp_path / "long.csv"
    history.write_text("code,day,close,market\n2330,2026-10-01,100,twse\n")
    assert load_long_term(tmp_path / "missing.csv", history) is None
    assert load_long_term(history, tmp_path / "missing.csv") is None


def test_有還原因子檔就算(tmp_path: Path) -> None:
    from src.build_bigholders import load_long_term

    actions = tmp_path / "actions.csv"
    actions.write_text("code,day,factor,kind\n2330,2026-10-02,0.5,twse_par\n")
    history = tmp_path / "long.csv"
    history.write_text(
        "code,day,close,market\n2330,2026-10-01,100,twse\n2330,2026-10-02,50,twse\n"
    )
    lt = load_long_term(actions, history)
    assert lt is not None
    assert lt["2330"].close == 50.0


def test_換發中只有一個持有人的股票不列() -> None:
    # 2601 益航減資換發期間:全部股票在同一個持有人名下
    reissue = _snapshot("20261002", {"2601": {15: (1, 100.0), 17: (1, 100.0)}})
    assert build(reissue, None, {"2601": QUOTE})["rows"] == []


def test_很久沒成交的不列_成交量只算最新一天() -> None:
    days = [f"2026-09-{d:02d}" for d in (21, 22, 23, 24, 25, 29, 30)]
    rows = [(d, "2330", 100.0, 5_000_000) for d in days]
    # 停了兩天:還在 5 個交易日內,要列;但最新一天沒成交,張數是 0
    rows += [(d, "1101", 40.0, 1_000_000) for d in days[:-2]]
    # 只有最早那天有成交:超過 5 個交易日,不列
    rows += [(days[0], "6497", 5.66, 1_872_000)]
    out = last_two_closes(_prices(rows))
    assert set(out) == {"2330", "1101"}
    assert out["2330"]["lots"] == 5000
    assert out["1101"]["lots"] == 0
    assert out["1101"]["day"] == "2026-09-25"


def test_沒有前一份快照_用往回補的週資料當上週() -> None:
    # 全市場快照只有最新一週;往回補的單檔週資料(#49)有上一週,
    # 不用等下週五的第二份快照,「比上週」現在就算得出來(#34)
    from datetime import date

    from src.weekly import LEVELS

    last = date(2026, 9, 24)
    prev = [0.0] * len(LEVELS)
    prev[11:] = [1.0, 1.0, 1.0, 45.0]
    weeks = {date(2026, 10, 2): {}, last: {"3105": (prev, [0] * len(LEVELS))}}
    out = build(
        NOW, None, {"3105": QUOTE}, weekly=([date(2026, 10, 2), last], weeks, {})
    )
    assert out["prevDay"] == "2026-09-24"
    assert out["rows"][0]["prevPct"] == prev


def test_有前一份快照就用快照() -> None:
    out = build(NOW, PREV, {"3105": QUOTE})
    assert out["prevDay"] == "2026-09-25"
