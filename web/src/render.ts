/** 把 report.json 的內容填進版面。版面結構在 index.html,這裡只管填值。 */

import { drawMonthly, drawPath } from "./charts.ts";
import { pct, pValue, sign, thousands } from "./format.ts";
import type {
	CapitalRow,
	Current,
	MarketCoverage,
	Report,
	Summary,
	WinLoss,
} from "./report.ts";

/** 新制上路的月份,月份圖用它換色 */
const NEW_RULES_MONTH = "2026-08";

/** 狀態文字 -> 樣式類別 */
const STATE_CLASS: Record<string, string> = {
	今天賣出: "now",
	持有中: "hold",
	尚未到買點: "wait",
	已過賣點: "past",
};

function fill(id: string, text: string): void {
	const node = document.querySelector(`#${id}`);
	if (node) node.textContent = text;
}

function html(id: string, markup: string): void {
	const node = document.querySelector(`#${id}`);
	if (node) node.innerHTML = markup;
}

function meta(report: Report): void {
	const c = report.coverage;
	fill("m-range", `${c.from} – ${c.to}`);
	fill("m-notice", thousands(c.notices));
	// 注意股目前只有上市 —— 旁邊的「處置」是兩個市場,不標的話讀起來像同一個範圍
	fill("m-notice-mk", c.noticesMarket === "twse" ? "(僅上市)" : "");
	fill("m-punish", thousands(c.punishes));
	fill("m-days", thousands(c.tradingDays));
	fill("m-bt", thousands(c.backtested));
	fill("m-codes", c.codes === undefined ? "—" : thousands(c.codes));
	fill("m-markets", marketBreakdown(c.markets));
	fill("m-drop", String(c.dropped.lookahead + c.dropped.fakeRelease));
	fill("m-gen", report.generated);
	// 這幾個數字本來寫死在 HTML 裡,所以每次資料變動就會再錯一次 ——
	// 頁面上半部用資料渲染、下半部寫死,兩邊必然會漂開
	fill("v-lookahead", thousands(c.dropped.lookahead));
	fill("v-fake", thousands(c.dropped.fakeRelease));
	fill("v-ratios", `都在 ${ratioRange(report)} 之間`);
	fill(
		"v-winrates",
		`${pct(report.headline["勝率%"])} vs ${pct(report.afterRelease["勝率%"])}`,
	);
	fill("rate", String(report.rate.每月平均 ?? "—"));
}

/** 三組賺賠比的範圍。寫死一個區間會在資料變動時變成假話。 */
function ratioRange(report: Report): string {
	const values = [report.winloss, report.winlossSecond]
		.map((w) => w.賺賠比)
		.filter((v): v is number => typeof v === "number");
	if (values.length === 0) return "相近";
	const low = Math.min(...values);
	const high = Math.max(...values);
	return `${low.toFixed(2)} 到 ${high.toFixed(2)}`;
}

/** 分市場的事件數。看到 2,265 筆的人要知道那裡面有多少是上櫃的。 */
function marketBreakdown(
	markets: Record<string, MarketCoverage> | undefined,
): string {
	// 舊的 report.json 沒有這一欄。Object.entries(undefined) 會丟 TypeError,
	// 而 meta() 是最先跑的 —— 那不是少一個欄位,是整頁空白
	const label: Record<string, string> = { twse: "上市", otc: "上櫃" };
	const parts = Object.entries(markets ?? {})
		.sort(([a], [b]) => a.localeCompare(b))
		.map(
			([key, m]) =>
				`${label[key] ?? key} ${thousands(m.backtested)}(${thousands(m.codes)} 檔)`,
		);
	return parts.join(" · ") || "—";
}

