/**
 * 兩頁共用:假的網站網址、擋掉外部請求、收集頁面上的 JS 錯誤、截圖。
 *
 * 頁面用 http://twse.test/ 打開,請求由 route 從 SITE_DIR 回應 —— 跟 GitHub Pages
 * 一樣是相對路徑,所以兩頁之間的導覽連結也測得到。Google 字型回空的 CSS,
 * 斷網也能跑、每次結果一樣。
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, type Page, test } from "@playwright/test";
import { SCREENS, SITE_DIR } from "./setup.ts";

export const SITE = "http://twse.test/";

let errors: string[] = [];

/** 每個 spec 呼叫一次:打開 path 之前清掉 localStorage,結束時確認沒有 JS 錯誤 */
export function usePage(path: string): void {
	test.beforeEach(async ({ page }) => {
		errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		page.on("console", (m) => {
			if (m.type() === "error") errors.push(m.text());
		});
		await page.route("**/*", async (route) => {
			const url = new URL(route.request().url());
			if (url.host === "twse.test") {
				const file =
					url.pathname === "/" ? "index.html" : url.pathname.slice(1);
				await route.fulfill({
					body: readFileSync(join(SITE_DIR, file)),
					contentType: "text/html; charset=utf-8",
				});
			} else if (url.host.startsWith("fonts.")) {
				await route.fulfill({ body: "", contentType: "text/css" });
			} else {
				await route.abort();
			}
		});
		await page.goto(SITE + path);
		await page.evaluate(() => localStorage.clear());
		await page.reload();
	});
	test.afterEach(() => {
		expect(errors).toEqual([]);
	});
}

export async function shot(page: Page, name: string): Promise<void> {
	const project = test.info().project.name;
	await page.screenshot({
		path: join(SCREENS, `${project}-${name}.png`),
		fullPage: true,
	});
}

/** 頁面本身不能橫向捲動(表格可以在自己的框裡捲) */
export async function overflowX(page: Page): Promise<number> {
	return page.evaluate(
		() => document.documentElement.scrollWidth - window.innerWidth,
	);
}
