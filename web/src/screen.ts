/**
 * 大戶頁的條件積木(#50):一張清單,條件可以新增、勾選、改數值、移除。
 *
 * 只有資料和規則,不碰畫面 —— 畫面在 holders-main.ts。每個條件就是
 * 「某個欄位 ≥ / ≤ 某個數」,或「市場 = 上市 / 上櫃」;勾選的條件全部成立
 * 才列出來(AND)。欄位算不出來(null)的股票不算符合 —— 不知道就是不知道,
 * 不當成 0。
 */

import { type HolderRow, inst5 } from "./holders.ts";

/** 從第 from 個級距加到最大那一級 */
function sumFrom(values: readonly number[], from: number): number {
	return values.slice(from).reduce((a, b) => a + b, 0);
}

/** 四捨五入到兩位。集保的佔比只到兩位,加總後的浮點尾巴不要顯示 */
function round2(value: number): number {
	return Math.round(value * 100) / 100;
}

/** 大戶門檻的級距:0 = 400 張以上 … 3 = 1000 張以上 */
export type Level = 0 | 1 | 2 | 3;

/** 算一個欄位需要知道的設定:大戶門檻,以及「過去 n 週」的 n(#49) */
export interface Ctx {
	level: Level;
	n: number;
}

/** 最新一週減 n 週前,從 level 那一級往上加總。任一週沒資料就是 null */
function weekDiff(weeks: readonly (number[] | null)[], c: Ctx): number | null {
	const now = weeks[0];
	const then = weeks[c.n];
	if (!now || !then) return null;
	return round2(sumFrom(now, c.level) - sumFrom(then, c.level));
}

/** 同一段期間的還原股價漲跌 % */
function priceChange(r: HolderRow, n: number): number | null {
	const now = r.weekClose[0];
	const then = r.weekClose[n];
	if (now == null || then == null || then <= 0) return null;
	return round2((now / then - 1) * 100);
}

export interface Metric {
	label: string;
	/** 顯示在數值後面 */
	unit: string;
	digits: number;
	/** 正負要上色、正數加 + 號 */
	signed: boolean;
	/** 新增這個條件時的預設 */
	op: Op;
	value: number;
	/** 數值輸入框一次加減多少 */
	step: number;
	/** 表格欄位的短標題 */
	short: string;
	get(row: HolderRow, c: Ctx): number | null;
}

export type Op = ">=" | "<=";

const big = (r: HolderRow, c: Ctx): number => round2(sumFrom(r.pct, c.level));