function card(item: Current): string {
	const second = item.measure === "第二次處置";
	const state = STATE_CLASS[item.status] ?? "wait";
	return `
 <article class="cell ${second ? "second" : ""}">
  <div class="cell-top"><span class="code num">${item.code}</span>
   <span class="nm">${item.name}</span>
   <span class="tag">${second ? "全額預收" : "第一次"}</span></div>
  <div class="why">${item.condition}<br>${item.start} – ${item.end}</div>
  <div class="countdown"><span class="big num">${item.daysLeft}</span>
   <small>天後出關(${item.release})</small></div>
  <div class="plan">
   <dl>
    <dt>參考買點 t−6</dt><dd>${item.buyDay}</dd>
    <dt>參考賣點 t−1</dt><dd>${item.sellDay}</dd>
    <dt>歷史同類</dt><dd>${item.histN} 筆</dd>
    <dt>中位數 / 勝率</dt><dd>${pct(item.histMedian)} / ${item.histWin}%</dd>
    <dt>期望值</dt><dd class="ev">${pct(item.histEV)}</dd>
    <dt>賺時 / 賠時</dt><dd>${pct(item.histWinAvg)} / ${pct(item.histLossAvg)}</dd>
    <dt>歷史最慘</dt><dd>${pct(item.histWorst)}</dd>
   </dl>
   <span class="state ${state}">${item.status}</span>
  </div>
 </article>`;
}

function verdict(report: Report): string {
	const h = report.headline;
	const w = report.winloss;
	const a = report.afterRelease;
	return `
 <p>在 <b class="num">${thousands(h.樣本數)}</b> 次處置裡,於出關前第六個交易日收盤買進、<strong>出關前一日收盤賣出</strong>,超額報酬中位數 <b class="num">${pct(h["中位數%"])}</b>,勝率 <span class="num">${h["勝率%"]}%</span>。已扣掉來回成本與大盤同期漲跌。</p>
 <p>反過來,<strong>等出關之後才買</strong>,持有五日的中位數是 <span class="num">${pct(a["中位數%"])}</span>,勝率只有 <span class="num">${a["勝率%"]}%</span>。市場上常說的「出關必噴」,資料不支持 —— 噴的那一段發生在出關之前。</p>
 <p>賺的時候平均 <span class="num">${pct(w["賺_平均%"])}</span>,賠的時候平均 <span class="num">${pct(w["賠_平均%"])}</span>,<strong>期望值 ${pct(w["期望值%"])}</strong>。四分位距 <span class="num">${pct(h["四分之一%"])}</span> 到 <span class="num">${pct(h["四分之三%"])}</span>,最慘一次 <span class="num">${pct(h["最小%"])}</span> —— 中位數是正的,但尾部很長。</p>`;
}

/** 賺賠表格子的顯示方式依列而異 */
function cellText(label: string, value: number): string {
	if (label === "樣本") return thousands(value);
	if (label === "勝率") return `${value.toFixed(1)}%`;
	if (label === "賺賠比") return value.toFixed(2);
	return pct(value);
}

/** 賺賠對照表。第三欄是「出關後才買」,只有部分欄位有值 */
function winLossRows(a: WinLoss, b: WinLoss, after: Summary): string {
	const rows: [string, (w: WinLoss) => number, number | null, boolean][] = [
		["樣本", (w) => w.全部_樣本, after.樣本數, false],
		["勝率", (w) => w["勝率%"], after["勝率%"], true],
		["賺的平均", (w) => w["賺_平均%"], null, false],
		["賺的中位數", (w) => w["賺_中位數%"], null, false],
		["賠的平均", (w) => w["賠_平均%"], null, false],
		["賠的中位數", (w) => w["賠_中位數%"], null, false],
		["賺賠比", (w) => w.賺賠比, null, false],
		["期望值", (w) => w["期望值%"], after["平均%"], true],
	];
	return rows
		.map(([label, pick, third, strong]) => {
			const cells = [pick(a), pick(b), third]
				.map((v) =>
					v === null
						? '<td class="num">—</td>'
						: `<td class="num ${strong ? sign(v) : ""}">${cellText(label, v)}</td>`,
				)
				.join("");
			return `<tr class="${strong ? "total" : ""}"><td>${label}</td>${cells}</tr>`;
		})
		.join("");
}

/** 本金那一欄的文字。null 是無限,"market" 是大盤對照列 */
function capitalLabel(capital: CapitalRow["capital"]): string {
	if (capital === "market") return "大盤(全程持有)";
	if (capital === null) return "資金無限";
	return `${thousands(capital)} 元`;
}

