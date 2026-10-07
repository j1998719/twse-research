"""bigholders.json 的欄位必須跟 web/src/holders.ts 的型別定義一致。

跟 test_report_contract.py 同一個理由:Python 寫、TypeScript 讀,
兩邊各自定義欄位遲早會漂移。這裡不用等真的資料 —— build() 用假的快照
就能產出完整形狀,所以這個測試在沒有 data/ 的新機器上也會跑。
"""

import re
from pathlib import Path

from src.build_bigholders import LEVELS, THRESHOLDS, build


ROOT = Path(__file__).resolve().parent.parent
TYPES = ROOT / "web" / "src" / "holders.ts"

SNAPSHOT = (
    "資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\r\n"
    "20261002,2330  ,15,1500,1,80.0\r\n"
    "20261002,2330  ,17,2000000,1,100.0\r\n"
)
QUOTE = {
    "name": "台積電",
    "market": "twse",
    "day": "2026-10-05",
    "close": 1000.0,
    "change": 1.0,
    "lots": 30000,
}


def _block(name: str) -> str:
    text = TYPES.read_text(encoding="utf-8")
    match = re.search(rf"{name}[^{{]*\{{(.*?)\n\}}", text, re.DOTALL)
    assert match, f"在 holders.ts 裡找不到 {name}"
    return match.group(1)


def declared_keys() -> set[str]:
    text = TYPES.read_text(encoding="utf-8")
    block = re.search(
        r"REQUIRED_KEYS:\s*readonly\s*\(keyof Holders\)\[\]\s*=\s*\[(.*?)\]",
        text,
        re.DOTALL,
    )
    assert block, "在 holders.ts 裡找不到 REQUIRED_KEYS"
    return set(re.findall(r'"([^"]+)"', block.group(1)))


def row_keys() -> set[str]:
    """HolderRow 介面的欄位名。註解行跳過。"""
    return set(re.findall(r"^\t(\w+):", _block("interface HolderRow"), re.MULTILINE))


def test_最上層欄位一致() -> None:
    assert set(build(SNAPSHOT, None, {"2330": QUOTE})) == declared_keys()


def test_每一列的欄位一致() -> None:
    row = build(SNAPSHOT, None, {"2330": QUOTE})["rows"][0]
    assert set(row) == row_keys()


def test_門檻跟級距一樣多() -> None:
    # 網頁用索引把門檻對到級距,數量不一樣就會對錯
    assert len(THRESHOLDS) == len(LEVELS)


def test_網頁的級距下限跟_python_一樣() -> None:
    # screen.ts 用 LOT_EDGES 把金額、比例換算後的張數對到級距(#55)
    text = (ROOT / "web" / "src" / "screen.ts").read_text(encoding="utf-8")
    match = re.search(r"LOT_EDGES[^=]*=\s*\[(.*?)\]", text, re.DOTALL)
    assert match, "在 screen.ts 裡找不到 LOT_EDGES"
    assert tuple(int(x) for x in re.findall(r"\d+", match.group(1))) == THRESHOLDS
