# twse-research

台股注意股／處置股的資料抓取與回測。資料全部來自證交所公開 API,不需要任何帳號。

## 開始

```bash
uv venv                   # 讀 .python-version,版本不對會自己下載
uv pip install -r requirements.txt
lefthook install          # 裝 pre-push 檢查,clone 下來要自己跑一次
```

Python 版本定在 `.python-version`(3.13),Node 定在 `.nvmrc`。`pyproject.toml` 的
`requires-python` 和 Ruff 的 `target-version` 都跟著它 —— Ruff 只決定用哪一版的語法規則
來檢查,不會管實際跑的是哪一版,所以 `make pyver`(pre-push 也會跑)另外檢查 `.venv` 的版本。

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

### 大戶持股排行

```bash
make holders  # 用最新兩份集保快照與收盤行情產生 data/out/holders.html
```

列出上市與上櫃普通股的大戶持股比例,門檻可在 400 / 600 / 800 / 1000 張之間切換,
也可以依週變化、大戶人數、當日漲跌排序。給不寫程式的人用,所以字放大、手機可讀。

網址是 <https://j1998719.github.io/twse-research/>。`update.sh` 最後一步會跑
`publish_pages.sh`,把建好的頁面推到 `gh-pages` 分支(只有 `index.html`,沒有原始碼),
GitHub Pages 一兩分鐘內就會更新。

「比上週」需要兩份快照。集保只提供最新一週,所以第一週只有絕對比例,
要等 cron 存到第二份之後才有週變化。

## 每日自動更新

```bash
./update.sh   # 抓資料 → 算統計 → 建置網頁,約兩分鐘(有快取)
```

已設定 cron,每天台灣時間 08:00 執行(本機時區是 Asia/Taipei,cron 用本機時間):

```
0 8 * * * $HOME/twse-research/update.sh >> $HOME/twse-research/data/cron.log 2>&1
```

排在早上是因為前一天的盤後資料(注意股、處置、法人買賣超)前一晚就齊了,而集保股權分散
是週五盤後公布,週末也照跑,才不會漏掉那一週的快照。GitHub 推送用的 SSH 金鑰沒有密碼,
cron 在背景也推得上去。

腳本用 `set -euo pipefail`,任何一步失敗就中止 —— 不要拿抓了一半的資料
蓋掉前一天正常的輸出。

**注意**:`~/Library/LaunchAgents` 在這台機器上是 root 所有(MDM 管理),
所以用 cron 而不是 launchd。換機器時要重設。

### 自動化到哪裡為止

- **大戶持股排行**(`holders.html`):全自動。cron 跑完 `update.sh` 會用 `publish_pages.sh`
  推到 GitHub Pages(<https://j1998719.github.io/twse-research/>),要給爸爸天天看,所以
  2026-10 改成全自動。用 repo 自己的 Pages,不用另外申請憑證。
- **處置股觀測**(`index.html`):仍然是半自動 —— cron 每天產生,要看的時候再請 Claude
  發布一次。
