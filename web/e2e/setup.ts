/**
 * 用假資料(fixtures/)建出兩頁,再照 publish_pages.sh 的檔名排成網站:
 * 大戶持股是首頁(index.html),處置股觀測是 disposition.html。
 */

import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const results = join(here, "..", "..", "test-results");
/** build.ts 的資料與輸出目錄 */
const BUILT = join(results, "e2e-build");
/** 排成 GitHub Pages 那樣的網站,common.ts 從這裡回應請求 */
export const SITE_DIR = join(results, "e2e-site");
/** 截圖 */
export const SCREENS = join(results, "screens");

/** [建出來的檔名, 網站上的檔名] —— 跟 publish_pages.sh 的 PAGES 一樣 */
const PAGES: [string, string][] = [
	["holders.html", "index.html"],
	["index.html", "disposition.html"],
];

export default function setup(): void {
	mkdirSync(BUILT, { recursive: true });
	mkdirSync(SITE_DIR, { recursive: true });
	for (const name of ["bigholders.json", "report.json"]) {
		copyFileSync(join(here, "fixtures", name), join(BUILT, name));
	}
	for (const page of ["holders", "report"]) {
		execFileSync(
			process.execPath,
			["--experimental-strip-types", join(here, "..", "build.ts"), page],
			{ env: { ...process.env, BUILD_DIR: BUILT }, stdio: "pipe" },
		);
	}
	for (const [built, published] of PAGES) {
		copyFileSync(join(BUILT, built), join(SITE_DIR, published));
	}
}
