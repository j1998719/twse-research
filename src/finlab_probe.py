"""確認 finlab 免費方案拿得到什麼資料。

不是正式流程的一部分,只是用來決定價量資料要走 finlab 還是證交所。
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path


def load_env(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    warnings.filterwarnings("ignore")
    load_env()

    import finlab
    from finlab import data

    finlab.login(os.environ["FINLAB_TOKEN"])
    print("登入成功")

    try:
        print("方案等級:", data.get_role())
    except Exception as exc:
        print("查不到方案等級:", type(exc).__name__)

    for name in [
        "price:收盤價",
        "price:成交股數",
        "price:開盤價",
        "etl:adj_close",
    ]:
        try:
            table = data.get(name)
            print(
                f"✅ {name}: {table.shape[0]} 天 × {table.shape[1]} 檔"
                f" | {table.index.min().date()} ~ {table.index.max().date()}"
            )
        except Exception as exc:
            print(f"❌ {name}: {type(exc).__name__} {str(exc)[:120]}")

    # 找找看有沒有處置股相關資料集
    try:
        hits = [d for d in data.search("處置") or []]
        print("\n搜尋「處置」:", hits[:10] if hits else "沒有")
    except Exception as exc:
        print("\n搜尋失敗:", type(exc).__name__, str(exc)[:120])


if __name__ == "__main__":
    main()
