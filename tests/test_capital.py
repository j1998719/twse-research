import pandas as pd

from src.capital import capital_run, position_cost


DAYS = pd.DatetimeIndex(pd.bdate_range("2026-01-01", "2026-01-30"))


def events(rows):
    return pd.DataFrame(
        [{"buy_day": b, "sell_day": s, "buy": p, "net": n} for b, s, p, n in rows]
    )


def test_一張的成本():
    assert position_cost(100.0) == 100_000
    assert position_cost(100.0, lot=100) == 10_000


class TestCapitalRun:
    # 兩筆重疊(1/5–1/9 與 1/6–1/12),一筆不重疊
    overlapping = events(
        [
            ("2026-01-05", "2026-01-09", 100.0, 10.0),
            ("2026-01-06", "2026-01-12", 200.0, -5.0),
            ("2026-01-20", "2026-01-23", 50.0, 20.0),
        ]
    )

    def test_資金無限時全部吃下(self):
        r = capital_run(self.overlapping, DAYS)
        assert r.taken == 3
        assert r.skipped == 0

    def test_錢不夠就跳過重疊的那筆(self):
        # 第一筆佔 10 萬,第二筆要 20 萬 -> 15 萬的本金吃不下第二筆
        r = capital_run(self.overlapping, DAYS, capital=150_000)
        assert r.taken == 2
        assert r.skipped == 1

    def test_先來後到而不是挑好的(self):
        # 被跳過的第二筆是虧損的,但那是巧合 —— 程式不能偷看結果
        # 把第二筆改成大賺,一樣要被跳過
        rows = self.overlapping.copy()
        rows.loc[1, "net"] = 99.0
        r = capital_run(rows, DAYS, capital=150_000)
        assert r.taken == 2

    def test_損益用實際金額算(self):
        r = capital_run(self.overlapping, DAYS, capital=150_000)
        # 10 萬 × +10% + 5 萬 × +20% = 2 萬
        assert r.pnl == 20_000

    def test_賣掉之後錢就放出來了(self):
        # 6 萬只買得起第三筆(5 萬);重點是它在 1/20,
        # 不該因為 1 月初那兩筆而被擋 —— 那時候的部位早就出場了
        r = capital_run(self.overlapping, DAYS, capital=60_000)
        assert r.taken == 1
        assert r.pnl == 10_000  # 5 萬 × +20%
        assert r.max_concurrent == 1

    def test_資金放出來之後可以再買(self):
        # 兩筆都是 10 萬且時間不重疊,10 萬本金應該兩筆都吃得到
        rows = events(
            [
                ("2026-01-05", "2026-01-09", 100.0, 10.0),
                ("2026-01-12", "2026-01-16", 100.0, 10.0),
            ]
        )
        r = capital_run(rows, DAYS, capital=100_000)
        assert r.taken == 2
        assert r.max_concurrent == 1

    def test_同時最多幾檔與高峰金額(self):
        r = capital_run(self.overlapping, DAYS)
        assert r.max_concurrent == 2
        assert r.peak_capital == 300_000  # 10 萬 + 20 萬

    def test_資金使用率(self):
        r = capital_run(self.overlapping, DAYS)
        assert 0 < r.utilisation_pct < 100

    def test_空的事件不會當掉(self):
        r = capital_run(
            pd.DataFrame(columns=["buy_day", "sell_day", "buy", "net"]), DAYS
        )
        assert r.taken == 0
        assert r.pnl == 0.0


class TestExposure:
    def test_曝險天數少於總天數(self):
        rows = events([("2026-01-05", "2026-01-09", 100.0, 10.0)])
        r = capital_run(rows, DAYS, capital=100_000)
        # 只有 1/5–1/9 在場,總共 22 個營業日
        assert 0 < r.exposure_days < len(DAYS)

    def test_每曝險日報酬(self):
        # 10% 報酬、5 天曝險 -> 每天 2%,也就是 200 基點
        rows = events([("2026-01-05", "2026-01-09", 100.0, 10.0)])
        r = capital_run(rows, DAYS, capital=100_000)
        assert r.exposure_days == 5.0
        assert r.return_per_exposure_day_bp == 200.0

    def test_空手久的策略每日報酬不會被稀釋(self):
        # 同樣一筆交易,研究期間拉長一倍,總年化會掉但每曝險日報酬不變
        long_days = pd.DatetimeIndex(pd.bdate_range("2026-01-01", "2026-03-01"))
        rows = events([("2026-01-05", "2026-01-09", 100.0, 10.0)])
        short = capital_run(rows, DAYS, capital=100_000)
        long_ = capital_run(rows, long_days, capital=100_000)
        assert long_.annualised_pct < short.annualised_pct
        assert long_.return_per_exposure_day_bp == short.return_per_exposure_day_bp

    def test_虧光不會算出無效數字(self):
        rows = events([("2026-01-05", "2026-01-09", 100.0, -100.0)])
        r = capital_run(rows, DAYS, capital=100_000)
        assert r.return_per_exposure_day_bp == -2000.0
