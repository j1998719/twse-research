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
	backtested: number;
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
		backtested: number;
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
