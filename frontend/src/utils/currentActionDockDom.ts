const STYLE_ID = "current-action-dock-style";
const TIMELINE_SELECTOR = "[data-agent-timeline-scroll='true']";
const GENERATED_ATTR = "data-current-action-generated";
const COMPACT_ATTR = "data-history-compact-row";
const DOCK_ATTR = "data-current-action-dock";
const HIDDEN_ATTR = "data-current-action-hidden";
const ORIGINAL_ORDER_ATTR = "data-current-action-original-order";

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

[${COMPACT_ATTR}="true"] { min-height: 0 !important; }

[${COMPACT_ATTR}="true"] [data-agent-card] {
	min-width: 0 !important;
	width: auto !important;
	max-width: min(36rem, calc(100vw - 5rem)) !important;
	padding: .55rem .7rem !important;
	border-radius: .8rem !important;
}

[${COMPACT_ATTR}="true"] [data-agent-card] > *:not([data-history-compact-label="true"]) {
	display: none !important;
}

[data-history-compact-label="true"] {
	display: flex;
	align-items: center;
	gap: .45rem;
	min-width: 0;
	font-size: .75rem;
	line-height: 1.15rem;
	font-weight: 650;
	color: rgb(51 65 85);
}

[data-history-status-dot] {
	width: .45rem;
	height: .45rem;
	flex: 0 0 auto;
	border-radius: 999px;
	background: rgb(59 130 246);
	box-shadow: 0 0 0 3px rgba(59,130,246,.10);
}

[data-history-state="running"] [data-history-status-dot] {
	background: rgb(16 185 129);
	box-shadow: 0 0 0 3px rgba(16,185,129,.12), 0 0 10px rgba(16,185,129,.24);
	animation: currentActionHistoryPulse 1.45s ease-in-out infinite;
}

[data-history-state="stopped"] [data-history-status-dot],
[data-history-state="warning"] [data-history-status-dot] {
	background: rgb(245 158 11);
	box-shadow: 0 0 0 3px rgba(245,158,11,.12);
}

[data-history-label-text] {
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}

[data-history-label-time] {
	margin-left: auto;
	flex: 0 0 auto;
	font-size: .625rem;
	font-weight: 500;
	color: rgb(148 163 184);
}

[${GENERATED_ATTR}="placeholder"] {
	display: flex;
	justify-content: flex-start;
	width: 100%;
}

[${GENERATED_ATTR}="placeholder"] > div {
	max-width: min(36rem, calc(100vw - 4rem));
	padding: .55rem .75rem;
	border: 1px solid rgba(148,163,184,.22);
	border-radius: .85rem;
	background: rgba(255,255,255,.82);
	box-shadow: 0 5px 16px rgba(15,23,42,.045);
	backdrop-filter: blur(12px);
}

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

@keyframes currentActionHistoryPulse {
	0%, 100% { opacity: .62; transform: scale(.88); }
	50% { opacity: 1; transform: scale(1.08); }
}

