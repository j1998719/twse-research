/** canvas 繪圖。顏色一律從 CSS 變數取,才會跟著深淺色主題走。 */

function token(name: string): string {
	return getComputedStyle(document.documentElement)
		.getPropertyValue(name)
		.trim();
}

function context(
	id: string,
): [HTMLCanvasElement, CanvasRenderingContext2D] | null {
	const canvas = document.querySelector<HTMLCanvasElement>(`#${id}`);
	const ctx = canvas?.getContext("2d");
	if (!canvas || !ctx) return null;
	ctx.clearRect(0, 0, canvas.width, canvas.height);
	return [canvas, ctx];
}

/** 以出關日對齊的價格路徑。峰值那點特別標出來 */
export function drawPath(points: [number, number][]): void {
	const found = context("path");
	if (!found) return;
	const [canvas, ctx] = found;
	const pad = { l: 70, r: 30, t: 30, b: 56 };
	const xs = points.map((p) => p[0]);
	const ys = points.map((p) => p[1]);
	const lo = Math.min(...ys) - 0.8;
	const hi = Math.max(...ys) + 0.8;
	const xAt = (v: number) =>
		pad.l +
		((v - Math.min(...xs)) / (Math.max(...xs) - Math.min(...xs))) *
			(canvas.width - pad.l - pad.r);
	const yAt = (v: number) =>
		canvas.height -
		pad.b -
		((v - lo) / (hi - lo)) * (canvas.height - pad.t - pad.b);

	const peak = points.reduce((a, b) => (b[1] > a[1] ? b : a));

	ctx.strokeStyle = token("--hair");
	ctx.lineWidth = 2;
	ctx.beginPath();
	ctx.moveTo(pad.l, yAt(0));
	ctx.lineTo(canvas.width - pad.r, yAt(0));
	ctx.stroke();

	ctx.setLineDash([7, 6]);
	ctx.strokeStyle = token("--muted");
	ctx.beginPath();
	ctx.moveTo(xAt(0), pad.t);
	ctx.lineTo(xAt(0), canvas.height - pad.b);
	ctx.stroke();
	ctx.setLineDash([]);

	ctx.strokeStyle = token("--brass");
	ctx.lineWidth = 5;
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
		ctx.arc(xAt(x), yAt(y), isPeak ? 11 : 6, 0, Math.PI * 2);
		ctx.fill();
	}

	ctx.fillStyle = token("--up");
	ctx.font = "700 26px 'IBM Plex Mono', monospace";
	ctx.textAlign = "center";
	ctx.fillText(`+${peak[1].toFixed(2)}%`, xAt(peak[0]), yAt(peak[1]) - 24);
	ctx.fillStyle = token("--muted");
	ctx.font = "600 22px 'Noto Sans TC', sans-serif";
	ctx.fillText("出關前一日見頂", xAt(peak[0]), yAt(peak[1]) - 52);
	ctx.fillText("出關日", xAt(0), canvas.height - pad.b + 34);

	ctx.font = "400 22px 'IBM Plex Mono', monospace";
	for (const v of [-6, -4, -2, 2, 4]) {
		ctx.fillText(`${v > 0 ? "+" : ""}${v}`, xAt(v), canvas.height - pad.b + 34);
	}
	ctx.textAlign = "right";
	for (let v = Math.ceil(lo); v <= Math.floor(hi); v++) {
		ctx.fillText(`${v}%`, pad.l - 14, yAt(v) + 8);
	}
}

/** 每月處置件數。新制上路後的月份換色 */
export function drawMonthly(
	rows: { m: string; n: number }[],
	newRulesFrom: string,
): void {
	const found = context("bars");
	if (!found || rows.length === 0) return;
	const [canvas, ctx] = found;
	const pad = { l: 50, r: 20, t: 20, b: 52 };
	const max = Math.max(...rows.map((d) => d.n));
	const width = (canvas.width - pad.l - pad.r) / rows.length;

	ctx.strokeStyle = token("--hair");
	ctx.lineWidth = 2;
	ctx.beginPath();
	ctx.moveTo(pad.l, canvas.height - pad.b);
	ctx.lineTo(canvas.width - pad.r, canvas.height - pad.b);
	ctx.stroke();

	rows.forEach((row, i) => {
		const height = (row.n / max) * (canvas.height - pad.t - pad.b);
		const x = pad.l + i * width;
		const isNew = row.m >= newRulesFrom;
		ctx.fillStyle = isNew ? token("--brass") : token("--muted");
		ctx.globalAlpha = isNew ? 0.95 : 0.5;
		ctx.fillRect(
			x + 1,
			canvas.height - pad.b - height,
			Math.max(2, width - 2),
			height,
		);
		ctx.globalAlpha = 1;
		if (row.m.endsWith("-01")) {
			ctx.fillStyle = token("--muted");
			ctx.font = "400 21px 'IBM Plex Mono', monospace";
			ctx.textAlign = "center";
			ctx.fillText(
				row.m.slice(0, 4),
				x + width / 2,
				canvas.height - pad.b + 32,
			);
		}
	});

	ctx.fillStyle = token("--muted");
	ctx.font = "400 20px 'IBM Plex Mono', monospace";
	ctx.textAlign = "right";
	for (const v of [0, Math.round(max / 2), max]) {
		ctx.fillText(
			String(v),
			pad.l - 10,
			canvas.height - pad.b - (v / max) * (canvas.height - pad.t - pad.b) + 7,
		);
	}
}
