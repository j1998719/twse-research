/**
 * 瀏覽器測試:用假資料(fixtures/)建出頁面,在無頭 Chromium 裡實際操作。
 *
 * tsc 和 Biome 看不到畫面 —— 輸入框被擠成三行、數字沒對齊這類問題,只有在
 * 瀏覽器裡跑起來才看得到(#55 就是這樣抓到的)。測試有兩種產出:
 *
 * - 斷言:失敗就擋 push
 * - 截圖:存在 test-results/screens/,給人(或 Claude)看排版
 *
 * 用法:npm run e2e(第一次要先 npx playwright install chromium)
 */

import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
	testDir: ".",
	outputDir: "../../test-results/e2e",
	globalSetup: "./setup.ts",
	reporter: [["list"]],
	use: {
		...devices["Desktop Chrome"],
		viewport: { width: 1280, height: 1000 },
	},
	projects: [
		{ name: "desktop" },
		{
			name: "phone",
			use: {
				viewport: { width: 390, height: 844 },
				isMobile: true,
				hasTouch: true,
			},
		},
	],
});