@media (prefers-reduced-motion: reduce) {
	[data-history-status-dot] { animation: none !important; }
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

function cardOf(row: HTMLElement) {
	return row.querySelector<HTMLElement>("[data-agent-card]");
}

function displayedTime(row: HTMLElement) {
	const matches = Array.from(
		textOf(row).matchAll(/\b([01]\d|2[0-3]):([0-5]\d)\b/g),
	);
	return matches.at(-1)?.[0] || "";
}

function isChoiceRow(row: HTMLElement) {
	return Boolean(row.querySelector(".choice-attachment"));
}

function isInitialProblemRow(row: HTMLElement) {
	return /已确定题目信息|题目信息题目文本/.test(textOf(row));
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

function isModelingRefinement(row: HTMLElement) {
	return /详细建模方案细化|方案细化|整体建模方案/.test(textOf(row));
}

function stateOf(row: HTMLElement): "running" | "done" | "stopped" | "warning" {
	const text = textOf(row);
	if (/已停止|任务已停止|停止指令|已中断/.test(text)) return "stopped";
	if (/失败|错误|需关注|改错/.test(text)) return "warning";
	if (/已完成|完成|成功|已确认/.test(text)) return "done";
	if (
		row.querySelector("[data-running-card='true'], .animate-spin") ||
		/正在|进行中|开始|生成中|执行中/.test(text)
	)
		return "running";
	return "done";
}

function filenameOf(text: string) {
	return (
		text.match(/([\w\-\u4e00-\u9fff]+\.(?:png|jpe?g|webp|svg))/i)?.[1] || ""
	);
}

function questionSubject(text: string) {
	const match = text.match(/(?:问题|第|Q)\s*(\d+)\s*(?:问)?/i);
	if (!match) return "";
	if (/写作/.test(text)) return `问题 ${match[1]} 的论文写作`;
	if (/改错|调试|重写/.test(text)) return `问题 ${match[1]} 的代码调试`;
	return `问题 ${match[1]} 的模型求解`;
}

function conciseLabel(row: HTMLElement, forceStart = false) {
	const text = textOf(row);
	const state = stateOf(row);
	const suffix =
		state === "done"
			? "已完成"
			: state === "stopped"
				? "已停止"
				: state === "warning"
					? "需关注"
					: "进行中";

	if (isUserStop(row)) return "用户请求停止任务";
	if (isFinalSystemStop(row)) return "任务已停止";
	if (isSystemStop(row)) return "正在安全停止当前任务";
	if (isImageRevision(row)) {
		const filename = filenameOf(text);
		const subject = filename ? `图片：${filename}` : "图片";
		return /完成|成功|已生成/.test(text)
			? `${subject}修改完成`
			: `开始修改${subject}`;
	}
	if (isTextRevision(row))
		return /完成|成功|已应用/.test(text)
			? "论文文本修改完成"
			: "开始修改论文文本";
	if (isEda(row))
		return forceStart || state === "running"
			? "开始 EDA 数据探索与代码求解"
			: `EDA 数据探索与代码求解${suffix}`;
	if (isModelingRefinement(row))
		return forceStart || state === "running"
			? "开始详细建模方案细化"
			: `详细建模方案细化${suffix}`;

	const question = questionSubject(text);
	if (question)
		return forceStart || state === "running"
			? `开始${question}`
			: `${question}${suffix}`;
	if (/论文终稿|终稿整合|整体检查/.test(text))
		return state === "running"
			? "开始论文终稿整合与质量检查"
			: `论文终稿整合与质量检查${suffix}`;
	if (/并行写作|章节写作/.test(text))
		return state === "running"
			? "开始论文各章节写作"
			: `论文各章节写作${suffix}`;

	const title = Array.from(row.querySelectorAll<HTMLElement>("span"))
		.map(textOf)
		.find((value) =>
			/开始|正在|进行中|已完成|已停止|已确认|修改|求解|写作|建模|EDA/.test(
				value,
			),
		);
	return title || text.slice(0, 72) || "任务状态更新";
}

function shouldCompact(row: HTMLElement) {
	if (!cardOf(row) || isChoiceRow(row) || isInitialProblemRow(row)) return false;
	return (
		isUserStop(row) ||
		isSystemStop(row) ||
		isImageRevision(row) ||
		isTextRevision(row) ||
		isEda(row) ||
		isModelingRefinement(row) ||
		/子问题组|模型求解|代码求解|章节写作|并行写作|终稿整合|论文终稿/.test(
			textOf(row),
		)
	);
}

function ensureCompactLabel(row: HTMLElement, value?: string) {
	const card = cardOf(row);
	if (!card) return;
	let label = card.querySelector<HTMLElement>("[data-history-compact-label='true']");
	if (!label) {
		label = document.createElement("div");
		label.dataset.historyCompactLabel = "true";
		label.innerHTML = `
			<span data-history-status-dot></span>
			<span data-history-label-text></span>
			<span data-history-label-time></span>
		`;
		card.appendChild(label);
	}
	label.dataset.historyState = stateOf(row);
	const textNode = label.querySelector<HTMLElement>("[data-history-label-text]");
	const timeNode = label.querySelector<HTMLElement>("[data-history-label-time]");
	const nextText = value || conciseLabel(row);
	if (textNode && textOf(textNode) !== nextText) textNode.textContent = nextText;
	const time = displayedTime(row);
	if (timeNode && textOf(timeNode) !== time) timeNode.textContent = time;
}

function setCompact(row: HTMLElement, compact: boolean, value?: string) {
	if (compact) {
		row.setAttribute(COMPACT_ATTR, "true");
		ensureCompactLabel(row, value);
	} else {
		row.removeAttribute(COMPACT_ATTR);
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
	if (!placeholder) {
		placeholder = document.createElement("div");
		placeholder.setAttribute(GENERATED_ATTR, "placeholder");
		placeholder.innerHTML = `
			<div>
				<div data-history-compact-label="true" data-history-state="running">
					<span data-history-status-dot></span>
					<span data-history-label-text></span>
					<span data-history-label-time></span>
				</div>
			</div>
		`;
		scroll.appendChild(placeholder);
	}
	placeholder.style.order = String(order);
	const label = placeholder.querySelector<HTMLElement>("[data-history-compact-label]");
	if (label) label.dataset.historyState = stateOf(row);
	const textNode = placeholder.querySelector<HTMLElement>("[data-history-label-text]");
	const timeNode = placeholder.querySelector<HTMLElement>("[data-history-label-time]");
	const value = conciseLabel(row, true);
	if (textNode && textOf(textNode) !== value) textNode.textContent = value;
	const time = displayedTime(row);
	if (timeNode && textOf(timeNode) !== time) timeNode.textContent = time;
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
	setCompact(selected, false);
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
		for (const row of rows) row.setAttribute(HIDDEN_ATTR, "false");
		const stops = dedupeStops(rows);
		const selected = activeRichRow(rows);

		for (const row of rows) {
			if (row === selected) continue;
			setCompact(row, shouldCompact(row));
		}

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
