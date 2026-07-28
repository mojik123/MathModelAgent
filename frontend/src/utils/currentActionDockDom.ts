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
let sequence = 0;

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
[${HIDDEN_ATTR}="true"] {
	display: none !important;
}

[${COMPACT_ATTR}="true"] {
	min-height: 0 !important;
}

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

[data-history-compact-label="true"] [data-history-status-dot] {
	width: .45rem;
	height: .45rem;
	flex: 0 0 auto;
	border-radius: 999px;
	background: rgb(59 130 246);
	box-shadow: 0 0 0 3px rgba(59,130,246,.10);
}

[data-history-compact-label="true"][data-history-state="running"] [data-history-status-dot] {
	background: rgb(16 185 129);
	box-shadow: 0 0 0 3px rgba(16,185,129,.12), 0 0 10px rgba(16,185,129,.24);
	animation: currentActionHistoryPulse 1.45s ease-in-out infinite;
}

[data-history-compact-label="true"][data-history-state="stopped"] [data-history-status-dot],
[data-history-compact-label="true"][data-history-state="warning"] [data-history-status-dot] {
	background: rgb(245 158 11);
	box-shadow: 0 0 0 3px rgba(245,158,11,.12);
}

[data-history-compact-label="true"] [data-history-label-text] {
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}

[data-history-compact-label="true"] [data-history-label-time] {
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
	background: rgba(255,255,255,.80);
	box-shadow: 0 5px 16px rgba(15,23,42,.045);
	backdrop-filter: blur(12px);
}

