/**
 * 大戶頁的「我的條件」:最多 10 組存好的條件,一組一顆按鈕,點了就套用(#53、#56)。
 *
 * 只存在這台裝置的瀏覽器裡。讀回來的東西一律重新驗證 —— 每一格的條件交給
 * screen.ts 的 restore(),壞掉的格子當成空的,不讓一格壞資料弄壞整頁。
 */

import { restore, type Screen } from "./screen.ts";

export const SLOTS = 10;
/** 名字最多幾個字。畫面上的選單要放得下 */
export const NAME_MAX = 30;
/** 第 1 格預先放的那組 */
export const DAD_NAME = "大戶增加、股價沒動";
/** #53 時的名字。網頁就是給爸爸用的,不用寫「爸爸」(#56),讀到舊名字就換掉 */
const OLD_DAD_NAME = "爸爸:大戶增加、股價沒動";

export interface Preset {
	name: string;
	screen: Screen;
}

/** 長度固定 SLOTS,空格是 null */
export type Presets = (Preset | null)[];

export function cleanName(name: string, slot: number): string {
	const trimmed = name.trim().slice(0, NAME_MAX);
	return trimmed || `條件 ${slot + 1}`;
}

/** 第一次打開:第 1 格是爸爸的條件,其他是空的 */
export function starterPresets(dad: Screen): Presets {
	const out: Presets = Array.from({ length: SLOTS }, () => null);
	out[0] = { name: DAD_NAME, screen: dad };
	return out;
}

export function restorePresets(
	raw: unknown,
	dad: Screen,
	maxWeeks: number,
): Presets {
	if (!Array.isArray(raw)) return starterPresets(dad);
	return Array.from({ length: SLOTS }, (_, i) => {
		const x: unknown = raw[i];
		if (typeof x !== "object" || x === null) return null;
		const item = x as { name?: unknown; screen?: unknown };
		if (typeof item.screen !== "object" || item.screen === null) return null;
		const given = typeof item.name === "string" ? item.name : "";
		const name = given === OLD_DAD_NAME ? DAD_NAME : given;
		return { name: cleanName(name, i), screen: restore(item.screen, maxWeeks) };
	});
}

/** 存進 localStorage 的形狀:搜尋字不存 */
export function serialise(presets: Presets): unknown {
	return presets.map((p) => {
		if (!p) return null;
		const { big, weeks, filters, sort, dir } = p.screen;
		return { name: p.name, screen: { big, weeks, filters, sort, dir } };
	});
}

/** 存一份「目前的條件」的複本,之後再改畫面不會動到存好的那格 */
export function snapshot(screen: Screen): Screen {
	// 不用 structuredClone:Safari 15.4 以前沒有,爸爸的手機不一定夠新
	return JSON.parse(JSON.stringify({ ...screen, query: "" })) as Screen;
}

/** 比較兩組條件。條件積木的 id 只是畫面用的編號,不算 */
function essence(screen: Screen): string {
	const { big, weeks, filters, sort, dir } = screen;
	const blocks = filters.map(({ id: _id, ...rest }) => rest);
	return JSON.stringify({ big, weeks, filters: blocks, sort, dir });
}

/** 目前畫面跟哪一組一模一樣。沒有就是 -1 */
export function matching(presets: Presets, screen: Screen): number {
	const now = essence(screen);
	return presets.findIndex((p) => p !== null && essence(p.screen) === now);
}

/** 第一個空格。滿了是 -1 */
export function firstEmpty(presets: Presets): number {
	return presets.indexOf(null);
}
