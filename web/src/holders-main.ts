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
	cleanName,
	firstEmpty,
	matching,
	type Preset,
	type Presets,
	restorePresets,
	SLOTS,
	serialise,
	snapshot,
	starterPresets,
} from "./presets.ts";
import {
	BIG_DEFAULTS,
	type Big,
	columns,
	ctx,
	defaultScreen,
	type Filter,
	isMetric,
	LOT_EDGES,
	MAX_WEEKS,
	METRICS,
	type MetricKey,
	newFilter,
	restore,
	run,
	type Screen,
	tier,
} from "./screen.ts";

declare const HOLDERS_DATA: unknown;

/** 一次畫幾列。全市場一千多檔一次畫完,手機會卡 */
const PAGE = 100;
/** 記住自己堆的條件。只在這個瀏覽器,換裝置不會跟著走 */
const STORE = "holders.screen.v2";
/** 10 個儲存格(#53)。同樣只在這個瀏覽器 */
const PRESET_STORE = "holders.presets.v1";
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
let presets: Presets = [];
/** 名稱輸入框現在是在存新的、還是在改名;null = 收起來 */
let formMode: "new" | "rename" | null = null;
/** 剛刪掉的那組,可以復原 */
let undo: { slot: number; preset: Preset } | null = null;

/** 週資料目前最多能看幾週。預設和讀回來的條件都不要超過它 */
function availableWeeks(): number {
	return Math.max(1, Math.min(MAX_WEEKS, data.weeks.length - 1));
}

function load(): Screen {
	try {
		const raw = localStorage.getItem(STORE);
		return raw
			? restore(JSON.parse(raw), MAX_WEEKS)
			: defaultScreen(availableWeeks());
	} catch {
		return defaultScreen(availableWeeks());
	}
}

function loadPresets(): Presets {
	const dad = defaultScreen(availableWeeks());
	try {
		const raw = localStorage.getItem(PRESET_STORE);
		return raw
			? restorePresets(JSON.parse(raw), dad, MAX_WEEKS)
			: starterPresets(dad);
	} catch {
		return starterPresets(dad);
	}
}

function savePresets(): boolean {
	try {
		localStorage.setItem(PRESET_STORE, JSON.stringify(serialise(presets)));
		return true;
	} catch {
		return false;
	}
}

function persist(): void {
	try {
		const { big, weeks, filters, sort, dir } = screen;
		localStorage.setItem(
			STORE,
			JSON.stringify({ big, weeks, filters, sort, dir }),
		);
	} catch {
		// 私密視窗、封鎖儲存:不記也照常運作
	}
}

function nextId(): number {
	return Math.max(0, ...screen.filters.map((f) => f.id)) + 1;
}

/** 金額用萬元存;一萬萬以上改用億 */
function money(wan: number): string {
	return wan >= 10000 ? `${wan / 10000} 億元` : `${thousands(wan)} 萬元`;
}

/** 條件列用的完整說法 */
function bigLabel(big: Big): string {
	if (big.by === "lots") return `${big.value} 張以上`;
	if (big.by === "amount") return `持股 ${money(big.value)}以上`;
	return `持股佔公司 ${big.value}% 以上`;
}

/** 欄位標題用的短說法 */
function bigShort(big: Big): string {
	if (big.by === "lots") return `${big.value}+`;
	if (big.by === "amount")
		return `≥${money(big.value).replace(" ", "").replace("元", "")}`;
	return `≥${big.value}%`;
}

/** 把 {n} 換成目前選的週數 */
function withN(text: string): string {
	return text.replace("{n}", String(screen.weeks));
}

/** 大戶相關的欄位標題要帶出目前的門檻 */
function title(key: MetricKey): string {
	const m = METRICS[key];
	const short = withN(m.short);
	return LEVELLED.includes(key) ? `${short}(${bigShort(screen.big)})` : short;
}

