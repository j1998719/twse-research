/**
 * 大戶頁的進入點。資料由 build 內嵌成全域的 HOLDERS_DATA。
 *
 * 一張清單 + 條件積木(#50)。規則在 screen.ts,這裡只負責畫面:
 * 條件列(勾選、≥ / ≤、數值、移除)、新增選單、排序、表格。
 */

import { thousands } from "./format.ts";
import { type HolderRow, type Holders, parseHolders } from "./holders.ts";
import { EXTERNAL, yahooQuote } from "./links.ts";
import {
	columns,
	ctx,
	defaultScreen,
	type Filter,
	isMetric,
	type Level,
	MAX_WEEKS,
	METRICS,
	type MetricKey,
	newFilter,
	restore,
	run,
	type Screen,
} from "./screen.ts";

declare const HOLDERS_DATA: unknown;

/** 一次畫幾列。全市場一千多檔一次畫完,手機會卡 */
const PAGE = 100;
/** 記住自己堆的條件。只在這個瀏覽器,換裝置不會跟著走 */
const STORE = "holders.screen.v1";
/** 標題要帶出目前大戶門檻的欄位 */
const LEVELLED: readonly MetricKey[] = [
	"big",
	"bigWeek",
	"people",
	"bigChgN",
	"peopleChgN",
];
/** 用到週資料的欄位 */
const WEEKLY: readonly MetricKey[] = [
	"bigChgN",
	"peopleChgN",
	"priceMoveN",
	"priceChgN",
];
/** 法人與融資融券來源的欄位 */
const FLOWS: readonly MetricKey[] = [
	"inst5",
	"foreign5",
	"trust5",
	"dealer5",
	"inst20",
	"marginChg5",
	"shortRatio",
];

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

let data: Holders;
let latestDay = "";
let screen: Screen = defaultScreen();
let shown = PAGE;

function load(): Screen {
	try {
		const raw = localStorage.getItem(STORE);
		return raw ? restore(JSON.parse(raw)) : defaultScreen();
	} catch {
		return defaultScreen();
	}
}

function persist(): void {
	try {
		const { level, weeks, filters, sort, dir } = screen;
		localStorage.setItem(
			STORE,
			JSON.stringify({ level, weeks, filters, sort, dir }),
		);
	} catch {
		// 私密視窗、封鎖儲存:不記也照常運作
	}
}

function nextId(): number {
	return Math.max(0, ...screen.filters.map((f) => f.id)) + 1;
}

function threshold(): number {
	return data.thresholds[screen.level] ?? 1000;
}

/** 把 {n} 換成目前選的週數 */
function withN(text: string): string {
	return text.replace("{n}", String(screen.weeks));
}

/** 大戶相關的欄位標題要帶出目前的門檻 */
function title(key: MetricKey): string {
	const m = METRICS[key];
	const short = withN(m.short);
	return LEVELLED.includes(key) ? `${short}(${threshold()}+)` : short;
}

function format(key: MetricKey, v: number | null): string {
	if (v === null) return "—";
	const m = METRICS[key];
	const text = m.digits === 0 ? thousands(Math.round(v)) : v.toFixed(m.digits);
	const unit = m.unit === "%" ? "%" : "";
	return `${m.signed && v > 0 ? "+" : ""}${text}${unit}`;
}

function tone(key: MetricKey, v: number | null): string {
	if (v === null || !METRICS[key].signed || v === 0) return "";
	return v > 0 ? "pos" : "neg";
}

// ---- 條件列 ----

function marketRow(
	f: Filter & { kind: "market" },
	check: string,
	remove: string,
): string {
	return `<li class="${f.on ? "" : "off"}">${check}<span class="what">市場</span>
  <select data-act="market" data-id="${f.id}" aria-label="市場">
   <option value="twse" ${f.market === "twse" ? "selected" : ""}>上市</option>
   <option value="otc" ${f.market === "otc" ? "selected" : ""}>上櫃</option>
  </select>${remove}</li>`;
}

