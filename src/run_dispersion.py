"""跑 [#19] 事前登記的出貨訊號檢定,完全走 [#22] 的框架。

參數在 [#21] 的留言裡先寫死了:回看 8 週、回落 2 個百分點,持有期 4/8/13 週,
三個訊號定義 —— 合計 9 個檢定,一次 BH 校正。跑完不補測。

樣本是 [#21] 的 20 檔系統性抽樣。**這不是全市場研究**,是先導測試:集保
查詢頁一檔一週要兩個請求,全市場回溯要約 10 萬個請求([#23])。框架會自己
在輸出上標示。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src import cli
from src.dispersion import DROP_PP, LOOKBACK, signals
from src.eventdata import available_codes, load_closes, load_weeks
from src.events.dispersion import events as dispersion_events
from src.study import Event, Grouping, Spec, period_window, report, run_study


if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.tdcc import Week

#: 事前登記的持有期(幾個集保週次)
HORIZONS = (4, 8, 13)
#: 事前登記的三個訊號。名稱就是 Signal 上的欄位名
SIGNALS = ("big_rolled_over", "holders_peaked", "distributing")


def _tags(prior: Sequence[Week], week: Week) -> dict[str, object]:
    """這一週有沒有觸發各個訊號。

    signals() 要看前 LOOKBACK 週才算得出滾動高點,所以把歷史接上這一週再算,
    然後取最後一筆 —— 歷史不足時它回空清單,代表這一週無從判斷。
    """
    got = signals([*prior, week])
    if not got or got[-1].day != week.day:
        return {}
    last = got[-1]
    return {name: getattr(last, name) for name in SIGNALS}


def fired(name: str) -> object:
    """分組:這一週觸發了這個訊號。

    訊號算不出來(歷史不足)就回 None —— 那一筆不參加檢定,而不是被當成
    「沒觸發」塞進對照組。回報「沒觸發」會讓早期的週次看起來是乾淨的對照組。
    """

    def decide(event: Event) -> bool | None:
        value = event.tags.get(name)
        return value if isinstance(value, bool) else None

    return decide


def main() -> int:
    """跑 9 個檢定。每個持有期一個 Spec,因為窗口長度不同。"""
    cli.no_args(__doc__)
    closes = load_closes()
    events: list[Event] = []
    weeks: set[object] = set()
    for code in available_codes():
        loaded = load_weeks(code)
        weeks.update(w.day for w in loaded)
        events.extend(dispersion_events(loaded, tag=_tags))
    periods = sorted(weeks)  # type: ignore[type-var]

    print(f"樣本 {len({e.code for e in events})} 檔,基準用 {len(closes)} 檔")
    print(f"回看 {LOOKBACK} 週、回落 {DROP_PP} 個百分點,持有期 {HORIZONS} 週")

    findings = []
    coverages = []
    for horizon in HORIZONS:
        spec = Spec(
            name=f"出貨訊號/{horizon}週",
            window_of=period_window(periods, horizon),  # type: ignore[arg-type]
            horizon=horizon,
            groupings=tuple(
                Grouping(f"{name}/{horizon}週", fired(name))  # type: ignore[arg-type]
                for name in SIGNALS
            ),
            universe=len(closes),
        )
        got, coverage = run_study(spec, events, closes, periods)
        findings.extend(got)
        coverages.append(coverage)

    print()
    # declared:事前登記的檢定數。少掉的要在輸出上交代
    print(report(findings, coverages, declared=len(HORIZONS) * len(SIGNALS)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