function format(key: MetricKey, v: number | null): string {
	if (v === null) return "—";
	// 0.00% 看起來像沒資料;台股看盤的說法是「平盤」(#54)
	if (key === "change" && v === 0) return "平盤";
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
		? `${withN(m.label)}(${bigLabel(screen.big)})`
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
			const extra = key === "close" ? stale : key === "big" ? usedTier(r) : "";
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

/** 金額、比例模式下,這一檔實際用的是幾張以上(#55) */
function usedTier(r: HolderRow): string {
	if (screen.big.by === "lots") return "";
	const t = tier(r, screen.big);
	if (t === null) return "";
	const edge = LOT_EDGES[t.index] ?? 0;
	const text = edge === 0 ? "全部" : `${thousands(edge)}張+`;
	return `<small class="tier">${text}${t.capped ? " 最高級" : ""}</small>`;
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
	drawBig();
	el<HTMLSelectElement>("sort").value = screen.sort;
	el<HTMLSelectElement>("weeks").value = String(screen.weeks);
	el<HTMLSelectElement>("dir").value = screen.dir;
}

function changed(redrawFilters = true): void {
	shown = PAGE;
	if (redrawFilters) drawFilters();
	persist();
	draw();
	// 改了條件,亮著的那組可能就不一樣了
	drawPresets();
}

/** 張數按鈕。轉成陣列才能 for...of —— tsconfig 沒有開 DOM.Iterable */
function lotButtons(): HTMLButtonElement[] {
	return Array.from(
		document.querySelectorAll<HTMLButtonElement>("[data-lots]"),
	);
}

const BIG_UNITS: Record<Big["by"], string> = {
	lots: "張",
	amount: "萬元",
	ratio: "%",
};

/** 大戶定義那一列:張數用按鈕,金額和比例用輸入框 */
function drawBig(): void {
	const { by, value } = screen.big;
	el<HTMLSelectElement>("big-by").value = by;
	el("big-lots").hidden = by !== "lots";
	el("big-free").hidden = by === "lots";
	el("big-note").hidden = by === "lots";
	el("big-unit").textContent = BIG_UNITS[by];
	const input = el<HTMLInputElement>("big-value");
	input.step = by === "ratio" ? "0.1" : "1000";
	if (by !== "lots" && document.activeElement !== input)
		input.value = String(value);
	for (const button of lotButtons()) {
		button.setAttribute(
			"aria-pressed",
			String(by === "lots" && Number(button.dataset.lots) === value),
		);
	}
}

function bindBig(): void {
	for (const button of lotButtons()) {
		button.addEventListener("click", () => {
			screen.big = { by: "lots", value: Number(button.dataset.lots) };
			changed();
		});
	}
	const by = el<HTMLSelectElement>("big-by");
	by.addEventListener("change", () => {
		const next =
			by.value === "amount" || by.value === "ratio" ? by.value : "lots";
		screen.big = { by: next, value: BIG_DEFAULTS[next] };
		changed();
	});
	const input = el<HTMLInputElement>("big-value");
	input.addEventListener("input", () => {
		const v = Number(input.value);
		if (input.value.trim() === "" || !Number.isFinite(v) || v <= 0) return;
		screen.big = { by: screen.big.by, value: v };
		changed();
	});
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
}

function bindControls(): void {
	bindBig();
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

// ---- 我的條件(#56):一組一顆按鈕,點了就套用 ----

/** 狀態列的一句話。html 只用在自己組出來的字串(名字都先 escape 過) */
function say(html: string): void {
	el("p-msg").innerHTML = html;
}

function drawPresets(): void {
	const active = matching(presets, screen);
	el("p-list").innerHTML = presets
		.map((p, i) =>
			p
				? `<button type="button" class="chip" data-slot="${i}" aria-pressed="${i === active}">${escapeHtml(p.name)}</button>`
				: "",
		)
		.join("");
	const full = firstEmpty(presets) === -1;
	const add = el<HTMLButtonElement>("p-new");
	add.disabled = full;
	add.textContent = full ? `最多 ${SLOTS} 組` : "+ 存目前的條件";
	add.hidden = formMode !== null;
	el("p-form").hidden = formMode === null;
	el("p-tools").hidden = active === -1 || formMode !== null;
}

function stored(ok: boolean, done: string): string {
	return ok ? done : `${done}(這個瀏覽器不能儲存,重新整理後會不見)`;
}

function openForm(mode: "new" | "rename", name: string): void {
	formMode = mode;
	say("");
	drawPresets();
	const input = el<HTMLInputElement>("p-name");
	input.value = name;
	input.focus();
	input.select();
}

function closeForm(): void {
	formMode = null;
	drawPresets();
}

/** 存新的,或把目前亮著的那組改名 */
function submitForm(): void {
	const typed = el<HTMLInputElement>("p-name").value;
	if (formMode === "rename") {
		const at = matching(presets, screen);
		const p = presets[at];
		if (p) {
			p.name = cleanName(typed || p.name, at);
			say(stored(savePresets(), `已改名為「${escapeHtml(p.name)}」`));
		}
	} else {
		const at = firstEmpty(presets);
		if (at !== -1) {
			const name = cleanName(typed, at);
			presets[at] = { name, screen: snapshot(screen) };
			say(stored(savePresets(), `已存成「${escapeHtml(name)}」`));
		}
	}
	formMode = null;
	drawPresets();
}

function removeActive(): void {
	const at = matching(presets, screen);
	const p = presets[at];
	if (!p) return;
	presets[at] = null;
	undo = { slot: at, preset: p };
	const ok = savePresets();
	drawPresets();
	say(
		`${stored(ok, `已刪除「${escapeHtml(p.name)}」`)} <button type="button" class="link" id="p-undo">復原</button>`,
	);
}

function bindPresets(): void {
	el("p-list").addEventListener("click", (e) => {
		const at = Number((e.target as HTMLElement).dataset.slot);
		const p = presets[at];
		if (!p) return;
		screen = { ...snapshot(p.screen), query: screen.query };
		formMode = null;
		say("");
		changed();
	});
	el("p-new").addEventListener("click", () => openForm("new", ""));
	el("p-rename").addEventListener("click", () =>
		openForm("rename", presets[matching(presets, screen)]?.name ?? ""),
	);
	el("p-delete").addEventListener("click", removeActive);
	el("p-cancel").addEventListener("click", closeForm);
	el("p-form").addEventListener("submit", (e) => {
		e.preventDefault();
		submitForm();
	});
	el("p-name").addEventListener("keydown", (e) => {
		if (e.key === "Escape") closeForm();
	});
	el("p-msg").addEventListener("click", (e) => {
		if ((e.target as HTMLElement).id !== "p-undo" || !undo) return;
		presets[undo.slot] = undo.preset;
		const name = undo.preset.name;
		undo = null;
		say(stored(savePresets(), `已復原「${escapeHtml(name)}」`));
		drawPresets();
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
	presets = loadPresets();
	// 格數不對、或全部刪光了:補回預設那組。拿掉「恢復預設」之後(#57),
	// 這是回到預設的唯一路徑
	if (presets.length !== SLOTS || presets.every((p) => p === null))
		presets = starterPresets(defaultScreen(availableWeeks()));
	fillSelects();
	bindFilters();
	bindControls();
	bindPresets();
	drawPresets();
	drawFilters();
	draw();
}

main();