function filterRow(f: Filter): string {
	const check = `<input type="checkbox" data-act="toggle" data-id="${f.id}" ${f.on ? "checked" : ""} aria-label="套用這個條件">`;
	const remove = `<button type="button" class="remove" data-act="remove" data-id="${f.id}" aria-label="移除這個條件">×</button>`;
	if (f.kind === "market") return marketRow(f, check, remove);
	const m = METRICS[f.metric];
	const label = LEVELLED.includes(f.metric)
		? `${withN(m.label)}(${threshold()} 張以上)`
		: withN(m.label);
	return `<li class="${f.on ? "" : "off"}">${check}<span class="what">${label}</span>
  <select data-act="op" data-id="${f.id}" aria-label="比較">
   <option value=">=" ${f.op === ">=" ? "selected" : ""}>≥</option>
   <option value="<=" ${f.op === "<=" ? "selected" : ""}>≤</option>
  </select>
  <input type="number" inputmode="decimal" step="${m.step}" value="${f.value}" data-act="value" data-id="${f.id}" aria-label="數值">
  <span class="unit">${m.unit}</span>${remove}</li>`;
}

function drawFilters(): void {
	el("filters").innerHTML = screen.filters.map(filterRow).join("");
}

/** 改一個條件。回傳要不要重畫條件列(數值框打字時不重畫,游標才不會跳掉) */
function edit(f: Filter, act: string, target: HTMLElement): boolean {
	const value = (target as HTMLInputElement | HTMLSelectElement).value;
	if (act === "remove") {
		screen.filters = screen.filters.filter((x) => x !== f);
	} else if (act === "toggle") {
		f.on = (target as HTMLInputElement).checked;
	} else if (act === "op" && f.kind === "metric") {
		f.op = value === "<=" ? "<=" : ">=";
	} else if (act === "value" && f.kind === "metric") {
		const v = Number(value);
		if (value.trim() === "" || !Number.isFinite(v)) return false;
		f.value = v;
		return false;
	} else if (act === "market" && f.kind === "market") {
		f.market = value === "otc" ? "otc" : "twse";
	}
	return true;
}

function onFilterEvent(event: Event): void {
	const target = event.target as HTMLElement;
	const act = target.dataset.act;
	const f = screen.filters.find((x) => x.id === Number(target.dataset.id));
	if (!act || !f) return;
	changed(edit(f, act, target));
}

// ---- 表格 ----

function rowHtml(r: HolderRow, rank: number, keys: MetricKey[]): string {
	const stale =
		r.day === latestDay ? "" : ` <small class="qual">${r.day.slice(5)}</small>`;
	const c = ctx(screen);
	const cells = keys
		.map((key) => {
			const v = METRICS[key].get(r, c);
			const extra = key === "close" ? stale : "";
			const strong = key === screen.sort ? " strong" : "";
			return `<td class="num ${tone(key, v)}${strong}">${format(key, v)}${extra}</td>`;
		})
		.join("");
	return `<tr>
 <td class="num rank">${rank}</td>
 <td><a class="quote" href="${yahooQuote(r.code, r.market)}" ${EXTERNAL}><b class="code">${escapeHtml(r.code)}</b> ${escapeHtml(r.name)}<small class="qual mk">${r.market === "otc" ? "櫃" : "市"}</small></a></td>
 ${cells}
</tr>`;
}

/** 用到還沒準備好的資料時說一聲,不然清單空了會以為是條件太嚴 */
function pendingNote(keys: MetricKey[]): string {
	const notes: string[] = [];
	if (!data.maReady && keys.some((k) => k === "gap5y" || k === "gap10y")) {
		notes.push(
			"長期均線的歷史資料還在準備中,用到五年線、十年線的條件暫時篩不出東西。",
		);
	}
	if (!data.flowsReady && keys.some((k) => FLOWS.includes(k))) {
		notes.push("法人與融資融券的資料還在準備中。");
	}
	if (data.prevDay === null && keys.includes("bigWeek")) {
		notes.push(
			"目前只有一週的集保資料,還沒有「比上週」;每週存一份之後就會有。",
		);
	}
	const have = Math.max(0, data.weeks.length - 1);
	if (keys.some((k) => WEEKLY.includes(k)) && screen.weeks > have) {
		notes.push(
			`過去幾週的集保資料還在往回補,目前最多只能看 ${have} 週;選 ${screen.weeks} 週的話,這幾欄暫時是空的。`,
		);
	}
	return notes.join(" ");
}

