const STYLE_ID = "current-action-dock-style";
const TIMELINE_SELECTOR = "[data-agent-timeline-scroll='true']";
const GENERATED_ATTR = "data-current-action-generated";
const LEGACY_COMPACT_ATTR = "data-history-compact-row";
const DOCK_ATTR = "data-current-action-dock";
const HIDDEN_ATTR = "data-current-action-hidden";
const ORIGINAL_ORDER_ATTR = "data-current-action-original-order";
const SOURCE_ATTR = "data-current-action-source";

let sourceSequence = 0;

let installed = false;
let scheduled = false;
let applying = false;

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
[${HIDDEN_ATTR}="true"] { display: none !important; }

${TIMELINE_SELECTOR} {
	padding-bottom: var(--current-action-dock-space, .75rem) !important;
}

[${GENERATED_ATTR}="placeholder"] { pointer-events: none; }

[${DOCK_ATTR}="true"] {
	position: fixed !important;
	z-index: 60 !important;
	display: flex !important;
	box-sizing: border-box !important;
	margin: 0 !important;
	padding: 2.15rem .45rem .55rem !important;
	overflow-x: hidden;
	overflow-y: auto;
	border: 1px solid rgba(96,165,250,.30);
	border-radius: 1rem 1rem .35rem .35rem;
	background:
		linear-gradient(180deg, rgba(248,250,252,.97), rgba(255,255,255,.99)),
		radial-gradient(circle at 16% 0%, rgba(96,165,250,.13), transparent 34%);
	box-shadow: 0 -14px 34px rgba(15,23,42,.10), 0 0 0 1px rgba(255,255,255,.72) inset;
	backdrop-filter: blur(20px) saturate(1.15);
	-webkit-backdrop-filter: blur(20px) saturate(1.15);
	overscroll-behavior: contain;
	scrollbar-gutter: stable;
}

[${DOCK_ATTR}="true"]::before {
	content: attr(data-current-action-heading);
	position: absolute;
	left: .75rem;
	top: .48rem;
	font-size: .7rem;
	line-height: 1rem;
	font-weight: 750;
	letter-spacing: .02em;
	color: rgb(30 64 175);
}

[${DOCK_ATTR}="true"]::after {
	content: "";
	position: absolute;
	left: .75rem;
	right: .75rem;
	top: 1.72rem;
	height: 1px;
	background: linear-gradient(90deg, rgba(59,130,246,.24), rgba(45,212,191,.14), transparent);
}

[${DOCK_ATTR}="true"] > div,
[${DOCK_ATTR}="true"] [data-agent-card] {
	width: 100% !important;
	max-width: none !important;
}

[${DOCK_ATTR}="true"] [data-agent-card] { box-shadow: none !important; }

[${GENERATED_ATTR}="idle"] {
	position: fixed;
	z-index: 55;
	box-sizing: border-box;
	padding: .75rem .9rem;
	border: 1px solid rgba(148,163,184,.20);
	border-radius: .9rem .9rem .35rem .35rem;
	background: rgba(248,250,252,.96);
	box-shadow: 0 -10px 24px rgba(15,23,42,.06);
	font-size: .72rem;
	font-weight: 650;
	color: rgb(100 116 139);
}

