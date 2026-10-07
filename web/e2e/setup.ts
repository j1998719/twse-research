/** 把假資料複製到暫存目錄,用 build.ts 建出要測的頁面 */

import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
/** 建好的頁面放這裡;spec 用同一個路徑打開 */
export const BUILT = join(here, "..", "..", "test-results", "e2e-build");

export default function setup(): void {
	mkdirSync(BUILT, { recursive: true });
	copyFileSync(
		join(here, "fixtures", "bigholders.json"),
		join(BUILT, "bigholders.json"),
	);
	execFileSync(
		process.execPath,
		["--experimental-strip-types", join(here, "..", "build.ts"), "holders"],
		{ env: { ...process.env, BUILD_DIR: BUILT }, stdio: "pipe" },
	);
}