/** 可以拿來當條件、也可以排序的欄位。順序就是「新增條件」選單的順序 */
export const METRICS = {
	big: {
		label: "大戶持股比例",
		short: "大戶持股",
		unit: "%",
		digits: 2,
		signed: false,
		op: ">=",
		value: 50,
		step: 5,
		get: big,
	},
	bigWeek: {
		label: "大戶持股比上週",
		short: "比上週",
		unit: "百分點",
		digits: 2,
		signed: true,
		op: ">=",
		value: 0.5,
		step: 0.1,
		get: (r, c) =>
			r.prevPct === null
				? null
				: round2(sumFrom(r.pct, c.level) - sumFrom(r.prevPct, c.level)),
	},
	people: {
		label: "大戶人數",
		short: "大戶人數",
		unit: "人",
		digits: 0,
		signed: false,
		op: ">=",
		value: 10,
		step: 1,
		get: (r, c) => sumFrom(r.people, c.level),
	},
	bigChgN: {
		label: "大戶持股 {n} 週增減",
		short: "大戶 {n} 週",
		unit: "百分點",
		digits: 2,
		signed: true,
		op: ">=",
		value: 1,
		step: 0.5,
		get: (r, c) => weekDiff(r.weekPct, c),
	},
	peopleChgN: {
		label: "大戶人數 {n} 週增減",
		short: "人數 {n} 週",
		unit: "人",
		digits: 0,
		signed: true,
		op: ">=",
		value: 1,
		step: 1,
		get: (r, c) => weekDiff(r.weekPeople, c),
	},
	priceMoveN: {
		label: "{n} 週股價變動幅度(漲跌都算)",
		short: "{n} 週變動",
		unit: "%",
		digits: 2,
		signed: false,
		op: "<=",
		value: 5,
		step: 1,
		get: (r, c) => {
			const v = priceChange(r, c.n);
			return v === null ? null : Math.abs(v);
		},
	},
	priceChgN: {
		label: "{n} 週股價漲跌",
		short: "{n} 週漲跌",
		unit: "%",
		digits: 2,
		signed: true,
		op: "<=",
		value: 5,
		step: 1,
		get: (r, c) => priceChange(r, c.n),
	},
	gap10y: {
		label: "收盤價距十年線",
		short: "距十年線",
		unit: "%",
		digits: 1,
		signed: true,
		op: "<=",
		value: 0,
		step: 5,
		get: (r) => r.gap10y,
	},
	gap5y: {
		label: "收盤價距五年線",
		short: "距五年線",
		unit: "%",
		digits: 1,
		signed: true,
		op: "<=",
		value: 0,
		step: 5,
		get: (r) => r.gap5y,
	},
	inst5: {
		label: "三大法人近 5 日買賣超",
		short: "法人 5 日",
		unit: "張",
		digits: 0,
		signed: true,
		op: ">=",
		value: 500,
		step: 100,
		get: (r) => inst5(r),
	},
	foreign5: {
		label: "外資近 5 日買賣超",
		short: "外資 5 日",
		unit: "張",
		digits: 0,
		signed: true,
		op: ">=",
		value: 500,
		step: 100,
		get: (r) => r.foreign5,
	},
	trust5: {
		label: "投信近 5 日買賣超",
		short: "投信 5 日",
		unit: "張",
		digits: 0,
		signed: true,
		op: ">=",
		value: 100,
		step: 50,
		get: (r) => r.trust5,
	},
	dealer5: {
		label: "自營商近 5 日買賣超",
		short: "自營 5 日",
		unit: "張",
		digits: 0,
		signed: true,
		op: ">=",
		value: 100,
		step: 50,
		get: (r) => r.dealer5,
	},
	inst20: {
		label: "三大法人近 20 日買賣超",
		short: "法人 20 日",
		unit: "張",
		digits: 0,
		signed: true,
		op: ">=",
		value: 1000,
		step: 500,
		get: (r) => r.inst20,
	},
	marginChg5: {
		label: "融資近 5 日增減",
		short: "融資 5 日",
		unit: "張",
		digits: 0,
		signed: true,
		op: "<=",
		value: 0,
		step: 100,
		get: (r) => r.marginChg5,
	},
	shortRatio: {
		label: "券資比",
		short: "券資比",
		unit: "%",
		digits: 2,
		signed: false,
		op: ">=",
		value: 10,
		step: 1,
		get: (r) => r.shortRatio,
	},
	change: {
		label: "今天漲跌",
		short: "漲跌",
		unit: "%",
		digits: 2,
		signed: true,
		op: ">=",
		value: 0,
		step: 1,
		get: (r) => r.change,
	},
	lots: {
		label: "今天成交量",
		short: "成交張數",
		unit: "張",
		digits: 0,
		signed: false,
		op: ">=",
		value: 100,
		step: 100,
		get: (r) => r.lots,
	},
	close: {
		label: "收盤價",
		short: "收盤",
		unit: "元",
		digits: 2,
		signed: false,
		op: "<=",
		value: 100,
		step: 10,
		get: (r) => r.close,
	},
} satisfies Record<string, Metric>;

export type MetricKey = keyof typeof METRICS;

export function isMetric(key: string): key is MetricKey {
	return Object.hasOwn(METRICS, key);
}

/** 一個條件積木 */
export type Filter =
	| {
			id: number;
			on: boolean;
			kind: "metric";
			metric: MetricKey;
			op: Op;
			value: number;
	  }
	| { id: number; on: boolean; kind: "market"; market: "twse" | "otc" };

export interface Screen {
	level: Level;
	/** 「過去 n 週」的 n */
	weeks: number;
	filters: Filter[];
	sort: MetricKey;
	/** desc = 由大到小 */
	dir: "desc" | "asc";
	query: string;
}

/**
 * 打開就看到爸爸要的那組(#49、#53):過去 4 週千張大戶持股增加至少 0.5 百分點、
 * 同期股價變動不超過 5%,大戶增加最多的排前面。週資料還沒補到 4 週時,
 * 先用目前有的最多週數(maxWeeks),不要一打開就是空的。
 */