`;
	document.head.appendChild(style);
}

function textOf(node: Element | null) {
	return (node?.textContent || "").replace(/\s+/g, " ").trim();
}

function getTimeline() {
	return document.querySelector<HTMLElement>(TIMELINE_SELECTOR);
}

function getRows(scroll: HTMLElement) {
	return Array.from(scroll.children).filter(
		(node): node is HTMLElement =>
			node instanceof HTMLElement &&
			node.getAttribute(GENERATED_ATTR) == null &&
			textOf(node).length > 0,
	);
}

function isChoiceRow(row: HTMLElement) {
	return Boolean(row.querySelector(".choice-attachment"));
}

function isUserStop(row: HTMLElement) {
	return /用户请求安全停止当前建模工作流|用户请求停止当前建模工作流|用户请求停止任务/.test(
		textOf(row),
	);
}

function isSystemStop(row: HTMLElement) {
	return /停止指令已发送|正在安全停止|任务已停止|任务已安全停止|任务已中断/.test(
		textOf(row),
	);
}

function isFinalSystemStop(row: HTMLElement) {
	return /任务已停止|任务已安全停止|任务已中断/.test(textOf(row));
}

function isImageRevision(row: HTMLElement) {
	return /图片修订|修改图片|AI 修改图片|图片修改|重新生成图片/.test(textOf(row));
}

function isTextRevision(row: HTMLElement) {
	return /文本修订|修改论文文本|AI 修改文本|文本修改/.test(textOf(row));
}

function isEda(row: HTMLElement) {
	return /\bEDA\b|探索性数据分析|数据探索与代码求解|数据预处理与探索/i.test(
		textOf(row),
	);
}

function stateOf(row: HTMLElement): "running" | "done" | "stopped" | "warning" {
	const text = textOf(row);
	if (/已停止|任务已停止|停止指令|已中断/.test(text)) return "stopped";
	if (
		row.querySelector(
			"[data-running-card='true'], .cp-action[data-active='true'], .animate-spin",
		)
	)
		return "running";
	if (/失败|错误|需关注|改错/.test(text)) return "warning";
	if (/已完成|完成|成功|已确认/.test(text)) return "done";
	if (/正在|进行中|开始|生成中|执行中/.test(text))
		return "running";
	return "done";
}

function restoreFullCard(row: HTMLElement) {
	row.removeAttribute(LEGACY_COMPACT_ATTR);
	for (const label of row.querySelectorAll<HTMLElement>(
		"[data-history-compact-label='true']",
	)) {
		label.remove();
	}
}

function dedupeStops(rows: HTMLElement[]) {
	const userStops = rows.filter(isUserStop);
	for (const [index, row] of userStops.entries())
		row.setAttribute(HIDDEN_ATTR, index === 0 ? "false" : "true");

	const systemStops = rows.filter(isSystemStop);
	const finalStops = systemStops.filter(isFinalSystemStop);
	const keptSystem = finalStops.at(-1) || systemStops.at(-1) || null;
	for (const row of systemStops)
		row.setAttribute(HIDDEN_ATTR, row === keptSystem ? "false" : "true");

	return { user: userStops[0] || null, system: keptSystem };
}

function safeOrder(row: HTMLElement, fallback: number) {
	const saved = row.getAttribute(ORIGINAL_ORDER_ATTR);
	const candidate = Number.parseInt(saved ?? row.style.order ?? "", 10);
	return Number.isFinite(candidate) && Math.abs(candidate) < 100_000_000
		? candidate
		: fallback;
}

function activeRichRow(rows: HTMLElement[]) {
	const visible = rows.filter((row) => row.getAttribute(HIDDEN_ATTR) !== "true");
	const runningRich = visible.filter(
		(row) =>
			Boolean(row.querySelector("[data-running-card='true']")) &&
			Boolean(
				row.querySelector(".streaming-detail, img, .message-detail, [data-running-card]"),
			),
	);
	if (runningRich.length) return runningRich.at(-1) || null;

	const runningRevision = visible.filter(
		(row) =>
			(isImageRevision(row) || isTextRevision(row)) && stateOf(row) === "running",
	);
	if (runningRevision.length) return runningRevision.at(-1) || null;

	const rich = visible.filter(
		(row) =>
			!isChoiceRow(row) &&
			Boolean(row.querySelector(".streaming-detail, img, .message-detail")) &&
			(isEda(row) ||
				isImageRevision(row) ||
				isTextRevision(row) ||
				/代码求解|模型求解|写作/.test(textOf(row))),
	);
	return rich.at(-1) || null;
}

function clearDockStyles(row: HTMLElement) {
	row.removeAttribute(DOCK_ATTR);
	row.removeAttribute("data-current-action-heading");
	for (const property of [
		"left",
		"right",
		"bottom",
		"width",
		"max-height",
		"visibility",
	])
		row.style.removeProperty(property);
	row.removeAttribute(ORIGINAL_ORDER_ATTR);
}

function removeGenerated(scroll: HTMLElement, kind?: "placeholder" | "idle") {
	for (const node of scroll.querySelectorAll<HTMLElement>(`[${GENERATED_ATTR}]`))
		if (!kind || node.getAttribute(GENERATED_ATTR) === kind) node.remove();
}

function ensurePlaceholder(scroll: HTMLElement, row: HTMLElement, order: number) {
	let placeholder = scroll.querySelector<HTMLElement>(
		`[${GENERATED_ATTR}='placeholder']`,
	);
	let source = row.getAttribute(SOURCE_ATTR);
	if (!source) {
		sourceSequence += 1;
		source = `action-${sourceSequence}`;
		row.setAttribute(SOURCE_ATTR, source);
	}
	if (!placeholder || placeholder.getAttribute(SOURCE_ATTR) !== source) {
		placeholder?.remove();
		placeholder = row.cloneNode(true) as HTMLElement;
		placeholder.setAttribute(GENERATED_ATTR, "placeholder");
		placeholder.setAttribute(SOURCE_ATTR, source);
		placeholder.removeAttribute(DOCK_ATTR);
		placeholder.removeAttribute(ORIGINAL_ORDER_ATTR);
		placeholder.removeAttribute("data-current-action-heading");
		placeholder.style.cssText = "";
		for (const node of [
			placeholder,
			...placeholder.querySelectorAll<HTMLElement>("[id]"),
		]) {
			node.removeAttribute("id");
		}
		scroll.appendChild(placeholder);
	}
	placeholder.style.order = String(order);
}

function ensureIdle(scroll: HTMLElement) {
	let idle = scroll.querySelector<HTMLElement>(`[${GENERATED_ATTR}='idle']`);
	if (!idle) {
		idle = document.createElement("div");
		idle.setAttribute(GENERATED_ATTR, "idle");
		idle.textContent = "当前动作 · 暂无正在执行的任务";
		scroll.appendChild(idle);
	}
	return idle;
}

function positionDock(scroll: HTMLElement, dock: HTMLElement) {
	const rect = scroll.getBoundingClientRect();
	if (rect.width < 80 || rect.height < 80) {
		dock.style.visibility = "hidden";
		return;
	}
	const inset = 7;
	const maxHeight = Math.min(window.innerHeight * 0.48, rect.height * 0.54, 480);
	dock.style.visibility = "visible";
	dock.style.left = `${Math.round(rect.left + inset)}px`;
	dock.style.right = "auto";
	dock.style.bottom = `${Math.max(4, Math.round(window.innerHeight - rect.bottom + inset))}px`;
	dock.style.width = `${Math.max(120, Math.round(rect.width - inset * 2))}px`;
	dock.style.maxHeight = `${Math.max(90, Math.round(maxHeight))}px`;
	requestAnimationFrame(() => {
		if (!dock.isConnected || !scroll.isConnected) return;
		const height = Math.ceil(dock.getBoundingClientRect().height);
		const reserved = Math.min(
			Math.max(48, height + 16),
			Math.max(80, rect.height * 0.62),
		);
		scroll.style.setProperty("--current-action-dock-space", `${reserved}px`);
	});
}

function applyDock(scroll: HTMLElement, rows: HTMLElement[], selected: HTMLElement | null) {
	for (const row of rows) {
		if (row !== selected && row.hasAttribute(DOCK_ATTR)) clearDockStyles(row);
	}

	if (!selected) {
		removeGenerated(scroll, "placeholder");
		positionDock(scroll, ensureIdle(scroll));
		return;
	}

	removeGenerated(scroll, "idle");
	const fallbackOrder = rows.indexOf(selected) * 10;
	const order = safeOrder(selected, fallbackOrder);
	selected.setAttribute(ORIGINAL_ORDER_ATTR, String(order));
	selected.style.order = String(order);
	selected.setAttribute(DOCK_ATTR, "true");
	selected.setAttribute(
		"data-current-action-heading",
		stateOf(selected) === "running" ? "当前动作 · 正在执行" : "当前动作 · 最近结果",
	);
	ensurePlaceholder(scroll, selected, order);
	positionDock(scroll, selected);
}

function normalizeTimeline() {
	if (applying) return;
	const scroll = getTimeline();
	if (!scroll) return;
	applying = true;
	try {
		const rows = getRows(scroll);
		for (const row of rows) {
			row.setAttribute(HIDDEN_ATTR, "false");
			restoreFullCard(row);
		}
		const stops = dedupeStops(rows);
		const selected = activeRichRow(rows);

		const ordinary = rows.filter(
			(row) =>
				row !== selected &&
				!isUserStop(row) &&
				!isSystemStop(row) &&
				!isImageRevision(row) &&
				!isTextRevision(row),
		);
		const base =
			Math.max(
				0,
				...ordinary.map((row) => safeOrder(row, rows.indexOf(row) * 10)),
			) + 10;
		const revisions = rows.filter(
			(row) => isImageRevision(row) || isTextRevision(row),
		);
		for (const [index, row] of revisions.entries())
			row.style.order = String(base + index * 2);
		const stopBase = base + revisions.length * 2 + 10;
		if (stops.user) stops.user.style.order = String(stopBase);
		if (stops.system) stops.system.style.order = String(stopBase + 1);

		applyDock(scroll, rows, selected);
	} finally {
		applying = false;
	}
}

function scheduleNormalize() {
	if (scheduled) return;
	scheduled = true;
	requestAnimationFrame(() => {
		scheduled = false;
		normalizeTimeline();
	});
}

export function installCurrentActionDockDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined")
		return;
	installed = true;
	addStyle();
	const observer = new MutationObserver(scheduleNormalize);
	observer.observe(document.body, {
		childList: true,
		characterData: true,
		subtree: true,
	});
	window.addEventListener("resize", scheduleNormalize, { passive: true });
	window.addEventListener("scroll", scheduleNormalize, {
		passive: true,
		capture: true,
	});
	setInterval(scheduleNormalize, 420);
	scheduleNormalize();
}
