"""每一支可以直接執行的模組都要有 --help(#58)。"""

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from src import cli


ROOT = Path(__file__).resolve().parent.parent
RUNNABLE = sorted(
    p.stem
    for p in (ROOT / "src").glob("*.py")
    if '__name__ == "__main__"' in p.read_text(encoding="utf-8")
)


def test_找得到可執行的模組() -> None:
    assert len(RUNNABLE) >= 18


@pytest.mark.parametrize("module", RUNNABLE)
def test_每一支都有_help(module: str) -> None:
    # 新加的執行入口忘了接 cli,這裡會抓到:沒有 --help 的程式會把它當成一般參數照跑
    done = subprocess.run(  # noqa: S603 —— 模組名來自 src/ 的檔名,不是外部輸入
        [sys.executable, "-m", f"src.{module}", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith(f"usage: .venv/bin/python -m src.{module}")
    # 說明就是模組的 docstring,不是空的
    assert re.search(r"[一-鿿]", done.stdout)


def test_日期區間() -> None:
    assert cli.date_range(None, ["2026-01-01", "2026-10-07"]) == (
        date(2026, 1, 1),
        date(2026, 10, 7),
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["2026/01/01", "2026-10-07"],  # 斜線
        ["115-01-01", "2026-10-07"],  # 民國年
        ["2026-10-07", "2026-01-01"],  # 起訖顛倒
        ["2026-01-01"],  # 少一個
    ],
)
def test_日期區間_寫錯就報錯(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.date_range(None, argv)
    assert exc.value.code == 2


def test_不吃參數的模組_多給就報錯() -> None:
    with pytest.raises(SystemExit):
        cli.no_args(None, ["oops"])
