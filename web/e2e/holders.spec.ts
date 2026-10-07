/**
 * 大戶持股頁(holders.html)。假資料四檔,見 fixtures/bigholders.json:
 *
 * - 3661 世芯 4180 元:4 週千張大戶 +1.76、股價 +1.95%
 * - 6152 百一 18.95 元:+0.90、+2.43%
 * - 1110 東泥 14.35 元:平盤,大戶只 +0.38
 * - 2330 台積電 2585 元:大戶 +1.77,但股價 +12.4%
 */

import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { expect, type Page, test } from "@playwright/test";
import { BUILT } from "./setup.ts";

const PAGE = pathToFileURL(join(BUILT, "holders.html")).href;
const SCREENS = join(BUILT, "..", "screens");

/** 頁面上的 JS 錯誤都收起來,每個測試最後確認是空的 */
let errors: string[] = [];

test.beforeEach(async ({ page }) => {
	errors = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => {
		if (m.type() === "error") errors.push(m.text());
	});
	await page.goto(PAGE);
	await page.evaluate(() => localStorage.clear());
	await page.reload();
});

test.afterEach(() => {
	expect(errors).toEqual([]);
});

async function shot(page: Page, name: string): Promise<void> {
	const project = test.info().project.name;
	await page.screenshot({
		path: join(SCREENS, `${project}-${name}.png`),
		fullPage: true,
	});
}

/** 表格每一列的代號,照畫面順序 */
async function codes(page: Page): Promise<string[]> {
	return page.locator("#rows .code").allTextContents();
}

/** 某一檔「大戶持股」那格的文字 */
function bigCell(page: Page, code: string) {
	const row = page.locator("#rows tr", {
		has: page.locator(".code", { hasText: code }),
	});
	const col = page.locator("#head th", { hasText: "大戶持股(" });
	return { row, col };
}

async function bigText(page: Page, code: string): Promise<string> {
	const { row } = bigCell(page, code);
	const heads = await page.locator("#head th").allTextContents();
	const at = heads.findIndex((h) => h.startsWith("大戶持股("));
	return (await row.locator("td").nth(at).innerText()).replace(/\s+/g, " ");
}

test("預設是爸爸的條件:大戶增加、股價沒動", async ({ page }) => {
	await expect(page.locator("[data-lots='1000']")).toHaveAttribute(
		"aria-pressed",
		"true",
	);
	expect(await codes(page)).toEqual(["3661", "6152"]);
	await expect(page.locator("#head th").nth(4)).toHaveText("大戶持股(1000+)");
	await shot(page, "default");
});

test("「股票」標題跟股名一樣靠左", async ({ page }) => {
	const align = await page
		.locator("#head th")
		.nth(1)
		.evaluate((th) => getComputedStyle(th).textAlign);
	expect(align).toBe("left");
});

test("漲跌是 0 顯示平盤(#54)", async ({ page }) => {
	await page.locator("#filters input[type=checkbox]").first().uncheck();
	await page.locator("#filters input[type=checkbox]").last().uncheck();
	const row = page.locator("#rows tr", {
		has: page.locator(".code", { hasText: "1110" }),
	});
	await expect(row).toContainText("平盤");
});

test("持股金額:換算成張數後往上取級距(#55)", async ({ page }) => {
	await page.selectOption("#big-by", "amount");
	await expect(page.locator("#big-lots")).toBeHidden();
	await expect(page.locator("#big-value")).toHaveValue("10000");
	await expect(page.locator("#big-unit")).toHaveText("萬元");
	await expect(page.locator("#head th", { hasText: "大戶持股(" })).toHaveText(
		"大戶持股(≥1億)",
	);
	// 1 億 / 4180 元 = 23.9 張 → 30 張那級;1 億 / 18.95 元 = 5,277 張 → 超過最高級
	expect(await bigText(page, "3661")).toContain("30張+");
	expect(await bigText(page, "6152")).toContain("1,000張+ 最高級");
	await shot(page, "amount");

	await page.fill("#big-value", "5000");
	await expect(page.locator("#head th", { hasText: "大戶持股(" })).toHaveText(
		"大戶持股(≥5,000萬)",
	);
	// 5000 萬 / 4180 = 12.0 張 → 15 張那級
	expect(await bigText(page, "3661")).toContain("15張+");
});

test("佔市值比例(#55)", async ({ page }) => {
	await page.selectOption("#big-by", "ratio");
	await expect(page.locator("#big-unit")).toHaveText("%");
	// 0.5% × 86,349 張 = 431.7 → 600 張;0.5% × 167,738 張 = 838.7 → 1000 張(沒超過)
	expect(await bigText(page, "3661")).toContain("600張+");
	expect(await bigText(page, "6152")).toMatch(/1,000張\+$/);
});

test("「≥ 數字 單位」排在同一行", async ({ page }) => {
	await page.selectOption("#big-by", "amount");
	const tops = await page
		.locator("#big-free > *")
		.evaluateAll((els) =>
			els.map((e) => Math.round(e.getBoundingClientRect().top)),
		);
	const input = await page.locator("#big-value").boundingBox();
	const unit = await page.locator("#big-unit").boundingBox();
	expect(tops.length).toBeGreaterThan(0);
	// 單位的垂直中心落在輸入框的高度範圍裡,就是同一行
	expect(unit && input && unit.y + unit.height / 2).toBeGreaterThan(
		input?.y ?? 0,
	);
	expect(unit && input && unit.y + unit.height / 2).toBeLessThan(
		(input?.y ?? 0) + (input?.height ?? 0),
	);
});

test("切回張數按鈕", async ({ page }) => {
	await page.selectOption("#big-by", "amount");
	await page.selectOption("#big-by", "lots");
	await page.click("[data-lots='400']");
	await expect(page.locator("#big-free")).toBeHidden();
	await expect(page.locator("#head th", { hasText: "大戶持股(" })).toHaveText(
		"大戶持股(400+)",
	);
});

test("舊版存的 level 讀得回來", async ({ page }) => {
	await page.evaluate(() =>
		localStorage.setItem(
			"holders.screen.v2",
			JSON.stringify({
				level: 1,
				weeks: 4,
				filters: [],
				sort: "big",
				dir: "desc",
			}),
		),
	);
	await page.reload();
	await expect(page.locator("[data-lots='600']")).toHaveAttribute(
		"aria-pressed",
		"true",
	);
	expect(await codes(page)).toHaveLength(4);
});

test("頁面不會橫向捲動", async ({ page }) => {
	await page.selectOption("#big-by", "amount");
	const overflow = await page.evaluate(
		() => document.documentElement.scrollWidth - window.innerWidth,
	);
	expect(overflow).toBeLessThanOrEqual(0);
	await shot(page, "amount-full");
});
