/** 進入點。資料由 build 內嵌成全域的 REPORT_DATA。 */

import { render } from "./render.ts";
import { parseReport } from "./report.ts";

declare const REPORT_DATA: unknown;

render(parseReport(REPORT_DATA));
