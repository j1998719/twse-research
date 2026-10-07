/**
 * report.json 的形狀。
 *
 * 這份定義跟 Python 端的 `build_report.py` 是一組的。
 * 兩邊各自定義欄位遲早會漂移 —— 改了 Python 的欄位名,網頁就會安靜地
 * 顯示 undefined。所以:
 *   1. Python 端有測試驗證輸出的欄位跟這裡一致
 *   2. 讀取時用 `require()` 顯性檢查,缺欄位直接報錯而不是顯示 undefined
 */

/** 一組報酬的統計量,對應 Python 的 summarise() */
export interface Summary {
	樣本數: number;
	"最小%": number;
	"四分之一%": number;
	"中位數%": number;
	"平均%": number;
	"四分之三%": number;
	"最大%": number;
	"標準差%": number;
	"勝率%": number;
}

/** 賺賠拆分,對應 Python 的 win_loss() */
export interface WinLoss {
	全部_樣本: number;
	"全部_平均%": number;
	"全部_中位數%": number;
	賺_筆數: number;
	賠_筆數: number;
	"勝率%": number;
	"賺_平均%": number;
	"賺_中位數%": number;
	"賠_平均%": number;
	"賠_中位數%": number;
	賺賠比: number;
	"期望值%": number;
}

/** 目前仍在處置期間的個股,附歷史同類事件的統計 */
export interface Current {
	/** 這一檔在哪個市場。同類統計是用同市場的樣本算的 */
	market: string;
	/** 同市場樣本不足而退回混合市場的統計 */
	histPooled: boolean;
	code: number;
	name: string;
	measure: string;
	condition: string;
	start: string;
	end: string;
	daysLeft: number;
	release: string;
	buyDay: string;
	/** t−6 在處置公告之前(新制 5 個營業日),買點往後推到公告後第一個交易日(#65) */
	buyLate: boolean;
	sellDay: string;
	/** 尚未到買點 / 持有中 / 今天賣出 / 已過賣點 */
	status: string;
	/** 出關日在已知交易日之後,用平日推算的 */
	projected: boolean;
	histN: number;
	histMedian: number;
	histWin: number;
	histEV: number;
	histWinAvg: number;
	histLossAvg: number;
	histWorst: number;
	/** 最新收盤價與日期(#44) */
	close: number | null;
	closeDay: string | null;
	/** 照 t−6 買、t−1 賣實際做的話:進出場價、日期、因漲跌停順延了幾天(#45) */
	entryPrice: number | null;
	entryDay: string | null;
	entryDeferred: number;
	exitPrice: number | null;
	exitDay: string | null;
	exitDeferred: number;
	/** 這一檔扣掉來回成本的報酬 %(不扣大盤)。還沒賣出就是用最新收盤算的 */
	tradeReturn: number | null;
	/** 尚未到買點 / 持有中 / 已賣出 / 漲停買不到… / 跌停賣不掉… */
	tradeState: string;
	/** 整串第一次處置前 20 日成交金額中位數(百萬元,#31)。算不出來是 null */
	w2: number | null;
	/** 符合 #30 的候選條件:第二次處置 × W2 ≥ 2 億 */
	candidate: boolean;
}

/** 候選和對照組的事件研究統計 */
export interface CandidateRow {
	label: string;
	n: number;
	median: number;
	win: number;
	/** 按月群集拔靴的 95% CI */
	low: number;
	high: number;
}

/** 組合回測的一種部位大小(或大盤) */
export interface PortfolioRow {
	label: string;
	annual: number;
	mdd: number;
	/** 最長多久沒創新高(日曆天) */
	underwater: number;
}

/** #30:研究中的候選。網頁上一定要跟「還沒驗證」的警語一起出現 */
export interface Candidate {
	/** 門檻(百萬元) */
	minW2: number;
	/** 組合回測的本金(元) */
	capital: number;
	/** 平均每月幾筆 */
	perMonth: number;
	rows: CandidateRow[];
	portfolio: PortfolioRow[];
}

export interface Period {
	name: string;
	n: number;
	median: number;
	win: number;
	p: number;
	bear: boolean;
}

export interface ExitRow {
	label: string;
	n: number;
	median: number;
	win: number;
	p: number;
}

export interface CapitalRow {
	/** null 是資金無限,"market" 是大盤對照列 */
	capital: number | null | "market";
	taken: number | null;
	total: number | null;
	ret: number;
	ann: number;
	days: number;
	bp: number;
	concurrent: number | null;
}

export interface Offender {
	code: number;
	name: string;
	total: number;
	second: number;
}

/** 以出關日對齊的價格路徑上的一個點 */
export interface PathPoint {
	t: number;
	excess: number;
	n: number;
}

export interface MarketCoverage {
	codes: number;
	punishes: number;
	studied: number;
}

export interface Report {
	generated: string;
	coverage: {
		from: string;
		to: string;
		notices: number;
		/** 注意股公告目前只有上市 —— 櫃買的端點還沒接 */
		noticesMarket: string;
		punishes: number;
		tradingDays: number;
		studied: number;
		codes?: number;
		/** 分市場的檔數、公告數、可回測事件數。上櫃的流動性和上市不同,
		 *  一個分不出市場的涵蓋率等於把兩個不同的東西當成一個 */
		markets?: Record<string, MarketCoverage>;
		/** 順延到最後還是成交不了的筆數(漲停一路買不到、跌停一路賣不掉) */
		dropped: { lookahead: number; fakeRelease: number; unfilled: number };
	};
	/** 價格路徑圖。本來寫死在 render.ts 裡,而且是上市那 951 筆算的 */
	path: PathPoint[];
	current: Current[];
	headline: Summary;
	winloss: WinLoss;
	winlossSecond: WinLoss;
	years: Period[];
	exits: ExitRow[];
	caps: CapitalRow[];
	afterRelease: Summary;
	rate: Record<string, number>;
	binomial: number;
	monthly: { m: string; n: number }[];
	offenders: Offender[];
	/** 超額報酬的分布,畫直方圖用 */
	dist: number[];
	candidate: Candidate;
}

/** report.json 最上層必須有的欄位。Python 端的測試會對照這份清單 */
export const REQUIRED_KEYS: readonly (keyof Report)[] = [
	"generated",
	"coverage",
	"path",
	"current",
	"headline",
	"winloss",
	"winlossSecond",
	"years",
	"exits",
	"caps",
	"afterRelease",
	"rate",
	"binomial",
	"monthly",
	"offenders",
	"dist",
	"candidate",
];

/**
 * 缺欄位就直接報錯,不要讓畫面顯示 undefined。
 *
 * 顯示 undefined 的問題是它看起來像「這個數字剛好沒有」,
 * 而不是「程式壞了」—— 那種錯誤會留在頁面上很久沒人發現。
 */
export function parseReport(raw: unknown): Report {
	if (typeof raw !== "object" || raw === null) {
		throw new TypeError("report.json 不是物件");
	}
	const missing = REQUIRED_KEYS.filter((key) => !(key in raw));
	if (missing.length > 0) {
		throw new TypeError(`report.json 缺少欄位:${missing.join("、")}`);
	}
	return raw as Report;
}