function capitalRow(row: CapitalRow, total: number): string {
	const isMarket = row.capital === "market";
	const label = capitalLabel(row.capital);
	return `<tr class="${isMarket ? "total" : ""}"><td>${label}</td>
   <td class="num">${row.taken === null ? "—" : `${row.taken}/${total}`}</td>
   <td class="num ${sign(row.ret)}">${row.ret.toFixed(1)}%</td>
   <td class="num">${row.ann.toFixed(1)}%</td>
   <td class="num">${Math.round(row.days)}</td>
   <td class="num ${isMarket ? "" : "sig"}">${Math.round(row.bp)} bp</td>
   <td class="num">${row.concurrent ?? "—"}</td></tr>`;
}

function tables(report: Report): void {
	html(
		"t-exit",
		report.exits
			.map(
				(e, i) => `<tr class="${i === 0 ? "total" : ""}"><td>${e.label}</td>
   <td class="num">${thousands(e.n)}</td>
   <td class="num ${sign(e.median)}">${pct(e.median)}</td>
   <td class="num win">${e.win}%</td>
   <td class="num ${e.p < 0.05 ? "sig" : "win"}">${pValue(e.p)}</td></tr>`,
			)
			.join(""),
	);

	const h = report.headline;
	html(
		"t-years",
		`${report.years
			.map(
				(y) => `<tr class="${y.bear ? "bear" : ""}"><td>${y.name}</td>
   <td class="num">${y.n}</td>
   <td class="num ${sign(y.median)}">${pct(y.median)}</td>
   <td class="num win">${y.win}%</td>
   <td class="num ${y.p < 0.05 ? "sig" : "win"}">${pValue(y.p)}</td></tr>`,
			)
			.join("")}<tr class="total"><td>整段期間</td>
   <td class="num">${thousands(h.樣本數)}</td>
   <td class="num ${sign(h["中位數%"])}">${pct(h["中位數%"])}</td>
   <td class="num">${h["勝率%"]}%</td>
   <td class="num sig">&lt;0.0001</td></tr>`,
	);

	html(
		"t-wl",
		winLossRows(report.winloss, report.winlossSecond, report.afterRelease),
	);

	const secondTotal = report.caps[0]?.total ?? 0;
	html(
		"t-cap",
		report.caps.map((row) => capitalRow(row, secondTotal)).join(""),
	);

	html(
		"t-off",
		report.offenders
			.map(
				(o) => `<tr><td><span class="code num">${o.code}</span> ${o.name}</td>
   <td class="num">${o.total}</td><td class="num">${o.second}</td>
   <td class="num ${o.second / o.total >= 0.6 ? "pos" : "win"}">${Math.round((o.second / o.total) * 100)}%</td></tr>`,
			)
			.join(""),
	);
}

export function render(report: Report): void {
	meta(report);
	html(
		"board",
		report.current.length > 0
			? report.current.map(card).join("")
			: '<p class="lede">目前沒有個股在處置期間。</p>',
	);
	html("verdict", verdict(report));
	html(
		"binomial",
		`<h3>七年全部是正的</h3>
 <p style="margin:0">個別年份因為樣本小,有幾年沒到顯著。但<strong>七個期間的中位數全部為正</strong> —— 若真實效果是零,這種情況出現的機率是 0.5<sup>7</sup> = <span class="num">${report.binomial}</span>。方向的一致性本身就是證據。<br>
 黃底那列是 <strong>2022 空頭年</strong>,中位數同樣為正,與多頭年沒有顯著差異(p=0.83)。這支持「流動性折價」的解釋,而不是「多頭時什麼都會漲」。</p>`,
	);
	tables(report);

	const draw = (): void => {
		drawPath(report.path.map((p) => [p.t, p.excess]));
		drawMonthly(report.monthly, NEW_RULES_MONTH);
	};
	draw();
	matchMedia("(prefers-color-scheme:dark)").addEventListener("change", draw);
}
