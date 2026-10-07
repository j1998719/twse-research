"""跑 #26 事前登記的 7 個可轉債條款檢定,重現整張結果表。

用法:.venv/bin/python -m src.run_cb

先要有:
  - data/raw/cbboard/ 的看板日存檔(src.fetch_cbboard 2017-01-01 <今天>)
  - data/out/long_prices.csv 含成交股數(src.fetch_history 2016-01-01 <今天>)
  - data/out/corporate_actions.csv(src.fetch_actions;還原除權息)

流程完全照登記(第五、六、七輪):

1. 看板 → 每一對 (債, 賣回權起日)、(債, 轉換起日);錨點前一份看板上就看得到的
   才是事件,knowable = 第一次出現的那一天
2. 發行年份代理 = 轉換起日往前推三個月;≤ 2021 是形成組,2022 起是驗證組
3. 形成組跑 7 個檢定、一次 BH 校正,照事前寫的標準判定
4. **只有**判定為「找到了」的檢定,才在驗證組上重跑同一個檢定(不再校正),
   方向一致且 p < 0.05 才算樣本外成立

研究期間 2017 起,而 prices.csv 只從 2020 開始,所以股價用長日線
(long_prices.csv,2016 起)。
"""

from __future__ import annotations

import statistics
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
from scipy import stats

from src import cli
from src.cbboard import link_to_prices, load_boards
from src.cbstudy import (
    DECLARED,
    H1_WINDOWS,
    H3_WINDOWS,
    PREDICTED,
    Result,
    adjusted,
    horizon,
    lead_time,
    one_sample_test,
    put_groups,
    score,
    table,
    traded_value,
    two_group,
    verdict,
)
from src.events.cb import Ledger, events, sightings, tally
from src.eventstats import Observation
from src.run_chip_signals import (
    Excess,
    placebo_hits,
    scored as placebo_scored,
    summarize,
)
from src.run_wholemarket import closes_by_code
from src.study import ALPHA, Coverage, Window, pooled
from src.universe import all_actions, all_prices


if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from src.cbboard import Board
    from src.study import Event

BOARDS = Path("data/raw/cbboard")
HISTORY = Path("data/out/long_prices.csv")


def _counts(boards: Sequence[Board], prices: pd.DataFrame) -> None:
    """回填與對接的數字,跟第六輪那張表比。"""
    sizes = [len(b.bonds) for b in boards]
    print(
        f"看板 {len(boards)} 份,{boards[0].day} ~ {boards[-1].day},"
        f"每份列數中位 {statistics.median(sizes):.0f}"
    )
    for label, table_ in (
        ("prices.csv + tpex_prices.csv(2020 起)", all_prices()),
        ("long_prices.csv(2016 起)", prices),
    ):
        linked = link_to_prices(boards, table_)
        print(
            f"  對 {label}:CB {linked.bonds} 檔、標的 {linked.underlyings} 檔,"
            f"有股價 {len(linked.priced)} 檔;沒有的:{', '.join(linked.missing)}"
        )
    for field in ("put_start", "conversion_start", "call_start", "next_reset"):
        t = tally(sightings(boards, field), boards)  # type: ignore[arg-type]
        print(
            f"  (債, {field}):{t.pairs} 對、錨點在期間內 {t.within}、"
            f"左設限 {t.left_censored}、前夕看得到 {t.on_eve}、當天或之後才出現 {t.late}"
        )


def pick_formation(group: Sequence[Event]) -> list[Event]:
    """形成組的事件。"""
    return [e for e in group if e.tags["sample"] == "formation"]


def _measures(put_events: Sequence[Event], data: Data) -> None:
    """H1、H2 的量測算得出來的筆數,不分組、不算報酬差。"""
    for window in H1_WINDOWS:
        scored = score(put_events, data.days, window, data.closes)
        groups = put_groups(scored, data.ledger, data.raw, data.value)
        print(
            f"  形成組 T{window.entry}:可用 {len(scored)} 筆,moneyness 算得出 "
            f"{groups.priced}、壓力算得出 {groups.loaded}(中位數 {groups.cut:.1f} 天)"
        )


