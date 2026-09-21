# twse-research

台股注意股／處置股的資料抓取與回測。資料全部來自證交所公開 API,不需要任何帳號。

## 開始

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
lefthook install          # 裝 pre-push 檢查,clone 下來要自己跑一次
```

## 常用指令

```bash
make check   # ruff + mypy + pytest,跟 pre-push 跑的是同一組
make fix     # 自動修正與排版

.venv/bin/python -m src.fetch_all    2025-01-01 2026-09-21   # 注意股與處置股公告
.venv/bin/python -m src.fetch_prices 2025-01-01 2026-09-21   # 每日全市場收盤行情
```

`data/` 不進版控 —— 裡面的東西都能用上面兩個指令重新產生。`data/raw/` 是原始回應的快取,
有快取時不會重複打 API,所以重跑很快。

## 幾個容易踩的坑

- **API 的「累計次數」欄不能當「第幾次」用。** 那個值是相對於你查詢的區間算的,
  同一筆資料用不同區間查會得到不同的數字。處置的實際次數在「處置措施」欄。
- **四位數代號不等於普通股。** `0050` 是 ETF,`00400A` 是主動式 ETF。
- **民國日期要擋西元格式。** `2026-08-04` 若被當成民國年會算出西元 3937 年,而且不會報錯。

以上三點都有對應的測試。
