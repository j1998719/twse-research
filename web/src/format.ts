/** 顯示用的格式化。集中在一處,表格和卡片才不會各寫各的。 */

/** 百分比,正數加正號。null 顯示破折號而不是 0 —— 兩者意思不同 */
export function pct(value: number | null | undefined, digits = 2): string {
	if (value === null || value === undefined) return "—";
	return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

/** 正負決定顏色。台股慣例:紅漲綠跌 */
export function sign(value: number | null | undefined): string {
	if (value === null || value === undefined) return "";
	return value < 0 ? "neg" : "pos";
}

/** p 值。太小的話寫成 <0.0001,不要顯示一串零 */
export function pValue(value: number | null | undefined): string {
	if (value === null || value === undefined) return "—";
	return value < 0.0001 ? "<0.0001" : value.toFixed(4);
}

export function thousands(value: number): string {
	return value.toLocaleString("en-US");
}