def _leads(put_events: Sequence[Event], days: Sequence[date]) -> None:
    """賣回事件從第一次看得到到賣回日的前置期(交易日)。T−20 撤掉的理由。"""
    leads = sorted(x for e in put_events if (x := lead_time(e, days)) is not None)
    if not leads:
        return
    q = statistics.quantiles(leads, n=4)
    print(
        f"  賣回前置期(交易日):最小 {leads[0]}、四分位 {q[0]:.0f}、中位 {q[1]:.0f}、"
        f"四分之三 {q[2]:.0f}、最大 {leads[-1]}"
    )
    for k in (5, 10, 20):
        print(f"    T−{k} 進得了場:{sum(x >= k for x in leads)}/{len(leads)}")


def _ledger_check(ledger: Ledger, put_events: Sequence[Event]) -> None:
    """看板上的轉換價格跟「當天實際有效」的不一樣的有幾筆(GLOSS 註2)。"""
    differ = 0
    for event in put_events:
        bond = str(event.tags["bond"])
        row = ledger.as_of(bond, event.happened)
        price = ledger.conversion_price(bond, event.happened)
        if row is not None and price != row.conversion_price:
            differ += 1
    print(
        f"  賣回日當天看板掛的轉換價格還沒生效的:{differ}/{len(put_events)} 筆"
        "(這些若直接讀看板欄位就會用到未生效的價格)"
    )


def _put_tests(
    put_events: Sequence[Event],
    data: Data,
    only: set[str] | None = None,
) -> tuple[list[Result], list[Coverage]]:
    """H1、H2:每個窗口算一次報酬,兩個分組共用。"""
    results: list[Result] = []
    coverages: list[Coverage] = []
    for window in H1_WINDOWS:
        tag = f"T{window.entry}"
        names = (f"H1 價外>價內/{tag}", f"H2 壓力高>低/{tag}")
        if only is not None and not only & set(names):
            continue
        scored = score(put_events, data.days, window, data.closes)
        coverages.append(
            Coverage.of(
                f"賣回/{tag}", put_events, [s.event for s in scored], data.universe
            )
        )
        groups = put_groups(scored, data.ledger, data.raw, data.value)
        print(
            f"  {tag}:可用 {len(scored)} 筆,moneyness 算得出 {groups.priced}、"
            f"壓力算得出 {groups.loaded}(中位數 {groups.cut:.1f} 天)"
        )
        sides = (groups.out_of_money, groups.high_pressure)
        for name, side in zip(names, sides, strict=True):
            if only is not None and name not in only:
                continue
            got = two_group(name, name[:2], scored, side, horizon(window), data.days)
            if got is not None:
                results.append(got)
    return results, coverages


def _conversion_tests(
    conv_events: Sequence[Event], data: Data, only: set[str] | None = None
) -> tuple[list[Result], list[Coverage]]:
    """H3:轉換起日之後的超額報酬對 0。"""
    results: list[Result] = []
    coverages: list[Coverage] = []
    for window in H3_WINDOWS:
        name = f"H3 轉換起日後/T+{window.exit}"
        if only is not None and name not in only:
            continue
        scored = score(conv_events, data.days, window, data.closes)
        coverages.append(
            Coverage.of(
                f"轉換/T+{window.exit}",
                conv_events,
                [s.event for s in scored],
                data.universe,
            )
        )
        got = one_sample_test(name, "H3", scored, horizon(window), data.days)
        if got is not None:
            results.append(got)
    return results, coverages


