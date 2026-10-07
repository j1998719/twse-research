/** 連到外部網站。處置股卡片和大戶頁共用(#44、#46),市場別只在這裡判斷一次。 */

/** Yahoo 股市的個股頁。上市是 .TW、上櫃是 .TWO */
export function yahooQuote(code: string | number, market: string): string {
	const suffix = market === "otc" ? "TWO" : "TW";
	return `https://tw.stock.yahoo.com/quote/${encodeURIComponent(String(code))}.${suffix}`;
}

/** 在新分頁打開的連結屬性。noopener:新分頁拿不到這一頁的 window */
export const EXTERNAL = 'target="_blank" rel="noopener noreferrer"';
