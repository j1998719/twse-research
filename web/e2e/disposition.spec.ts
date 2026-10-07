/**
 * 處置股觀測(disposition.html)。假資料的七張卡片,見 fixtures/report.json:
 *
 * 3219 已賣出 · 4174 持有中 · 3094 剛進場 · 2221 尚未到買點 ·
 * 6708 漲停順延 2 天才買到(上櫃) · 3055 跌停賣不掉 · 8227 第二次處置
 */

import { expect, type Page, test } from "@playwright/test";
import { overflowX, SITE, shot, usePage } from "./common.ts";

usePage("disposition.html");

function card(page: Page, code: string) {
	return page.locator("#board .cell", {
		has: page.locator(".code", { hasText: code }),
	});
}

/** 卡片上某一欄(dt)對應的值(dd) */
async function field(page: Page, code: string, label: string): Promise<string> {
	const dd = card(page, code).locator(`dt:has-text("${label}") + dd`);
	return (await dd.innerText()).replace(/\s+/g, " ").trim();
}

test("每一張卡片都畫出來,沒有 undefined 或 NaN", async ({ page }) => {
	await expect(page.locator("#board .cell")).toHaveCount(7);
	const text = await page.locator("body").innerText();
	expect(text).not.toMatch(/undefined|NaN/);
	await expect(page.locator("#m-gen")).toHaveText("2026-10-07");
	await shot(page, "disposition");
});

test("已賣出的卡片寫實現報酬", async ({ page }) => {
	await expect(
		card(page, "3219").locator("dt", { hasText: "實現報酬" }),
	).toBeVisible();
	expect(await field(page, "3219", "報酬")).toBe("+6.42% 已賣出");
});

test("剛進場:報酬留空,不顯示負的成本(#54)", async ({ page }) => {
	expect(await field(page, "3094", "報酬")).toBe("— 剛進場");
});

test("還沒到買點:進場價是空的", async ({ page }) => {
	expect(await field(page, "2221", "模擬進場")).toBe("—");
	await expect(card(page, "2221").locator(".state")).toHaveText("尚未到買點");
});

test("漲停順延:標出順延幾天", async ({ page }) => {
	expect(await field(page, "6708", "模擬進場")).toBe("40.00 10-03 順延 2 天");
});

test("跌停賣不掉:虧損上綠色", async ({ page }) => {
	const dd = card(page, "3055").locator('dt:has-text("報酬") + dd');
	await expect(dd).toHaveClass(/neg/);
	await expect(dd).toContainText("跌停賣不掉,順延中");
});

test("第二次處置標全額預收", async ({ page }) => {
	await expect(card(page, "8227").locator(".tag:not(.cand)")).toHaveText(
		"全額預收",
	);
	await expect(card(page, "4174").locator(".tag")).toHaveText("第一次");
});

test("卡片連到 Yahoo 股市,上市 .TW、上櫃 .TWO", async ({ page }) => {
	await expect(card(page, "4174").locator("a.quote")).toHaveAttribute(
		"href",
		/tw\.stock\.yahoo\.com\/quote\/4174\.TW$/,
	);
	await expect(card(page, "6708").locator("a.quote")).toHaveAttribute(
		"href",
		/tw\.stock\.yahoo\.com\/quote\/6708\.TWO$/,
	);
});

test("兩張圖都有畫東西", async ({ page }) => {
	for (const id of ["path", "bars"]) {
		const inked = await page.locator(`#${id}`).evaluate((c) => {
			const canvas = c as HTMLCanvasElement;
			const ctx = canvas.getContext("2d");
			if (!ctx) return 0;
			const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
			let n = 0;
			for (let i = 3; i < data.length; i += 4) if ((data[i] ?? 0) > 0) n++;
			return n;
		});
		expect(inked, id).toBeGreaterThan(1000);
	}
});

test("說明文字不再說國定假日會有誤差(#54 已經用休市日推算)", async ({
	page,
}) => {
	await expect(page.locator("body")).not.toContainText(
		"國定假日會有一兩天誤差",
	);
});

test("導覽列可以切回大戶持股", async ({ page }) => {
	await page.click('.sitenav a:has-text("大戶持股")');
	await expect(page).toHaveURL(SITE);
	await expect(page.locator("h1")).toContainText("大戶持股排行");
	await page.click('.sitenav a:has-text("處置股觀測")');
	await expect(page).toHaveURL(`${SITE}disposition.html`);
});

test("頁面不會橫向捲動", async ({ page }) => {
	expect(await overflowX(page)).toBeLessThanOrEqual(0);
});

test("圖照顯示寬度畫,手機上的字才不會縮成兩三個像素", async ({ page }) => {
	for (const id of ["path", "bars"]) {
		const { backing, shown, dpr } = await page
			.locator(`#${id}`)
			.evaluate((c) => ({
				backing: (c as HTMLCanvasElement).width,
				shown: c.clientWidth,
				dpr: window.devicePixelRatio,
			}));
		expect(Math.abs(backing - Math.round(shown * dpr)), id).toBeLessThanOrEqual(
			1,
		);
	}
});

// ---- #30:研究中的候選(Jordan 2026-10-07:要放上網頁)----

test("候選區塊一定帶著「還沒驗證」的警語", async ({ page }) => {
	const section = page.locator("#candidate");
	await expect(section.locator("h2")).toContainText("第二次處置 × 流動性");
	await expect(section.locator(".warn")).toContainText("還沒驗證");
	await expect(section.locator(".warn")).toContainText("不是建議");
	await shot(page, "candidate");
});

test("候選和全體、第二次並排比較", async ({ page }) => {
	const rows = page.locator("#t-cand tr");
	await expect(rows).toHaveCount(3);
	await expect(rows.nth(2)).toContainText("第二次 × 流動性 ≥ 2 億");
	await expect(rows.nth(2)).toContainText("305");
	await expect(rows.nth(2)).toContainText("+4.41%");
	await expect(rows.nth(2)).toContainText("70.8%");
	await expect(rows.nth(2)).toContainText("+3.27%");
	await expect(page.locator("#cand-freq")).toHaveText("3.8");
});

test("候選的組合回測跟大盤並排", async ({ page }) => {
	const rows = page.locator("#t-cand-port tr");
	await expect(rows).toHaveCount(4);
	await expect(rows.nth(1)).toContainText("每筆本金 10%");
	await expect(rows.nth(1)).toContainText("-6.0%");
	await expect(rows.nth(3)).toContainText("加權指數買進持有");
	await expect(rows.nth(3)).toContainText("772 天");
});

test("目前處置中符合條件的卡片標「候選」", async ({ page }) => {
	await expect(card(page, "8227").locator(".tag.cand")).toHaveText("候選");
	await expect(card(page, "8227")).toContainText("流動性 4.5 億");
	await expect(card(page, "4174").locator(".tag.cand")).toHaveCount(0);
});

test("新制 t−6 在公告前:買點標成「公告後最早」,不假裝是 t−6(#65)", async ({
	page,
}) => {
	await expect(card(page, "3094")).toContainText("公告後最早");
	await expect(card(page, "3094")).not.toContainText("參考買點 t−6");
	await expect(card(page, "4174")).toContainText("參考買點 t−6");
});
