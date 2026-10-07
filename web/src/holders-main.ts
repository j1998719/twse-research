/** 大戶持股頁的進入點。資料由 build 內嵌成全域的 HOLDERS_DATA。 */

import { pct, sign, thousands } from "./format.ts";
import {
	type Big,
	belowMa,
	bigHolders,
	type FlowKey,
	type HolderRow,
	type Holders,
	inst5,
	type MaFilter,
	matches,
	parseHolders,
	type SortKey,
	sortBig,
	sortFlows,
} from "./holders.ts";

declare const HOLDERS_DATA: unknown;

/** 一次畫幾列。全市場一千多檔一次畫完,手機會卡 */
const PAGE = 100;

interface State {
	level: number;
	sort: SortKey;
	market: string;
	minLots: number;
	query: string;
	shown: number;
}

function el<T extends HTMLElement>(id: string): T {
	const found = document.getElementById(id);
	if (!found) throw new Error(`頁面上找不到 #${id}`);
	return found as T;
}

function escapeHtml(text: string): string {
	return text.replace(
		/[&<>"]/g,
		(c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] ?? c,
	);
}

/** 週變化是百分點,不是百分比 —— 49% 變 50% 是 +1 個百分點 */
function points(value: number | null): string {
	if (value === null) return "—";
	return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

function rowHtml(item: Big, rank: number): string {
	const r = item.row;
	const stale =
		r.day === latestDay ? "" : ` <small class="qual">${r.day.slice(5)}</small>`;
	return `<tr>
 <td class="num rank">${rank}</td>
 <td><b class="code">${escapeHtml(r.code)}</b> ${escapeHtml(r.name)}<small class="qual mk">${r.market === "otc" ? "櫃" : "市"}</small></td>
 <td class="num">${r.close.toFixed(2)}${stale}</td>
 <td class="num ${sign(r.change)}">${pct(r.change)}</td>
 <td class="num strong">${item.pct.toFixed(2)}%</td>
 <td class="num ${sign(item.delta)}">${points(item.delta)}</td>
 <td class="num opt">${thousands(item.people)}</td>
 <td class="num opt">${r.lots === null ? "—" : thousands(r.lots)}</td>
</tr>`;
}

function maRowHtml(r: HolderRow, rank: number): string {
	const price = (v: number | null): string => (v === null ? "—" : v.toFixed(2));
	return `<tr>
 <td class="num rank">${rank}</td>
 <td><b class="code">${escapeHtml(r.code)}</b> ${escapeHtml(r.name)}<small class="qual mk">${r.market === "otc" ? "櫃" : "市"}</small></td>
 <td class="num">${r.close.toFixed(2)}</td>
 <td class="num opt">${price(r.ma5y)}</td>
 <td class="num ${sign(r.gap5y)}">${pct(r.gap5y)}</td>
 <td class="num opt">${price(r.ma10y)}</td>
 <td class="num ${sign(r.gap10y)}">${pct(r.gap10y)}</td>
 <td class="num opt">${(r.pct[r.pct.length - 1] ?? 0).toFixed(2)}%</td>
</tr>`;
}

/** 門檻按鈕。轉成陣列才能 for...of —— tsconfig 沒有開 DOM.Iterable */
function levelButtons(): HTMLButtonElement[] {
	return Array.from(
		document.querySelectorAll<HTMLButtonElement>("[data-level]"),
	);
}

let data: Holders;
let latestDay = "";
const state: State = {
	level: 3,
	sort: "pct",
	market: "all",
	minLots: 100,
	query: "",
	shown: PAGE,
};

function draw(): void {
	const items = sortBig(
		bigHolders(
			data.rows.filter(
				(r) =>
					matches(r, state.query) &&
					(state.market === "all" || r.market === state.market) &&
					(r.lots ?? 0) >= state.minLots,
			),
			state.level,
		),
		state.sort,
	);
	const body = el("rows");
	body.innerHTML = items
		.slice(0, state.shown)
		.map((item, i) => rowHtml(item, i + 1))
		.join("");
	el("count").textContent = `共 ${thousands(items.length)} 檔`;
	const more = el<HTMLButtonElement>("more");
	more.hidden = items.length <= state.shown;
	more.textContent = `再顯示 ${Math.min(PAGE, items.length - state.shown)} 檔`;
	el("th-big").textContent = `${data.thresholds[state.level]} 張以上持股`;
	for (const button of levelButtons()) {
		button.setAttribute(
			"aria-pressed",
			String(Number(button.dataset.level) === state.level),
		);
	}
}

/** 均線清單:預設只勾十年線 */
const maState: MaFilter & { shown: number } = {
	ma5y: false,
	ma10y: true,
	shown: PAGE,
};

function drawMa(): void {
	if (!data.maReady) return;
	const items = belowMa(data.rows, maState);
	el("ma-rows").innerHTML = items
		.slice(0, maState.shown)
		.map((r, i) => maRowHtml(r, i + 1))
		.join("");
	const picked = [maState.ma10y && "十年線", maState.ma5y && "五年線"].filter(
		Boolean,
	);
	el("ma-count").textContent =
		picked.length === 0
			? "在右上角「篩選」勾選要看哪一條線"
			: `收盤價低於${picked.join("和")}:共 ${thousands(items.length)} 檔`;
	const more = el<HTMLButtonElement>("ma-more");
	more.hidden = items.length <= maState.shown;
	more.textContent = `再顯示 ${Math.min(PAGE, items.length - maState.shown)} 檔`;
}

function bindMa(): void {
	for (const key of ["ma5y", "ma10y"] as const) {
		const box = el<HTMLInputElement>(`f-${key}`);
		box.checked = maState[key];
		box.addEventListener("change", () => {
			maState[key] = box.checked;
			maState.shown = PAGE;
			drawMa();
		});
	}
	el("ma-more").addEventListener("click", () => {
		maState.shown += PAGE;
		drawMa();
	});
}

function bind(): void {
	for (const button of levelButtons()) {
		button.addEventListener("click", () => {
			state.level = Number(button.dataset.level);
			state.shown = PAGE;
			draw();
		});
	}
	const sortBox = el<HTMLSelectElement>("sort");
	sortBox.addEventListener("change", () => {
		state.sort = sortBox.value as SortKey;
		state.shown = PAGE;
		draw();
	});
	const marketBox = el<HTMLSelectElement>("market");
	marketBox.addEventListener("change", () => {
		state.market = marketBox.value;
		state.shown = PAGE;
		draw();
	});
	const lotsBox = el<HTMLSelectElement>("min-lots");
	lotsBox.addEventListener("change", () => {
		state.minLots = Number(lotsBox.value);
		state.shown = PAGE;
		draw();
	});
	const search = el<HTMLInputElement>("q");
	search.addEventListener("input", () => {
		state.query = search.value;
		state.shown = PAGE;
		draw();
	});
	el("more").addEventListener("click", () => {
		state.shown += PAGE;
		draw();
	});
}

const TABS = ["holders", "ma", "flows"] as const;
type Tab = (typeof TABS)[number];

/** 一次只顯示一份清單。網址的 #ma 可以直接打開均線那一頁 */
function showTab(tab: Tab): void {
	for (const name of TABS) {
		const selected = name === tab;
		el(`tab-${name}`).setAttribute("aria-selected", String(selected));
		el(`${name}-section`).hidden = !selected;
	}
}

/** 籌碼總覽 */
const flowState = { sort: "inst5" as FlowKey, query: "", shown: PAGE };

/** 張數:千分位,正數加號 */
function lots(value: number | null): string {
	if (value === null) return "—";
	return `${value > 0 ? "+" : ""}${thousands(value)}`;
}

function flowRowHtml(r: HolderRow, rank: number): string {
	const big = r.pct[r.pct.length - 1] ?? 0;
	const prev = r.prevPct?.[r.prevPct.length - 1];
	const weekly =
		prev === undefined ? null : Math.round((big - prev) * 100) / 100;
	const total = inst5(r);
	return `<tr>
 <td class="num rank">${rank}</td>
 <td><b class="code">${escapeHtml(r.code)}</b> ${escapeHtml(r.name)}<small class="qual mk">${r.market === "otc" ? "櫃" : "市"}</small></td>
 <td class="num">${r.close.toFixed(2)}</td>
 <td class="num">${big.toFixed(2)}%</td>
 <td class="num opt ${sign(weekly)}">${points(weekly)}</td>
 <td class="num strong ${sign(total)}">${lots(total)}</td>
 <td class="num opt ${sign(r.foreign5)}">${lots(r.foreign5)}</td>
 <td class="num opt ${sign(r.trust5)}">${lots(r.trust5)}</td>
 <td class="num opt">${r.margin === null ? "—" : thousands(r.margin)}</td>
 <td class="num ${sign(r.marginChg5)}">${lots(r.marginChg5)}</td>
 <td class="num opt">${r.shortRatio === null ? "—" : `${r.shortRatio.toFixed(2)}%`}</td>
</tr>`;
}

function drawFlows(): void {
	if (!data.flowsReady) return;
	const items = sortFlows(
		data.rows.filter((r) => matches(r, flowState.query)),
		flowState.sort,
	);
	el("flow-rows").innerHTML = items
		.slice(0, flowState.shown)
		.map((r, i) => flowRowHtml(r, i + 1))
		.join("");
	el("flow-count").textContent = `共 ${thousands(items.length)} 檔`;
	const more = el<HTMLButtonElement>("flow-more");
	more.hidden = items.length <= flowState.shown;
	more.textContent = `再顯示 ${Math.min(PAGE, items.length - flowState.shown)} 檔`;
}

function bindFlows(): void {
	const sortBox = el<HTMLSelectElement>("flow-sort");
	sortBox.addEventListener("change", () => {
		flowState.sort = sortBox.value as FlowKey;
		flowState.shown = PAGE;
		drawFlows();
	});
	const search = el<HTMLInputElement>("flow-q");
	search.addEventListener("input", () => {
		flowState.query = search.value;
		flowState.shown = PAGE;
		drawFlows();
	});
	el("flow-more").addEventListener("click", () => {
		flowState.shown += PAGE;
		drawFlows();
	});
}

function bindTabs(): void {
	for (const name of TABS) {
		el(`tab-${name}`).addEventListener("click", () => {
			showTab(name);
			try {
				history.replaceState(null, "", name === "holders" ? "#" : `#${name}`);
			} catch {
				// 有些檢視器不讓改網址,不影響切換
			}
		});
	}
	const fromHash = TABS.find((name) => `#${name}` === location.hash);
	showTab(fromHash ?? "holders");
}

function main(): void {
	data = parseHolders(HOLDERS_DATA);
	latestDay = data.rows.reduce((max, r) => (r.day > max ? r.day : max), "");
	el("m-day").textContent = data.day ?? "—";
	el("m-price").textContent = latestDay || "—";
	el("m-gen").textContent = data.generated;
	const deltaOption = el<HTMLOptionElement>("sort-delta");
	if (data.prevDay === null) {
		// 只有一份快照時沒有週變化,排序選項留著會排出一張全是「—」的表
		deltaOption.disabled = true;
		el("no-prev").hidden = false;
	} else {
		el("m-prev").textContent = `(比較 ${data.prevDay})`;
	}
	if (!data.maReady) {
		el("ma-pending").hidden = false;
		el("ma-table").hidden = true;
	}
	if (!data.flowsReady) {
		el("flows-pending").hidden = false;
		el("flow-table").hidden = true;
	}
	bind();
	bindMa();
	bindFlows();
	bindTabs();
	draw();
	drawMa();
	drawFlows();
}

main();
