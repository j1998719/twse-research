"""跑 [#20] 的集中度檢定,完全走 [#22] 的框架。

[#20] 原本只跑穩懋一檔,而且用的是 [#19] 的 review 抓出問題**之前**的管線:
沒有去期間化,基準是每日再平衡指數對上買進持有的個股。那一輪唯一留下的
「線索」是 Gini 隨持有期單調變強(原始 p 從 0.975 降到 0.049)—— 而期間
叢聚正是會製造那種梯度的東西。

事前登記的組合:2 個指標 × 5 個持有期 = 10 個檢定,一次 BH 校正。
([#20] 原本寫 3 個指標,但「等效持有人數」是 1/HHI,跑出來會是同一個檢定。)

走框架的意義在於守衛不再靠自律:進場早於公布日的事件進不了樣本、重疊窗口
自動篩掉並回報獨立期間數、去期間化與原始兩種都算、同期相關性一起算、
涵蓋率跟著輸出並在低於門檻時標示為先導測試([#23])。
"""

from __future__ import annotations

from src.eventdata import available_codes, load_closes, load_weeks
from src.events.dispersion import events as dispersion_events
from src.study import Event, Grouping, Spec, period_window, report, run_study
from src.tdcc import Week, gini, herfindahl


#: 事前登記的持有期(幾個集保週次)。跑完不補測
HORIZONS = (1, 2, 4, 8, 13)
#: 事前登記的指標
METRICS = ("HHI", "Gini")


def _value(name: str, week: Week) -> float | None:
    return herfindahl(week) if name == "HHI" else gini(week)


def _tags(before: Week | None, week: Week) -> dict[str, object]:
    """每個指標的「這一週」和「前一週」都掛上去,分組時要比大小。"""
    tags: dict[str, object] = {}
    for name in METRICS:
        tags[name] = _value(name, week)
        tags[f"prev_{name}"] = None if before is None else _value(name, before)
    return tags


def rose(name: str) -> object:
    """分組:這一週的指標比上一週高。

    任一邊算不出來就回 None —— 那一筆不參加這個檢定,而不是被當成
    「沒上升」塞進對照組,那會讓一筆無從判斷的觀察污染對照組。
    """

    def decide(event: Event) -> bool | None:
        now = event.tags.get(name)
        before = event.tags.get(f"prev_{name}")
        if not isinstance(now, float) or not isinstance(before, float):
            return None
        return now > before

    return decide


def main() -> int:
    """跑 10 個檢定。每個持有期是一個 Spec,因為窗口長度不同。"""
    closes = load_closes()
    events: list[Event] = []
    weeks: set[object] = set()
    for code in available_codes():
        loaded = load_weeks(code)
        weeks.update(w.day for w in loaded)
        events.extend(dispersion_events(loaded, tag=_tags))
    periods = sorted(weeks)  # type: ignore[type-var]

    print(f"樣本 {len({e.code for e in events})} 檔,基準用 {len(closes)} 檔")
    print(f"事件 = 指標比上一週上升。持有期 {HORIZONS} 個集保週次")

    findings = []
    coverage = None
    for horizon in HORIZONS:
        spec = Spec(
            name=f"集中度/{horizon}週",
            window_of=period_window(periods, horizon),  # type: ignore[arg-type]
            groupings=tuple(
                Grouping(f"{name}/{horizon}週", horizon, rose(name))  # type: ignore[arg-type]
                for name in METRICS
            ),
            universe=len(closes),
        )
        got, coverage = run_study(spec, events, closes, periods)
        findings.extend(got)

    if coverage is None:
        print("沒有可用的持有期")
        return 1
    print()
    print(report(findings, coverage))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