function draw(): void {
	const keys = columns(screen);
	el("head").innerHTML =
		`<th>#</th><th>股票</th>${keys.map((k) => `<th>${title(k)}</th>`).join("")}`;
	const items = run(data.rows, screen);
	el("rows").innerHTML = items
		.slice(0, shown)
		.map((r, i) => rowHtml(r, i + 1, keys))
		.join("");
	const active = screen.filters.filter((f) => f.on).length;
	el("count").textContent =
		`${active} 個條件 · 共 ${thousands(items.length)} 檔`;
	const more = el<HTMLButtonElement>("more");
	more.hidden = items.length <= shown;
	more.textContent = `再顯示 ${Math.min(PAGE, items.length - shown)} 檔`;
	const note = pendingNote(keys);
	el("pending").hidden = note === "";
	el("pending").textContent = note;
	for (const button of levelButtons()) {
		button.setAttribute(
			"aria-pressed",
			String(Number(button.dataset.level) === screen.level),
		);
	}
	el<HTMLSelectElement>("sort").value = screen.sort;
	el<HTMLSelectElement>("weeks").value = String(screen.weeks);
	el<HTMLSelectElement>("dir").value = screen.dir;
}

function changed(redrawFilters = true): void {
	shown = PAGE;
	if (redrawFilters) drawFilters();
	persist();
	draw();
}

/** 門檻按鈕。轉成陣列才能 for...of —— tsconfig 沒有開 DOM.Iterable */
function levelButtons(): HTMLButtonElement[] {
	return Array.from(
		document.querySelectorAll<HTMLButtonElement>("[data-level]"),
	);
}

function fillSelects(): void {
	const options = (Object.keys(METRICS) as MetricKey[])
		.map((k) => `<option value="${k}">${withN(METRICS[k].label)}</option>`)
		.join("");
	el("sort").innerHTML = options;
	el("add").innerHTML =
		`<option value="">+ 選一個項目…</option>${options}<option value="market">市場(上市 / 上櫃)</option>`;
}

function bindFilters(): void {
	const list = el("filters");
	list.addEventListener("change", onFilterEvent);
	list.addEventListener("input", (e) => {
		if ((e.target as HTMLElement).dataset.act === "value") onFilterEvent(e);
	});
	list.addEventListener("click", (e) => {
		if ((e.target as HTMLElement).dataset.act === "remove") onFilterEvent(e);
	});
	const add = el<HTMLSelectElement>("add");
	add.addEventListener("change", () => {
		const kind = add.value;
		add.value = "";
		if (kind !== "market" && !isMetric(kind)) return;
		screen.filters.push(newFilter(kind, nextId()));
		changed();
	});
	el("reset").addEventListener("click", () => {
		screen = { ...defaultScreen(), query: screen.query };
		changed();
	});
}

function bindControls(): void {
	for (const button of levelButtons()) {
		button.addEventListener("click", () => {
			screen.level = Number(button.dataset.level) as Level;
			changed();
		});
	}
	const weeks = el<HTMLSelectElement>("weeks");
	const have = Math.max(0, data.weeks.length - 1);
	weeks.innerHTML = Array.from({ length: MAX_WEEKS }, (_, i) => i + 1)
		.map(
			(n) =>
				`<option value="${n}">${n} 週${n > have ? "(資料補齊中)" : ""}</option>`,
		)
		.join("");
	weeks.addEventListener("change", () => {
		screen.weeks = Number(weeks.value);
		fillSelects();
		changed();
	});
	const sort = el<HTMLSelectElement>("sort");
	sort.addEventListener("change", () => {
		if (isMetric(sort.value)) screen.sort = sort.value;
		changed(false);
	});
	const dir = el<HTMLSelectElement>("dir");
	dir.addEventListener("change", () => {
		screen.dir = dir.value === "asc" ? "asc" : "desc";
		changed(false);
	});
	const search = el<HTMLInputElement>("q");
	search.addEventListener("input", () => {
		screen.query = search.value;
		shown = PAGE;
		draw();
	});
	el("more").addEventListener("click", () => {
		shown += PAGE;
		draw();
	});
}

function main(): void {
	data = parseHolders(HOLDERS_DATA);
	latestDay = data.rows.reduce((max, r) => (r.day > max ? r.day : max), "");
	el("m-day").textContent = data.day ?? "—";
	el("m-price").textContent = latestDay || "—";
	el("m-gen").textContent = data.generated;
	if (data.prevDay !== null)
		el("m-prev").textContent = `(比較 ${data.prevDay})`;
	screen = load();
	fillSelects();
	bindFilters();
	bindControls();
	drawFilters();
	draw();
}

main();
