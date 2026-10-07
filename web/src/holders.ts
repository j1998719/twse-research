/**
 * bigholders.json 的形狀,以及從它算出「某個門檻以上的大戶」。
 *
 * 跟 report.ts 同一個做法:Python 端的 `build_bigholders.py` 寫、這裡讀,
 * `REQUIRED_KEYS` 是單一來源,`tests/test_holders_contract.py` 會對照。
 */

/** 一檔股票。pct / people / prevPct 是 400、600、800、1000 張以上四個級距,由小到大 */
export interface HolderRow {
	code: string;
	name: string;
	/** twse 或 otc */
	market: string;
	/** 收盤價的日期。停牌的股票會比其他檔早 */
	day: string;
	close: number;
	/** 比前一個交易日漲跌幾 %。只有一天行情時是 null */
	change: number | null;
	/** 成交張數 */
	lots: number | null;
	/** 總股東人數 */
	holders: number | null;
	pct: number[];
	people: number[];
	/** 上一週的同四個級距。沒有上一份快照、或上週沒有這一檔時是 null */
	prevPct: number[] | null;
	/** 五年線、十年線(還原股價、1,200 / 2,400 個交易日)。歷史不夠長是 null */
	ma5y: number | null;
	ma10y: number | null;
	/** 收盤價比均線高或低幾 %,負的就是跌破 */
	gap5y: number | null;
	gap10y: number | null;
	/** 外資、投信、自營商近 5 個交易日買賣超(張),正的是買超 */
	foreign5: number | null;
	trust5: number | null;
	dealer5: number | null;
	/** 三大法人合計近 20 個交易日(張) */
	inst20: number | null;
	/** 融資、融券餘額(張)與 5 個交易日的增減 */
	margin: number | null;
	marginChg5: number | null;
	short: number | null;
	shortChg5: number | null;
	/** 券資比 % = 融券 / 融資 */
	shortRatio: number | null;
}

export interface Holders {
	generated: string;
	/** 集保快照的資料日期 */
	day: string | null;
	prevDay: string | null;
	/** 跟四個級距一一對應的門檻(張) */
	thresholds: number[];
	/** 還原股價算好了沒。false 時均線區塊顯示「準備中」,不拿原始收盤頂替 */
	maReady: boolean;
	/** 法人與融資融券資料到了沒 */
	flowsReady: boolean;
	rows: HolderRow[];
}

/** bigholders.json 最上層必須有的欄位。Python 端的測試會對照這份清單 */
export const REQUIRED_KEYS: readonly (keyof Holders)[] = [
	"generated",
	"day",
	"prevDay",
	"thresholds",
	"maReady",
	"flowsReady",
	"rows",
];

export function parseHolders(raw: unknown): Holders {
	if (typeof raw !== "object" || raw === null) {
		throw new TypeError("bigholders.json 不是物件");
	}
	const missing = REQUIRED_KEYS.filter((key) => !(key in raw));
	if (missing.length > 0) {
		throw new TypeError(`bigholders.json 缺少欄位:${missing.join("、")}`);
	}
	return raw as Holders;
}

/** 從第 from 個級距加到最大那一級 */
function sumFrom(values: readonly number[], from: number): number {
	return values.slice(from).reduce((a, b) => a + b, 0);
}

/** 某個門檻以上的大戶,已經加總好,畫面直接用 */
export interface Big {
	row: HolderRow;
	pct: number;
	people: number;
	/** 比上週多幾個百分點。沒有上週可比是 null —— 不是 0 */
	delta: number | null;
}

/** 四捨五入到兩位。集保的佔比本來就只到兩位,加總後的浮點尾巴不要顯示 */
function round2(value: number): number {
	return Math.round(value * 100) / 100;
}

export function bigHolders(rows: readonly HolderRow[], level: number): Big[] {
	return rows.map((row) => ({
		row,
		pct: round2(sumFrom(row.pct, level)),
		people: sumFrom(row.people, level),
		delta:
			row.prevPct === null
				? null
				: round2(sumFrom(row.pct, level) - sumFrom(row.prevPct, level)),
	}));
}

export type SortKey = "pct" | "delta" | "people" | "change";

/** 由大到小。null 一律排最後,不要因為缺資料就被當成 0 排在中間 */
export function sortBig(items: Big[], key: SortKey): Big[] {
	const value = (b: Big): number | null =>
		key === "change" ? b.row.change : b[key];
	return [...items].sort((a, b) => {
		const x = value(a);
		const y = value(b);
		if (x === null) return y === null ? 0 : 1;
		if (y === null) return -1;
		return y - x;
	});
}

/** 代號或股名有包含就算 */
export function matches(row: HolderRow, query: string): boolean {
	const q = query.trim();
	return q === "" || row.code.includes(q) || row.name.includes(q);
}

/** 長期均線篩選:勾了哪幾條線 */
export interface MaFilter {
	ma5y: boolean;
	ma10y: boolean;
}

/**
 * 跌破勾選的「每一條」均線才算(Jordan 2026-10-06:勾兩個就是兩條都跌破)。
 * 那條線算不出來(歷史不夠長)的股票不列 —— 不知道就是不知道,不當成跌破。
 * 一條都沒勾就是空的,而不是全部列出來。
 */
export function belowMa(
	rows: readonly HolderRow[],
	filter: MaFilter,
): HolderRow[] {
	if (!filter.ma5y && !filter.ma10y) return [];
	const below = (gap: number | null): boolean => gap !== null && gap < 0;
	const picked = rows.filter(
		(r) =>
			(!filter.ma5y || below(r.gap5y)) && (!filter.ma10y || below(r.gap10y)),
	);
	// 跌得最深的排前面。兩條都勾時用十年線排
	const key = (r: HolderRow): number =>
		(filter.ma10y ? r.gap10y : r.gap5y) ?? 0;
	return picked.sort((a, b) => key(a) - key(b));
}

export type FlowKey =
	| "inst5"
	| "foreign5"
	| "trust5"
	| "inst20"
	| "marginChg5"
	| "shortRatio";

/** 三大法人近 5 日合計 */
export function inst5(row: HolderRow): number | null {
	if (row.foreign5 === null || row.trust5 === null || row.dealer5 === null) {
		return null;
	}
	return row.foreign5 + row.trust5 + row.dealer5;
}

/** 籌碼總覽的排序:由大到小,null 排最後 */
export function sortFlows(
	rows: readonly HolderRow[],
	key: FlowKey,
): HolderRow[] {
	const value = (r: HolderRow): number | null =>
		key === "inst5" ? inst5(r) : r[key];
	return [...rows].sort((a, b) => {
		const x = value(a);
		const y = value(b);
		if (x === null) return y === null ? 0 : 1;
		if (y === null) return -1;
		return y - x;
	});
}
