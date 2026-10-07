/**
 * canvas 繪圖。顏色一律從 CSS 變數取,才會跟著深淺色主題走。
 *
 * 畫布照「實際顯示的寬度 × 螢幕解析度」建立,座標和字級都用 CSS 像素。
 * 以前固定畫在 1840 寬再縮放,手機上縮成 1/5,刻度字只剩兩三個像素
 * (瀏覽器測試的截圖看到的)。
 */

function token(name: string): string {
	return getComputedStyle(document.documentElement)
		.getPropertyValue(name)
		.trim();
}

/** 畫布的 CSS 像素寬高 */
interface Size {
	w: number;
	h: number;
}

/**
 * 依顯示寬度重設畫布。高度 = 寬度 × ratio,但不低於 minHeight —— 手機上
 * 照比例會扁到看不出起伏。
 */
function context(
	id: string,
	ratio: number,
	minHeight: number,
): [CanvasRenderingContext2D, Size] | null {
	const canvas = document.querySelector<HTMLCanvasElement>(`#${id}`);
	const ctx = canvas?.getContext("2d");
	if (!canvas || !ctx) return null;
	const w = canvas.clientWidth || 920;
	const h = Math.max(minHeight, Math.round(w * ratio));
	const dpr = window.devicePixelRatio || 1;
	canvas.style.height = `${h}px`;
	canvas.width = Math.round(w * dpr);
	canvas.height = Math.round(h * dpr);
	ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
	ctx.clearRect(0, 0, w, h);
	return [ctx, { w, h }];
}

/** 以出關日對齊的價格路徑。峰值那點特別標出來 */
export function drawPath(points: [number, number][]): void {
	const found = context("path", 620 / 1840, 240);
	if (!found) return;
	const [ctx, canvas] = found;
	const pad = { l: 40, r: 15, t: 40, b: 30 };
	const xs = points.map((p) => p[0]);
	const ys = points.map((p) => p[1]);
	const lo = Math.min(...ys) - 0.8;
	const hi = Math.max(...ys) + 0.8;
	const xAt = (v: number) =>
		pad.l +
		((v - Math.min(...xs)) / (Math.max(...xs) - Math.min(...xs))) *
			(canvas.w - pad.l - pad.r);
	const yAt = (v: number) =>
		canvas.h - pad.b - ((v - lo) / (hi - lo)) * (canvas.h - pad.t - pad.b);

	const peak = points.reduce((a, b) => (b[1] > a[1] ? b : a));

	ctx.strokeStyle = token("--hair");
	ctx.lineWidth = 1;
	ctx.beginPath();
	ctx.moveTo(pad.l, yAt(0));
	ctx.lineTo(canvas.w - pad.r, yAt(0));
	ctx.stroke();

	ctx.setLineDash([4, 3]);
	ctx.strokeStyle = token("--muted");
	ctx.beginPath();
	ctx.moveTo(xAt(0), pad.t);
	ctx.lineTo(xAt(0), canvas.h - pad.b);
	ctx.stroke();
	ctx.setLineDash([]);

	ctx.strokeStyle = token("--brass");
	ctx.lineWidth = 2.5;
	ctx.lineJoin = "round";
	ctx.beginPath();
	points.forEach(([x, y], i) => {
		if (i === 0) ctx.moveTo(xAt(x), yAt(y));
		else ctx.lineTo(xAt(x), yAt(y));
	});
	ctx.stroke();

	for (const [x, y] of points) {
		const isPeak = x === peak[0];
		ctx.fillStyle = isPeak ? token("--up") : token("--brass");
		ctx.beginPath();
		ctx.arc(xAt(x), yAt(y), isPeak ? 5.5 : 3, 0, Math.PI * 2);
		ctx.fill();
	}

	ctx.fillStyle = token("--up");
	ctx.font = "700 13px 'IBM Plex Mono', monospace";
	ctx.textAlign = "center";
	ctx.fillText(`+${peak[1].toFixed(2)}%`, xAt(peak[0]), yAt(peak[1]) - 12);
	ctx.fillStyle = token("--muted");
	ctx.font = "600 12px 'Noto Sans TC', sans-serif";
	ctx.fillText("出關前一日見頂", xAt(peak[0]), yAt(peak[1]) - 27);
	ctx.fillText("出關日", xAt(0), canvas.h - pad.b + 18);

	ctx.font = "400 11px 'IBM Plex Mono', monospace";
	for (const v of [-6, -4, -2, 2, 4]) {
		ctx.fillText(`${v > 0 ? "+" : ""}${v}`, xAt(v), canvas.h - pad.b + 18);
	}
	ctx.textAlign = "right";
	for (let v = Math.ceil(lo); v <= Math.floor(hi); v++) {
		ctx.fillText(`${v}%`, pad.l - 7, yAt(v) + 4);
	}
}

/** 每月處置件數。新制上路後的月份換色 */
export function drawMonthly(
	rows: { m: string; n: number }[],
	newRulesFrom: string,
): void {
	const found = context("bars", 400 / 1840, 160);
	if (!found || rows.length === 0) return;
	const [ctx, canvas] = found;
	const pad = { l: 30, r: 10, t: 10, b: 26 };
	const max = Math.max(...rows.map((d) => d.n));
	const width = (canvas.w - pad.l - pad.r) / rows.length;

	ctx.strokeStyle = token("--hair");
	ctx.lineWidth = 1;
	ctx.beginPath();
	ctx.moveTo(pad.l, canvas.h - pad.b);
	ctx.lineTo(canvas.w - pad.r, canvas.h - pad.b);
	ctx.stroke();

	rows.forEach((row, i) => {
		const height = (row.n / max) * (canvas.h - pad.t - pad.b);
		const x = pad.l + i * width;
		const isNew = row.m >= newRulesFrom;
		ctx.fillStyle = isNew ? token("--brass") : token("--muted");
		ctx.globalAlpha = isNew ? 0.95 : 0.5;
		ctx.fillRect(
			x + 0.5,
			canvas.h - pad.b - height,
			Math.max(1, width - 1),
			height,
		);
		ctx.globalAlpha = 1;
		if (row.m.endsWith("-01")) {
			ctx.fillStyle = token("--muted");
			ctx.font = "400 11px 'IBM Plex Mono', monospace";
			ctx.textAlign = "center";
			ctx.fillText(row.m.slice(0, 4), x + width / 2, canvas.h - pad.b + 16);
		}
	});

	ctx.fillStyle = token("--muted");
	ctx.font = "400 11px 'IBM Plex Mono', monospace";
	ctx.textAlign = "right";
	for (const v of [0, Math.round(max / 2), max]) {
		ctx.fillText(
			String(v),
			pad.l - 5,
			canvas.h - pad.b - (v / max) * (canvas.h - pad.t - pad.b) + 4,
		);
	}
}
