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

## 網頁

版面與渲染在 `web/`,用 TypeScript 寫,受 Biome 與 `tsc` 把關。

```bash
make report   # 重算 report.json 並建置成單一 HTML
```

產出是 `data/out/index.html`,單一自足檔案(CSS 與 JS 都內嵌)——
artifact 的 CSP 禁止外部腳本,只有 Google Fonts 例外。

`report.json` 的欄位由 Python 寫、TypeScript 讀。兩邊各自定義遲早會漂移,
所以 `web/src/report.ts` 的 `REQUIRED_KEYS` 是單一來源,
`tests/test_report_contract.py` 會比對實際輸出;
`parseReport()` 在執行期再檢查一次,缺欄位直接報錯而不是顯示 undefined。

## 每日自動更新

```bash
./update.sh   # 抓資料 → 算統計 → 建置網頁,約兩分鐘(有快取)
```

已設定 cron,週一到五 18:00 自動執行:

```
0 18 * * 1-5 ~/twse-research/update.sh >> ~/twse-research/data/cron.log 2>&1
```

排在 18:00 是因為台股 13:30 收盤,證交所的盤後資料(注意股、處置、法人買賣超)
約 15:00 前後才齊全,留兩三小時的餘裕。

腳本用 `set -euo pipefail`,任何一步失敗就中止 —— 不要拿抓了一半的資料
蓋掉前一天正常的輸出。

**注意**:`~/Library/LaunchAgents` 在這台機器上是 root 所有(MDM 管理),
所以用 cron 而不是 launchd。換機器時要重設。

### 自動化到哪裡為止

這是**刻意的半自動**:

- cron 每天自動更新資料並產生 `data/out/index.html`
- 發布到網址是手動的 —— 要看的時候再請 Claude 發布一次

評估過 Cloudflare Pages 之類的靜態託管可以做到全自動,但要多一組憑證和權限設定。
以「偶爾看一次」的使用頻率來說,那個成本不划算。哪天需要天天看再說。
