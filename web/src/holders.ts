/**
 * bigholders.json 的形狀,以及從它算出「某個門檻以上的大戶」。
 *
 * 跟 report.ts 同一個做法:Python 端的 `build_bigholders.py` 寫、這裡讀,
 * `REQUIRED_KEYS` 是單一來源,`tests/test_holders_contract.py` 會對照。
 */

/** 一檔股票。pct / people / prevPct 是集保第 1–15 級,由小到大(#55) */
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
	/** 集保總股數。「佔市值比例」的門檻要用它換成張數 */
	shares: number | null;
	pct: number[];
	people: number[];
	/** 上一週的同 15 個級距。沒有上一份快照、或上週沒有這一檔時是 null */
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
	/** 每週的 15 級佔比、人數、還原收盤,順序同 Holders.weeks(新的在前)。那週沒資料是 null(#49) */
	weekPct: (number[] | null)[];
	weekPeople: (number[] | null)[];
	weekClose: (number | null)[];
}

export interface Holders {
	generated: string;
	/** 集保快照的資料日期 */
	day: string | null;
	prevDay: string | null;
	/** 跟 15 個級距一一對應:每一級的下限(張) */
	thresholds: number[];
	/** 還原股價算好了沒。false 時均線區塊顯示「準備中」,不拿原始收盤頂替 */
	maReady: boolean;
	/** 法人與融資融券資料到了沒 */
	flowsReady: boolean;
	/** 週次日期,新的在前 */
	weeks: string[];
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
	"weeks",
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

/** 三大法人近 5 日合計 */
export function inst5(row: HolderRow): number | null {
	if (row.foreign5 === null || row.trust5 === null || row.dealer5 === null) {
		return null;
	}
	return row.foreign5 + row.trust5 + row.dealer5;
}