def _placebo(
    label: str, group: Sequence[Event], windows: Sequence[Window], data: Data
) -> None:
    """安慰劑基準(診斷,不是新的檢定,不進 BH)。

    #60 的教訓:超額報酬扣了來回成本,而且單檔中位數天生低於全宇集的等權平均
    (右偏),所以「跟 0 比」的虛無假設其實不在 0。這裡用同一批標的股 × 同一段
    期間內的隨機交易日,走同一套算法(run_chip_signals 的 Excess / scored /
    summarize,數字跟 window_excess 一樣),看「沒有訊號」時的水位在哪裡。
    登記的檢定沒有流動性門檻,所以安慰劑也不設。

    事件的窗口 (進 a, 出 b) 對應 scored 的「事件日 = 進場前一天、持有 b − a 天」。
    有事件組的話(H3 單樣本)再印一個「事件 vs 安慰劑」的 Mann-Whitney p 當參考。
    """
    usable = [s for w in windows for s in score(group, data.days, w, data.closes)]
    if not usable:
        return
    codes = sorted({s.event.code for s in usable} & set(data.closes))
    lo, hi = min(s.entry for s in usable), max(s.entry for s in usable)
    days = pd.DatetimeIndex([pd.Timestamp(d) for d in data.days])
    span = days[(days >= pd.Timestamp(lo)) & (days <= pd.Timestamp(hi))]
    base = placebo_hits(codes, span)
    all_days = days

    def anywhere(_code: str, _day: pd.Timestamp) -> bool:
        return True

    print(
        f"\n安慰劑(診斷,不是檢定):{label}的標的 {len(codes)} 檔 × {lo}~{hi} 的隨機交易日"
    )
    for window in windows:
        hold = window.exit - window.entry
        frame = placebo_scored(base, hold, all_days, data.excess, anywhere)
        s0 = summarize(frame, data.market_of)
        line_ = (
            f"  窗口 ({window.entry:+d}, {window.exit:+d}) 持有 {hold} 日:n={s0['n']} "
            f"中位數 {s0['median']:+.2f}% 勝率 {s0['win']:.1f}% "
            f"群集 CI [{s0['low']:+.2f},{s0['high']:+.2f}]"
        )
        if window in H3_WINDOWS and label == "轉換起日":
            kept, _ = pooled(
                [
                    Observation(s.event.code, s.entry, s.excess, True)
                    for s in score(group, data.days, window, data.closes)
                ],
                horizon(window),
                data.days,
            )
            got = [o.excess for o in kept]
            p = float(
                stats.mannwhitneyu(got, frame.excess, alternative="two-sided").pvalue
            )
            line_ += (
                f";事件中位數 − 安慰劑中位數 = "
                f"{statistics.median(got) - float(frame.excess.median()):+.2f} 個百分點、"
                f"Mann-Whitney p={p:.4f}"
            )
        print(line_)


class Data:
    """跑檢定要的所有東西。"""

    def __init__(self, boards: Sequence[Board]) -> None:
        """讀長日線、還原因子;看板做成逐債的帳本。"""
        prices = pd.read_csv(HISTORY, dtype={"code": str}, parse_dates=["day"])
        self.prices = prices
        self.ledger = Ledger(boards)
        self.closes = closes_by_code(prices, all_actions())
        self.raw = closes_by_code(prices)
        self.value = traded_value(prices)
        self.days: list[date] = sorted(d.date() for d in prices.day.unique())
        self.universe = len(self.closes)
        #: 安慰劑用(run_chip_signals):快取等權基準的 window_excess
        self.excess = Excess(self.closes)
        self.market_of = {
            str(c): str(m) for c, m in zip(prices.code, prices.market, strict=True)
        }


def _family(
    put_events: Sequence[Event],
    conv_events: Sequence[Event],
    data: Data,
    only: set[str] | None = None,
) -> tuple[list[Result], list[Coverage]]:
    got_put, cov_put = _put_tests(put_events, data, only)
    got_conv, cov_conv = _conversion_tests(conv_events, data, only)
    return [*got_put, *got_conv], [*cov_put, *cov_conv]


