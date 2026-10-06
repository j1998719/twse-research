/**
 * 把頁面的 HTML、styles.css、編譯後的 TypeScript 和資料 JSON
 * 打包成單一自足的 HTML 檔。
 *
 * 必須自足 —— artifact 的 CSP 禁止外部腳本(只有 Google Fonts 例外),
 * 所以 JS 和 CSS 都要內嵌。
 *
 * 用法:node web/build.ts [report|holders],不給就是 report。
 * 兩頁分開建,一頁的資料壞了不會擋住另一頁。
 */

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { buildSync } from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const out = join(root, "data", "out");

interface Page {
	shell: string;
	entry: string;
	data: string;
	/** 進入點讀資料用的全域變數名 */
	global: string;
	output: string;
}

const PAGES: Record<string, Page> = {
	report: {
		shell: "index.html",
		entry: "main.ts",
		data: "report.json",
		global: "REPORT_DATA",
		output: "index.html",
	},
	holders: {
		shell: "holders.html",
		entry: "holders-main.ts",
		data: "bigholders.json",
		global: "HOLDERS_DATA",
		output: "holders.html",
	},
};

/** 內嵌到 HTML 裡的東西不能含 </script>,否則會提前結束標籤 */
function escapeForScript(text: string): string {
	return text.replace(/<\/script>/gi, "<\\/script>");
}

function build(page: Page): void {
	const data = readFileSync(join(out, page.data), "utf8");
	// 先驗證是合法 JSON,不要把壞掉的內容包進去
	JSON.parse(data);

	const bundle = buildSync({
		entryPoints: [join(here, "src", page.entry)],
		bundle: true,
		format: "iife",
		target: "es2022",
		write: false,
		minify: false,
	});
	const code = bundle.outputFiles[0]?.text;
	if (!code) throw new Error("esbuild 沒有產生輸出");

	const styles = readFileSync(join(here, "styles.css"), "utf8");
	const shell = readFileSync(join(here, page.shell), "utf8");

	// 用函式當取代值:資料裡的 $& 之類的字樣不能被當成取代語法
	const html = shell
		.replace("/* __STYLES__ */", () => styles)
		.replace(
			"/* __SCRIPT__ */",
			() =>
				`const ${page.global} = ${escapeForScript(data)};\n${escapeForScript(code)}`,
		);

	const target = join(out, page.output);
	writeFileSync(target, html, "utf8");
	process.stdout.write(
		`輸出 ${target}(${Math.round(html.length / 1024)} KB)\n`,
	);
}

const name = process.argv[2] ?? "report";
const page = PAGES[name];
if (!page)
	throw new Error(
		`沒有這一頁:${name}。可以用 ${Object.keys(PAGES).join("、")}`,
	);
build(page);
