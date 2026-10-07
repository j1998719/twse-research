/**
 * 大戶頁的「我的條件」:10 個儲存格,每格一組條件,可以改名(#53)。
 *
 * 只存在這台裝置的瀏覽器裡。讀回來的東西一律重新驗證 —— 每一格的條件交給
 * screen.ts 的 restore(),壞掉的格子當成空的,不讓一格壞資料弄壞整頁。
 */

import { restore, type Screen } from "./screen.ts";

export const SLOTS = 10;
/** 名字最多幾個字。畫面上的選單要放得下 */
export const NAME_MAX = 30;
/** 第 1 格預先放的那組 */
export const DAD_NAME = "爸爸:大戶增加、股價沒動";

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
		const name = typeof item.name === "string" ? item.name : "";
		return { name: cleanName(name, i), screen: restore(item.screen, maxWeeks) };
	});
}

/** 存進 localStorage 的形狀:搜尋字不存 */
export function serialise(presets: Presets): unknown {
	return presets.map((p) => {
		if (!p) return null;
		const { level, weeks, filters, sort, dir } = p.screen;
		return { name: p.name, screen: { level, weeks, filters, sort, dir } };
	});
}

/** 存一份「目前的條件」的複本,之後再改畫面不會動到存好的那格 */
export function snapshot(screen: Screen): Screen {
	// 不用 structuredClone:Safari 15.4 以前沒有,爸爸的手機不一定夠新
	return JSON.parse(JSON.stringify({ ...screen, query: "" })) as Screen;
}
