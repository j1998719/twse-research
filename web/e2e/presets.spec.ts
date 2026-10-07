/** 大戶頁的「我的條件」(#56):一組一顆按鈕,點了就套用 */

import { expect, type Page, test } from "@playwright/test";
import { shot, usePage } from "./common.ts";

usePage("");

const chips = (page: Page) => page.locator("#p-list .chip");
const chip = (page: Page, name: string) =>
	page.locator("#p-list .chip", { hasText: name });

async function saveAs(page: Page, name: string): Promise<void> {
	await page.click("#p-new");
	await page.fill("#p-name", name);
	await page.click("#p-ok");
}

test("一打開只列存過的那組,而且是亮著的;沒有空格、沒有「爸爸」", async ({
	page,
}) => {
	await expect(chips(page)).toHaveCount(1);
	await expect(chips(page).first()).toHaveText("大戶增加、股價沒動");
	await expect(chips(page).first()).toHaveAttribute("aria-pressed", "true");
	await expect(page.locator("body")).not.toContainText("(空)");
	await expect(page.locator("body")).not.toContainText("爸爸");
	await expect(page.locator("#p-form")).toBeHidden();
	await shot(page, "presets");
});

test("改了條件就不亮;點一下就套用回來", async ({ page }) => {
	await page.click("[data-lots='400']");
	await expect(chips(page).first()).toHaveAttribute("aria-pressed", "false");
	await expect(page.locator("#p-tools")).toBeHidden();
	await chips(page).first().click();
	await expect(page.locator("[data-lots='1000']")).toHaveAttribute(
		"aria-pressed",
		"true",
	);
	await expect(chips(page).first()).toHaveAttribute("aria-pressed", "true");
	await expect(page.locator("#p-tools")).toBeVisible();
});

test("存目前的條件:多一顆、亮著、重新整理還在", async ({ page }) => {
	await page.click("[data-lots='400']");
	await saveAs(page, "四百張");
	await expect(chips(page)).toHaveCount(2);
	await expect(chip(page, "四百張")).toHaveAttribute("aria-pressed", "true");
	await expect(page.locator("#p-msg")).toContainText("已存成「四百張」");
	await page.reload();
	await expect(chip(page, "四百張")).toHaveAttribute("aria-pressed", "true");
	await shot(page, "presets-saved");
});

test("取消就不存", async ({ page }) => {
	await page.click("#p-new");
	await page.fill("#p-name", "不要");
	await page.click("#p-cancel");
	await expect(chips(page)).toHaveCount(1);
	await expect(page.locator("#p-new")).toBeVisible();
});

test("改名", async ({ page }) => {
	await page.click("#p-rename");
	await expect(page.locator("#p-name")).toHaveValue("大戶增加、股價沒動");
	await page.fill("#p-name", "我的主力");
	await page.press("#p-name", "Enter");
	await expect(chips(page).first()).toHaveText("我的主力");
});

test("刪除之後可以復原", async ({ page }) => {
	await page.click("#p-delete");
	await expect(chips(page)).toHaveCount(0);
	await page.click("#p-undo");
	await expect(chips(page)).toHaveCount(1);
	await expect(chips(page).first()).toHaveText("大戶增加、股價沒動");
});

test("最多 10 組,滿了按鈕變灰", async ({ page }) => {
	for (let i = 2; i <= 10; i++) {
		await page.click(`[data-lots='${i % 2 ? 400 : 600}']`);
		await page.selectOption("#weeks", String(i % 8 || 8));
		await saveAs(page, `第 ${i} 組`);
	}
	await expect(chips(page)).toHaveCount(10);
	await expect(page.locator("#p-new")).toBeDisabled();
	await expect(page.locator("#p-new")).toHaveText("最多 10 組");
	await shot(page, "presets-full");
});

test("瀏覽器裡存的舊名字「爸爸:…」會自動改掉", async ({ page }) => {
	await page.evaluate(() => {
		const screen = {
			big: { by: "lots", value: 1000 },
			weeks: 4,
			filters: [],
			sort: "big",
			dir: "desc",
		};
		localStorage.setItem(
			"holders.presets.v1",
			JSON.stringify([{ name: "爸爸:大戶增加、股價沒動", screen }]),
		);
	});
	await page.reload();
	await expect(chips(page).first()).toHaveText("大戶增加、股價沒動");
});

test("一組條件的內容都在同一個模組裡;搜尋不存,在模組外(#57)", async ({
	page,
}) => {
	const module = page.locator("#module");
	for (const id of [
		"p-list",
		"big-by",
		"weeks",
		"filters",
		"add",
		"sort",
		"dir",
	]) {
		await expect(module.locator(`#${id}`), id).toHaveCount(1);
	}
	await expect(module.locator("#q")).toHaveCount(0);
	await expect(page.locator("#q")).toBeVisible();
	await shot(page, "module");
});

test("沒有「恢復預設」:預設那組就是第一顆按鈕(#57)", async ({ page }) => {
	await expect(page.locator("#reset")).toHaveCount(0);
	await expect(page.getByText("恢復預設")).toHaveCount(0);
});

test("全部刪光再重新整理,預設那組會回來(#57)", async ({ page }) => {
	await page.click("#p-delete");
	await expect(chips(page)).toHaveCount(0);
	await page.reload();
	await expect(chips(page)).toHaveCount(1);
	await expect(chips(page).first()).toHaveText("大戶增加、股價沒動");
});

test("模組裡的東西不貼框邊(#57)", async ({ page }) => {
	const box = await page.locator("#module").boundingBox();
	for (const id of ["p-title", "big-by", "sort"]) {
		const inner = await page.locator(`#${id}`).boundingBox();
		expect((inner?.x ?? 0) - (box?.x ?? 0), id).toBeGreaterThanOrEqual(8);
	}
});