export function defaultScreen(maxWeeks: number = MAX_WEEKS): Screen {
	return {
		level: 3,
		weeks: Math.max(1, Math.min(4, maxWeeks)),
		filters: [
			{
				id: 1,
				on: true,
				kind: "metric",
				metric: "bigChgN",
				op: ">=",
				value: 0.5,
			},
			{
				id: 2,
				on: true,
				kind: "metric",
				metric: "priceMoveN",
				op: "<=",
				value: 5,
			},
		],
		sort: "bigChgN",
		dir: "desc",
		query: "",
	};
}

export function newFilter(kind: MetricKey | "market", id: number): Filter {
	if (kind === "market")
		return { id, on: true, kind: "market", market: "twse" };
	const m = METRICS[kind];
	return {
		id,
		on: true,
		kind: "metric",
		metric: kind,
		op: m.op,
		value: m.value,
	};
}

function passes(row: HolderRow, f: Filter, c: Ctx): boolean {
	if (!f.on) return true;
	if (f.kind === "market") return row.market === f.market;
	const v = METRICS[f.metric].get(row, c);
	if (v === null) return false;
	return f.op === ">=" ? v >= f.value : v <= f.value;
}

/** 代號或股名有包含就算 */
export function matches(row: HolderRow, query: string): boolean {
	const q = query.trim();
	return q === "" || row.code.includes(q) || row.name.includes(q);
}

export function ctx(screen: Screen): Ctx {
	return { level: screen.level, n: screen.weeks };
}

/** 符合所有勾選條件的股票,照排序欄位排好。排序欄位是 null 的一律放最後 */
export function run(rows: readonly HolderRow[], screen: Screen): HolderRow[] {
	const metric = METRICS[screen.sort];
	const c = ctx(screen);
	const keyed = rows
		.filter(
			(r) =>
				matches(r, screen.query) &&
				screen.filters.every((f) => passes(r, f, c)),
		)
		.map((r) => ({ r, v: metric.get(r, c) }));
	keyed.sort((a, b) => {
		if (a.v === null) return b.v === null ? 0 : 1;
		if (b.v === null) return -1;
		return screen.dir === "desc" ? b.v - a.v : a.v - b.v;
	});
	return keyed.map((k) => k.r);
}

/** 永遠顯示的欄位 */
export const BASE_COLUMNS: readonly MetricKey[] = ["close", "change", "big"];

/** 表格要顯示哪些欄位:固定的,加上勾選中的條件用到的,再加上排序欄位 */
export function columns(screen: Screen): MetricKey[] {
	const out: MetricKey[] = [...BASE_COLUMNS];
	for (const f of screen.filters) {
		if (f.on && f.kind === "metric" && !out.includes(f.metric))
			out.push(f.metric);
	}
	if (!out.includes(screen.sort)) out.push(screen.sort);
	return out;
}

/** n 最多幾週:最新一週往回 8 週(bigholders.json 每檔放 9 週) */
export const MAX_WEEKS = 8;

/** 從 localStorage 讀回來的東西不可信:欄位不對就整個用預設 */
export function restore(raw: unknown, maxWeeks: number = MAX_WEEKS): Screen {
	const fallback = defaultScreen(maxWeeks);
	if (typeof raw !== "object" || raw === null) return fallback;
	const s = raw as Partial<Screen>;
	const level = [0, 1, 2, 3].includes(Number(s.level))
		? (Number(s.level) as Level)
		: fallback.level;
	const sort =
		typeof s.sort === "string" && isMetric(s.sort) ? s.sort : fallback.sort;
	const dir = s.dir === "asc" || s.dir === "desc" ? s.dir : fallback.dir;
	const n = Number(s.weeks);
	const weeks =
		Number.isInteger(n) && n >= 1 && n <= MAX_WEEKS ? n : fallback.weeks;
	const filters = Array.isArray(s.filters)
		? s.filters.filter(validFilter)
		: fallback.filters;
	return { level, weeks, sort, dir, filters, query: "" };
}

function validFilter(f: unknown): f is Filter {
	if (typeof f !== "object" || f === null) return false;
	const x = f as Record<string, unknown>;
	if (typeof x.id !== "number" || typeof x.on !== "boolean") return false;
	if (x.kind === "market") return x.market === "twse" || x.market === "otc";
	return (
		x.kind === "metric" &&
		typeof x.metric === "string" &&
		isMetric(x.metric) &&
		(x.op === ">=" || x.op === "<=") &&
		typeof x.value === "number" &&
		Number.isFinite(x.value)
	);
}