def _validate(
    found: Sequence[str],
    put_events: Sequence[Event],
    conv_events: Sequence[Event],
    data: Data,
) -> None:
    """找到了的檢定在驗證組上重跑一次,不再校正。"""
    print("\n=== 驗證組(代理發行年份 2022 起)===")
    results, coverages = _family(put_events, conv_events, data, set(found))
    for coverage in coverages:
        print(coverage.describe())
    print(table(results, [r.p for r in results]))
    for r in results:
        same = (r.effect > 0) - (r.effect < 0) == PREDICTED[r.hypothesis]
        ok = r.p < ALPHA and same
        print(
            f"{r.name}:p={r.p:.3f},方向{'與預測一致' if same else '與預測相反'} → "
            f"{'樣本外成立' if ok else '樣本外不成立'}"
        )
    # 驗證組的判定也是「跟 0 比」(H3)或看單組水位,一樣要有安慰劑在旁邊
    if any(r.hypothesis in {"H1", "H2"} for r in results):
        _placebo("賣回", put_events, H1_WINDOWS, data)
    if any(r.hypothesis == "H3" for r in results):
        _placebo("轉換起日", conv_events, H3_WINDOWS, data)


def main(argv: Sequence[str] | None = None) -> int:
    """回填數字 → 事件 → 形成組 7 個檢定 → (必要時)驗證組。"""
    parser = cli.parser(__doc__)
    parser.add_argument(
        "--counts-only",
        action="store_true",
        help="只印回填、事件與量測的數字,不跑檢定(檢定前先驗資料用)",
    )
    args = parser.parse_args(argv)
    boards = load_boards(BOARDS)
    if not boards or not HISTORY.exists():
        print("沒有資料。先跑 src.fetch_cbboard 和 src.fetch_history")
        return 1
    data = Data(boards)
    _counts(boards, data.prices)

    put_all = events(sightings(boards, "put_start"), boards)
    conv_all = events(sightings(boards, "conversion_start"), boards)
    for label, group in (("賣回", put_all), ("轉換起日", conv_all)):
        split = Counter(str(e.tags["sample"]) for e in group)
        print(f"  {label}事件 {len(group)} 筆:{dict(split)}")

    _leads(put_all, data.days)
    _ledger_check(data.ledger, put_all)

    if args.counts_only:
        _measures(pick_formation(put_all), data)
        return 0

    def pick(group: Sequence[Event], which: str) -> list[Event]:
        return [e for e in group if e.tags["sample"] == which]

    print("\n=== 形成組(代理發行年份 ≤ 2021,含 2017 以前發行的)===")
    results, coverages = _family(
        pick(put_all, "formation"), pick(conv_all, "formation"), data
    )
    for coverage in coverages:
        print(coverage.describe())
    corrected = adjusted(results)
    print()
    print(table(results, corrected))
    if len(results) != DECLARED:
        print(f"⚠️ 事前登記 {DECLARED} 個檢定,實際跑出 {len(results)} 個")
    print(
        "\n效果:H1/H2 是事件組減對照組的中位數(百分點),H3 是超額報酬中位數。"
        "\n檢定p:H1/H2 是按進場月份去期間化後的 Mann-Whitney,H3 是 Wilcoxon;"
        "BH 校正用它。"
    )
    for r in results:
        same = (r.effect > 0) - (r.effect < 0) == PREDICTED[r.hypothesis]
        print(f"  {r.name}:方向{'與預測一致' if same else '與預測相反'}")
    _placebo("賣回", pick(put_all, "formation"), H1_WINDOWS, data)
    _placebo("轉換起日", pick(conv_all, "formation"), H3_WINDOWS, data)
    judged, which = verdict(results, corrected)
    print(f"\n判定:{judged} {which}")
    if judged == "找到了":
        _validate(
            which, pick(put_all, "validation"), pick(conv_all, "validation"), data
        )
    else:
        print("沒有「找到了」的檢定,依登記不跑驗證組。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
