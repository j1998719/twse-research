"""上市與上櫃的合併。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pytest

from src.universe import all_prices, all_punishes, summary


if TYPE_CHECKING:
    from pathlib import Path

PRICE_HEAD = "day,code,name,open,high,low,close,volume\n"


@pytest.fixture
def listed(tmp_path: Path) -> Path:
    path = tmp_path / "prices.csv"
    path.write_text(
        PRICE_HEAD
        + "2026-09-23,2330,台積電,1000,1010,990,1005,100\n"
        + "2026-09-23,1101,台泥,40,41,39,40.5,200\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def otc(tmp_path: Path) -> Path:
    path = tmp_path / "tpex_prices.csv"
    path.write_text(
        PRICE_HEAD + "2026-09-23,3105,穩懋,507,518,486.5,497,26998\n",
        encoding="utf-8",
    )
    return path


class TestAllPrices:
    def test_兩個市場接起來並標上_market(self, listed: Path, otc: Path) -> None:
        got = all_prices(listed, otc)
        assert len(got) == 3
        assert set(got.market) == {"twse", "otc"}
        assert got[got.code == "3105"].market.iloc[0] == "otc"

    def test_代號保持字串(self, listed: Path, otc: Path) -> None:
        # 變成數字的話開頭是 0 的代號會掉一位
        got = all_prices(listed, otc)
        assert all(isinstance(c, str) for c in got.code)

    def test_同一天同一個代號出現在兩邊要出錯(
        self, listed: Path, tmp_path: Path
    ) -> None:
        # 不擋的話後面 pivot 成價格表時會安靜地取到其中一邊,而且看不出來
        clash = tmp_path / "clash.csv"
        clash.write_text(
            PRICE_HEAD + "2026-09-23,2330,台積電,1,1,1,1,1\n", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="兩個市場"):
            all_prices(listed, clash)

    def test_同一個代號不同天不算衝突(self, listed: Path, tmp_path: Path) -> None:
        # 轉上市的股票代號不變,所以同一個代號在不同期間出現在兩邊是正常的
        later = tmp_path / "later.csv"
        later.write_text(
            PRICE_HEAD + "2026-09-24,2330,台積電,1,1,1,1,1\n", encoding="utf-8"
        )
        assert len(all_prices(listed, later)) == 3

    def test_只有一邊存在也能用(self, listed: Path, tmp_path: Path) -> None:
        got = all_prices(listed, tmp_path / "不存在.csv")
        assert len(got) == 2

    def test_兩邊都不存在回空表(self, tmp_path: Path) -> None:
        got = all_prices(tmp_path / "a.csv", tmp_path / "b.csv")
        assert got.empty


PUNISH_HEAD = "announced,code,name,nth,measure,condition,start,end,detail\n"


@pytest.fixture
def listed_punishes(tmp_path: Path) -> Path:
    path = tmp_path / "punishes.csv"
    path.write_text(
        PUNISH_HEAD
        + "2026-09-20,2330,台積電,1,第一次處置,連續三次,2026-09-22,2026-09-26,x\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def otc_punishes(tmp_path: Path) -> Path:
    path = tmp_path / "tpex_punishes.csv"
    path.write_text(
        "公布日期,收盤價,本益比,累計,編號,處置內容,處置原因,處置起訖時間,證券代號,證券名稱\n"
        "115/09/22,100,15,6,1,因連續3個營業日,連續3個營業日,115/09/23~115/10/05,6218,豪勉\n",
        encoding="utf-8",
    )
    return path


class TestAllPunishes:
    def test_兩個市場併成同一個形狀(
        self, listed_punishes: Path, otc_punishes: Path
    ) -> None:
        got = all_punishes(listed_punishes, otc_punishes)
        assert len(got) == 2
        assert set(got.market) == {"twse", "otc"}
        for column in ("announced", "code", "nth", "start", "end"):
            assert column in got.columns

    def test_日期都轉成_datetime(
        self, listed_punishes: Path, otc_punishes: Path
    ) -> None:
        got = all_punishes(listed_punishes, otc_punishes)
        for column in ("announced", "start", "end"):
            assert pd.api.types.is_datetime64_any_dtype(got[column])

    def test_上櫃的民國日期轉對了(self, tmp_path: Path, otc_punishes: Path) -> None:
        got = all_punishes(tmp_path / "無.csv", otc_punishes)
        assert got.start.iloc[0] == pd.Timestamp("2026-09-23")

    def test_上櫃解不出來的列會被丟掉(self, tmp_path: Path) -> None:
        # 猜一個日期比少一筆事件糟得多
        bad = tmp_path / "bad.csv"
        bad.write_text(
            "公布日期,處置起訖時間,證券代號,證券名稱,處置內容,處置原因\n"
            "爛資料,爛資料,6218,豪勉,x,y\n",
            encoding="utf-8",
        )
        assert all_punishes(tmp_path / "無.csv", bad).empty

    def test_兩邊都不存在回空表(self, tmp_path: Path) -> None:
        assert all_punishes(tmp_path / "a.csv", tmp_path / "b.csv").empty


class TestSummary:
    def test_分市場報檔數與事件數(
        self, listed: Path, otc: Path, listed_punishes: Path, otc_punishes: Path
    ) -> None:
        facts = summary(
            all_prices(listed, otc), all_punishes(listed_punishes, otc_punishes)
        )
        assert facts["codes"] == 3
        assert facts["codes_by_market"] == {"otc": 1, "twse": 2}
        assert facts["events_by_market"] == {"otc": 1, "twse": 1}

    def test_期間是最早到最晚(self, listed: Path, otc: Path) -> None:
        facts = summary(all_prices(listed, otc), all_punishes())
        assert facts["span"] is not None

    def test_空表也能用而不是丟_KeyError(self, tmp_path: Path) -> None:
        # 抓取失敗或第一次執行時應該印出「什麼都沒有」,不是讓人以為程式壞了
        empty = all_prices(tmp_path / "a.csv", tmp_path / "b.csv")
        facts = summary(empty, all_punishes(tmp_path / "c.csv", tmp_path / "d.csv"))
        assert facts["span"] is None
        assert facts["codes"] == 0
        assert facts["codes_by_market"] == {}
        assert facts["events_by_market"] == {}
