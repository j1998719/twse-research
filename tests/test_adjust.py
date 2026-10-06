import pandas as pd
import pytest

from src.adjust import adjusted_closes, long_term


def _prices(
    code: str, closes: list[float | None], start: str = "2026-01-05"
) -> pd.DataFrame:
    days = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"code": code, "day": days, "close": closes})


def _events(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["code", "day", "factor"])
    frame["day"] = pd.to_datetime(frame["day"])
    return frame


def test_沒有事件時還原價等於收盤() -> None:
    out = adjusted_closes(_prices("2330", [10.0, 11.0]), _events([]))
    assert out["adj_close"].tolist() == [10.0, 11.0]


def test_除息日之前的價格乘上因子_當天和之後不動() -> None:
    # 2026-01-07 除息:前一日收 100、參考價 95 → 因子 0.95
    prices = _prices("2330", [100.0, 100.0, 95.0, 96.0])
    out = adjusted_closes(prices, _events([("2330", "2026-01-07", 0.95)]))
    assert out["adj_close"].tolist() == pytest.approx([95.0, 95.0, 95.0, 96.0])


def test_多次事件的因子相乘() -> None:
    prices = _prices("2330", [100.0, 50.0, 25.0])
    events = _events([("2330", "2026-01-06", 0.5), ("2330", "2026-01-07", 0.5)])
    out = adjusted_closes(prices, events)
    # 第一天在兩次事件之前:× 0.25;第二天只在第二次之前:× 0.5
    assert out["adj_close"].tolist() == pytest.approx([25.0, 25.0, 25.0])


def test_事件只影響自己那一檔() -> None:
    prices = pd.concat([_prices("2330", [100.0, 90.0]), _prices("1101", [40.0, 40.0])])
    out = adjusted_closes(prices, _events([("2330", "2026-01-06", 0.9)]))
    by = out.groupby("code")["adj_close"].apply(list).to_dict()
    assert by["2330"] == pytest.approx([90.0, 90.0])
    assert by["1101"] == [40.0, 40.0]


def test_均線用最後_N_個有成交的交易日() -> None:
    frame = _prices("2330", [1.0, 2.0, 3.0, None, 4.0, 5.0])
    adjusted = adjusted_closes(frame, _events([]))
    lt = long_term(adjusted, windows=(2, 4))["2330"]
    assert lt.close == 5.0
    assert lt.ma5y == 4.5  # 4, 5
    assert lt.ma10y == 3.5  # 2, 3, 4, 5(沒成交的那天跳過)


def test_歷史不夠長就沒有那條線() -> None:
    adjusted = adjusted_closes(_prices("2330", [1.0, 2.0, 3.0]), _events([]))
    lt = long_term(adjusted, windows=(2, 10))["2330"]
    assert lt.ma5y == 2.5  # 均線不先四捨五入,距離才不會差
    assert lt.ma10y is None
    assert lt.gap(lt.ma10y) is None


def test_跌破是負的距離() -> None:
    adjusted = adjusted_closes(_prices("2330", [10.0, 10.0, 8.0]), _events([]))
    lt = long_term(adjusted, windows=(2, 3))["2330"]
    assert lt.gap(lt.ma10y) == pytest.approx((8 / (28 / 3) - 1) * 100, abs=0.01)
    assert lt.gap(lt.ma5y) < 0


def test_還原之後才算均線() -> None:
    # 原始價看起來跌破(100 → 50),但其實是 1:2 分割;還原後沒有跌破
    prices = _prices("2330", [100.0, 100.0, 50.0, 51.0])
    adjusted = adjusted_closes(prices, _events([("2330", "2026-01-07", 0.5)]))
    lt = long_term(adjusted, windows=(2, 4))["2330"]
    assert lt.gap(lt.ma10y) > 0


def test_沒有資料回空的() -> None:
    assert long_term(pd.DataFrame()) == {}
