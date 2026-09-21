/**
 * 把 index.html、styles.css、編譯後的 TypeScript 和 report.json
 * 打包成單一自足的 HTML 檔。
 *
 * 必須自足 —— artifact 的 CSP 禁止外部腳本(只有 Google Fonts 例外),
 * 所以 JS 和 CSS 都要內嵌。
 */

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { buildSync } from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");

const OUT = process.argv[2] ?? join(root, "data", "out", "index.html");
const REPORT = join(root, "data", "out", "report.json");

/** 內嵌到 HTML 裡的東西不能含 </script>,否則會提前結束標籤 */
function escapeForScript(text: string): string {
	return text.replace(/<\/script>/gi, "<\\/script>");
}

function main(): void {
	const report = readFileSync(REPORT, "utf8");
	// 先驗證是合法 JSON,不要把壞掉的內容包進去
	JSON.parse(report);

	const bundle = buildSync({
		entryPoints: [join(here, "src", "main.ts")],
		bundle: true,
		format: "iife",
		target: "es2022",
		write: false,
		minify: false,
	});
	const code = bundle.outputFiles[0]?.text;
	if (!code) throw new Error("esbuild 沒有產生輸出");

	const styles = readFileSync(join(here, "styles.css"), "utf8");
	const shell = readFileSync(join(here, "index.html"), "utf8");

	const page = shell
		.replace("/* __STYLES__ */", styles)
		.replace(
			"/* __SCRIPT__ */",
			`const REPORT_DATA = ${escapeForScript(report)};\n${escapeForScript(code)}`,
		);

	writeFileSync(OUT, page, "utf8");
	process.stdout.write(`輸出 ${OUT}(${Math.round(page.length / 1024)} KB)\n`);
}

main();