[${DOCK_ATTR}="true"] {
	position: sticky !important;
	bottom: 0 !important;
	z-index: 60 !important;
	order: 2147483000 !important;
	display: flex !important;
	width: 100% !important;
	max-height: min(48vh, 30rem);
	margin-top: .85rem !important;
	padding: 2.15rem .45rem .55rem !important;
	overflow-x: hidden;
	overflow-y: auto;
	border: 1px solid rgba(96,165,250,.28);
	border-radius: 1rem 1rem .35rem .35rem;
	background:
		linear-gradient(180deg, rgba(248,250,252,.96), rgba(255,255,255,.985)),
		radial-gradient(circle at 16% 0%, rgba(96,165,250,.13), transparent 34%);
	box-shadow:
		0 -14px 34px rgba(15,23,42,.09),
		0 0 0 1px rgba(255,255,255,.72) inset;
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

[${DOCK_ATTR}="true"] > div {
	width: 100% !important;
	max-width: none !important;
}

[${DOCK_ATTR}="true"] [data-agent-card] {
	width: 100% !important;
	max-width: none !important;
	box-shadow: none !important;
}

[${GENERATED_ATTR}="idle"] {
	position: sticky;
	bottom: 0;
	z-index: 55;
	order: 2147483000 !important;
	margin-top: .75rem;
	padding: .75rem .9rem;
	border: 1px solid rgba(148,163,184,.20);
	border-radius: .9rem .9rem .35rem .35rem;
	background: rgba(248,250,252,.95);
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
	[data-history-compact-label="true"] [data-history-status-dot] {
		animation: none !important;
	}
}
`;
	document.head.appendChild(style);
}

function textOf(node: Element | null) {
	return (node?.textContent || "").replace(/\s+/g, " ").trim();
}

function timeline() {
	return document.querySelector<HTMLElement>(TIMELINE_SELECTOR);
}

function rowsOf(scroll: HTMLElement) {
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
	const matches = Array.from(textOf(row).matchAll(/\b([01]\d|2[0-3]):([0-5]\d)\b/g));
	return matches.at(-1)?.[0] || "";
}

function isChoiceRow(row: HTMLElement) {
	return Boolean(row.querySelector(".choice-attachment"));
}

function isInitialProblemRow(row: HTMLElement) {
	const text = textOf(row);
	return /已确定题目信息|题目信息题目文本/.test(text);
}

function isUserStop(row: HTMLElement) {
	const text = textOf(row);
	return /用户请求安全停止当前建模工作流|用户请求停止当前建模工作流|用户请求停止任务/.test(text);
}

function isSystemStop(row: HTMLElement) {
	const text = textOf(row);
	return /停止指令已发送|正在安全停止|任务已停止|任务已安全停止|任务已中断/.test(text);
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
	const text = textOf(row);
	return /\bEDA\b|探索性数据分析|数据探索与代码求解|数据预处理与探索/i.test(text);
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

function fileNameFrom(text: string) {
	const match = text.match(/([\w\-\u4e00-\u9fff]+\.(?:png|jpe?g|webp|svg))/i);
	return match?.[1] || "";
}

function questionLabel(text: string) {
	const match = text.match(/(?:问题|第|Q)\s*(\d+)\s*(?:问)?/i);
	if (!match) return "";
	if (/写作/.test(text)) return `问题 ${match[1]} 的论文写作`;
	if (/改错|调试|重写/.test(text)) return `问题 ${match[1]} 的代码调试`;
	return `问题 ${match[1]} 的模型求解`;
}

function conciseLabel(row: HTMLElement, forceStart = false) {
	const text = textOf(row);
	const state = stateOf(row);
	const suffix = state === "done" ? "已完成" : state === "stopped" ? "已停止" : state === "warning" ? "需关注" : "进行中";

	if (isUserStop(row)) return "用户请求停止任务";
	if (isFinalSystemStop(row)) return "任务已停止";
	if (isSystemStop(row)) return "正在安全停止当前任务";
	if (isImageRevision(row)) {
		const filename = fileNameFrom(text);
		const subject = filename ? `图片：${filename}` : "图片";
		if (/完成|成功|已生成/.test(text)) return `${subject}修改完成`;
		return `开始修改${subject}`;
	}
	if (isTextRevision(row)) {
		if (/完成|成功|已应用/.test(text)) return "论文文本修改完成";
		return "开始修改论文文本";
	}
	if (isEda(row)) {
		if (forceStart || state === "running") return "开始 EDA 数据探索与代码求解";
		return `EDA 数据探索与代码求解${suffix}`;
	}
	if (isModelingRefinement(row)) {
		if (forceStart || state === "running") return "开始详细建模方案细化";
		return `详细建模方案细化${suffix}`;
	}
	const question = questionLabel(text);
	if (question) {
		if (forceStart || state === "running") return `开始${question}`;
		return `${question}${suffix}`;
	}
	if (/论文终稿|终稿整合|整体检查/.test(text)) {
		return state === "running" ? "开始论文终稿整合与质量检查" : `论文终稿整合与质量检查${suffix}`;
	}
	if (/并行写作|章节写作/.test(text)) {
		return state === "running" ? "开始论文各章节写作" : `论文各章节写作${suffix}`;
	}

	const title = Array.from(row.querySelectorAll<HTMLElement>("span"))
		.map((span) => textOf(span))
		.find((value) =>
			/开始|正在|进行中|已完成|已停止|已确认|修改|求解|写作|建模|EDA/.test(value),
		);
	return title || text.slice(0, 72) || "任务状态更新";
}

function shouldCompact(row: HTMLElement) {
	if (!cardOf(row) || isChoiceRow(row) || isInitialProblemRow(row)) return false;
	const text = textOf(row);
	return (
		isUserStop(row) ||
		isSystemStop(row) ||
		isImageRevision(row) ||
		isTextRevision(row) ||
		isEda(row) ||
		isModelingRefinement(row) ||
		/子问题组|模型求解|代码求解|章节写作|并行写作|终稿整合|论文终稿/.test(text)
	);
}

function ensureCompactLabel(row: HTMLElement, labelText?: string) {
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
	const state = stateOf(row);
	label.dataset.historyState = state;
	const textNode = label.querySelector<HTMLElement>("[data-history-label-text]");
	const timeNode = label.querySelector<HTMLElement>("[data-history-label-time]");
	const nextLabel = labelText || conciseLabel(row);
	if (textNode && textOf(textNode) !== nextLabel) textNode.textContent = nextLabel;
	const time = displayedTime(row);
	if (timeNode && textOf(timeNode) !== time) timeNode.textContent = time;
}

function setCompact(row: HTMLElement, compact: boolean, labelText?: string) {
	if (compact) {
		row.setAttribute(COMPACT_ATTR, "true");
		ensureCompactLabel(row, labelText);
	} else {
		row.removeAttribute(COMPACT_ATTR);
	}
}

function hideDuplicateStops(rows: HTMLElement[]) {
	const userStops = rows.filter(isUserStop);
	for (const [index, row] of userStops.entries()) {
		row.setAttribute(HIDDEN_ATTR, index === 0 ? "false" : "true");
	}

	const systemStops = rows.filter(isSystemStop);
	const finalStops = systemStops.filter(isFinalSystemStop);
	const keep = finalStops.at(-1) || systemStops.at(-1) || null;
	for (const row of systemStops) {
		row.setAttribute(HIDDEN_ATTR, row === keep ? "false" : "true");
	}

	return {
		userStop: userStops[0] || null,
		systemStop: keep,
	};
}

function normalizeRevisionOrder(rows: HTMLElement[], baseOrder: number) {
	const revisions = rows.filter((row) => isImageRevision(row) || isTextRevision(row));
	for (const [index, row] of revisions.entries()) {
		row.style.order = String(baseOrder + index * 2);
	}
	return revisions.length ? baseOrder + revisions.length * 2 : baseOrder;
}

function activeRichRow(rows: HTMLElement[]) {
	const running = rows.filter(
		(row) =>
			row.getAttribute(HIDDEN_ATTR) !== "true" &&
			Boolean(row.querySelector("[data-running-card='true']")),
	);
	if (running.length) return running.at(-1) || null;

	const revisions = rows.filter(
		(row) =>
			row.getAttribute(HIDDEN_ATTR) !== "true" &&
			(isImageRevision(row) || isTextRevision(row)) &&
			stateOf(row) === "running",
	);
	if (revisions.length) return revisions.at(-1) || null;

	const rich = rows.filter(
		(row) =>
			row.getAttribute(HIDDEN_ATTR) !== "true" &&
			!isChoiceRow(row) &&
			Boolean(
				row.querySelector(
					".streaming-detail, img, .message-detail, [data-running-card='true']",
				),
			) &&
			(isEda(row) || isImageRevision(row) || isTextRevision(row) || /代码求解|模型求解|写作/.test(textOf(row))),
	);
	return rich.at(-1) || null;
}

function restoreDockRow(row: HTMLElement) {
	row.removeAttribute(DOCK_ATTR);
	row.removeAttribute("data-current-action-heading");
	const originalOrder = row.getAttribute(ORIGINAL_ORDER_ATTR);
	if (originalOrder != null) row.style.order = originalOrder;
	row.removeAttribute(ORIGINAL_ORDER_ATTR);
}

function removeGenerated(scroll: HTMLElement, kind?: "placeholder" | "idle") {
	for (const node of scroll.querySelectorAll<HTMLElement>(`[${GENERATED_ATTR}]`)) {
		if (!kind || node.getAttribute(GENERATED_ATTR) === kind) node.remove();
	}
}

function ensurePlaceholder(scroll: HTMLElement, row: HTMLElement, originalOrder: string) {
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
	placeholder.style.order = originalOrder;
	const label = placeholder.querySelector<HTMLElement>("[data-history-compact-label='true']");
	if (label) label.dataset.historyState = stateOf(row);
	const labelText = placeholder.querySelector<HTMLElement>("[data-history-label-text]");
	const time = placeholder.querySelector<HTMLElement>("[data-history-label-time]");
	const concise = conciseLabel(row, true);
	if (labelText && textOf(labelText) !== concise) labelText.textContent = concise;
	const timeValue = displayedTime(row);
	if (time && textOf(time) !== timeValue) time.textContent = timeValue;
}

function ensureIdleDock(scroll: HTMLElement) {
	let idle = scroll.querySelector<HTMLElement>(`[${GENERATED_ATTR}='idle']`);
	if (!idle) {
		idle = document.createElement("div");
		idle.setAttribute(GENERATED_ATTR, "idle");
		idle.textContent = "当前动作 · 暂无正在执行的任务";
		scroll.appendChild(idle);
	}
}

function applyDock(scroll: HTMLElement, rows: HTMLElement[]) {
	const selected = activeRichRow(rows);
	for (const row of rows) {
		if (row !== selected && row.hasAttribute(DOCK_ATTR)) restoreDockRow(row);
	}

	if (!selected) {
		removeGenerated(scroll, "placeholder");
		ensureIdleDock(scroll);
		return;
	}

	removeGenerated(scroll, "idle");
	let originalOrder = selected.getAttribute(ORIGINAL_ORDER_ATTR);
	if (originalOrder == null) {
		originalOrder = selected.style.order || String(rows.indexOf(selected) * 10);
		selected.setAttribute(ORIGINAL_ORDER_ATTR, originalOrder);
	}
	selected.setAttribute(DOCK_ATTR, "true");
	selected.setAttribute(
		"data-current-action-heading",
		stateOf(selected) === "running" ? "当前动作 · 正在执行" : "当前动作 · 最近结果",
	);
	selected.style.order = "2147483000";
	setCompact(selected, false);
	ensurePlaceholder(scroll, selected, originalOrder);
}

function normalizeTimeline() {
	if (applying) return;
	const scroll = timeline();
	if (!scroll) return;
	applying = true;
	try {
		const rows = rowsOf(scroll);
		for (const row of rows) row.setAttribute(HIDDEN_ATTR, "false");

		const stops = hideDuplicateStops(rows);
		for (const row of rows) {
			if (row.hasAttribute(DOCK_ATTR)) continue;
			setCompact(row, shouldCompact(row));
		}

		const visibleOrders = rows
			.filter((row) => row.getAttribute(HIDDEN_ATTR) !== "true")
			.map((row) => Number.parseInt(row.style.order || "0", 10))
			.filter(Number.isFinite);
		const maxOrder = Math.max(0, ...visibleOrders) + 20;
		const afterRevisions = normalizeRevisionOrder(rows, maxOrder);
		if (stops.userStop) stops.userStop.style.order = String(afterRevisions + 10);
		if (stops.systemStop) stops.systemStop.style.order = String(afterRevisions + 20);

		applyDock(scroll, rows);
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
	sequence += 1;
	addStyle();
	const observer = new MutationObserver(scheduleNormalize);
	observer.observe(document.body, {
		childList: true,
		characterData: true,
		subtree: true,
	});
	setInterval(scheduleNormalize, 420 + sequence);
	scheduleNormalize();
}
