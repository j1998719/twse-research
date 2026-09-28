"""report.json 的欄位必須跟 web/src/report.ts 的型別定義一致。

Python 寫、TypeScript 讀,兩邊各自定義欄位遲早會漂移 ——
改了 Python 的欄位名,網頁就會安靜地顯示 undefined。
這個測試把 TypeScript 那份清單讀進來比對,漂了就 fail。
"""

import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
TYPES = ROOT / "web" / "src" / "report.ts"
REPORT = ROOT / "data" / "out" / "report.json"


def declared_keys() -> set[str]:
    """從 report.ts 的 REQUIRED_KEYS 讀出最上層欄位。"""
    text = TYPES.read_text(encoding="utf-8")
    block = re.search(
        r"REQUIRED_KEYS:\s*readonly\s*\(keyof Report\)\[\]\s*=\s*\[(.*?)\]",
        text,
        re.DOTALL,
    )
    assert block, "在 report.ts 裡找不到 REQUIRED_KEYS"
    return set(re.findall(r'"([^"]+)"', block.group(1)))


def test_型別定義本身讀得出來():
    keys = declared_keys()
    assert "headline" in keys
    assert len(keys) > 10


@pytest.mark.skipif(not REPORT.exists(), reason="還沒產生 report.json")
def test_產出的欄位跟型別定義一致():
    actual = set(json.loads(REPORT.read_text(encoding="utf-8")))
    declared = declared_keys()
    missing = declared - actual
    extra = actual - declared
    assert not missing, f"report.json 少了 TypeScript 要的欄位:{sorted(missing)}"
    assert not extra, f"report.json 多了 TypeScript 沒宣告的欄位:{sorted(extra)}"


@pytest.mark.skipif(not REPORT.exists(), reason="還沒產生 report.json")
def test_巢狀結構的關鍵欄位():
    """幾個畫面一定會讀到的內層欄位,缺了就是空白。"""
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    assert {"from", "to", "backtested", "dropped"} <= set(data["coverage"])
    assert {"lookahead", "fakeRelease"} <= set(data["coverage"]["dropped"])
    assert "中位數%" in data["headline"]
    # 分市場的涵蓋率。原本只檢查最上層的 key,所以這層改名不會有人發現
    assert {"codes", "markets", "noticesMarket"} <= set(data["coverage"])
    for market, facts in data["coverage"]["markets"].items():
        assert {"codes", "punishes", "backtested"} <= set(facts), market
    assert data["path"], "價格路徑不能是空的"
    for point in data["path"]:
        assert {"t", "excess", "n"} <= set(point)
    assert "期望值%" in data["winloss"]
    for item in data["current"]:
        assert {"buyDay", "sellDay", "status", "histEV"} <= set(item)
        # 同類統計是哪個市場算的,以及有沒有退回混合
        assert {"market", "histPooled"} <= set(item)
