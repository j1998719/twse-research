"""命令列參數的共用寫法:每一支可以直接執行的模組都有 --help(#58)。

說明文字就是模組開頭的 docstring —— 只寫一份,--help 跟程式碼不會各說各話。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Sequence


def _prog() -> str:
    """`python -m src.xxx` 跑的時候,--help 第一行顯示的指令。"""
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    name = spec.name if spec is not None else "src.<模組>"
    return f".venv/bin/python -m {name}"


def parser(doc: str | None) -> argparse.ArgumentParser:
    """以模組 docstring 當說明的 parser。要加自己的參數就從這裡開始。"""
    return argparse.ArgumentParser(
        prog=_prog(),
        description=doc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def iso_day(text: str) -> date:
    """YYYY-MM-DD。民國年、斜線之類的寫法直接擋掉,不要猜。"""
    try:
        return date.fromisoformat(text)
    except ValueError:
        msg = f"日期要寫成 YYYY-MM-DD,例如 2026-10-07(收到 {text!r})"
        raise argparse.ArgumentTypeError(msg) from None


def no_args(doc: str | None, argv: Sequence[str] | None = None) -> None:
    """不吃參數的模組:只提供 --help,多給參數就報錯而不是默默忽略。"""
    parser(doc).parse_args(argv)


def date_range(doc: str | None, argv: Sequence[str] | None = None) -> tuple[date, date]:
    """起訖日期兩個位置參數(都含)。"""
    p = parser(doc)
    p.add_argument("start", type=iso_day, help="起始日(含),例如 2026-01-01")
    p.add_argument("end", type=iso_day, help="結束日(含),例如 2026-10-07")
    args = p.parse_args(argv)
    if args.end < args.start:
        p.error(f"結束日 {args.end} 早於起始日 {args.start}")
    return args.start, args.end
