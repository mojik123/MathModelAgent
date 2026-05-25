const STYLE_ID = "chat-phase-divider-style";
const DIVIDER_ATTR = "data-chat-phase-divider";
const HIDDEN_ATTR = "data-chat-phase-hidden";
const EDGE_ATTR = "data-chat-phase-edge-marker";
const EDGE_CONTAINER_ATTR = "data-chat-phase-edge-container";
let installed = false;
let scrollListenerBoundTo: HTMLElement | null = null;

const PHASES = [
	{
		key: "planning",
		label: "问题拆解与建模思路讨论",
		complete: (text: string) => /建模方案已确认|已确认建模方案|开始进入代码求解|代码手开始求解|子问题组#\d+.*启动/.test(text),
		match: (text: string) => /问题划分|问题确认|建模方案|建模确认|建模思路|候选建模|ModelerAgent|CoordinatorAgent|问题划分附件|建模方案附件|已确认问题划分|已确认建模方案/.test(text),
	},
	{
		key: "solving",
		label: "问题求解",
		complete: (text: string) => /论文手开始写|并行写作启动|开始终稿整体检查|论文手完成|论文生成完成/.test(text),
		match: (text: string) => /子问题组|代码求解|CoderAgent|SubCoordinatorAgent|开始求解|求解完成|改错|后台判别|备用\s*Coder|重写中/.test(text),
	},
	{
		key: "writing",
		label: "论文写作",
		complete: (text: string) => /论文手完成|完成终稿整体检查|论文生成完成|任务处理完成/.test(text),
		match: (text: string) => /并行写作|论文手开始写|论文手完成|WriterAgent|论文写作|章节写作|写作完成/.test(text) && !/终稿整体检查|论文终稿完成/.test(text),
	},
] as const;

type PhaseKey = (typeof PHASES)[number]["key"];
type EdgePosition = "top" | "bottom";

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
[${HIDDEN_ATTR}="true"] {
	display: none !important;
}

.chat-phase-divider {
	position: relative;
	width: 100%;
	margin: 10px 0;
	padding: 0;
	border: 0;
	background: transparent;
	cursor: pointer;
	color: #475569;
}

.chat-phase-divider::before {
	content: "";
	position: absolute;
	left: 0;
	right: 0;
	top: 50%;
	height: 1px;
	background: linear-gradient(90deg, transparent, rgba(148, 163, 184, .55), transparent);
}

.chat-phase-divider-inner {
	position: relative;
	z-index: 1;
	margin: 0 auto;
	display: flex;
	width: fit-content;
	max-width: min(92%, 520px);
	align-items: center;
	gap: 8px;
	border: 1px solid rgba(191, 219, 254, .9);
	border-radius: 999px;
	background:
		radial-gradient(circle at 14% 0%, rgba(255,255,255,.92), transparent 34%),
		linear-gradient(135deg, rgba(239,246,255,.96), rgba(255,255,255,.82));
	box-shadow: 0 10px 26px rgba(37, 99, 235, .08), inset 0 1px 0 rgba(255,255,255,.82);
	padding: 6px 12px;
	font-size: 11px;
	font-weight: 700;
	backdrop-filter: blur(14px) saturate(1.1);
	-webkit-backdrop-filter: blur(14px) saturate(1.1);
}

.chat-phase-divider-icon {
	display: inline-flex;
	height: 18px;
	width: 18px;
	align-items: center;
	justify-content: center;
	border-radius: 999px;
	background: rgba(37, 99, 235, .1);
	color: #2563eb;
	font-size: 10px;
}

.chat-phase-divider-title {
	white-space: nowrap;
	color: #1e3a8a;
}

.chat-phase-divider-meta {
	white-space: nowrap;
	color: rgba(71, 85, 105, .78);
	font-weight: 600;
}

.chat-phase-divider[data-phase-expanded="true"] {
	margin-bottom: 8px;
}

.chat-phase-divider[data-phase-warning="true"] .chat-phase-divider-inner {
	border-color: rgba(252, 211, 77, .95);
	background: linear-gradient(135deg, rgba(255,251,235,.96), rgba(255,255,255,.82));
}

.chat-phase-divider[data-phase-warning="true"] .chat-phase-divider-icon {
	background: rgba(245, 158, 11, .12);
	color: #b45309;
}

.chat-phase-divider[data-phase-warning="true"] .chat-phase-divider-title {
	color: #92400e;
}

.chat-phase-edge-container {
	position: fixed;
	z-index: 60;
	display: none;
	flex-direction: column;
	align-items: center;
	gap: 3px;
	border: 0;
	background: transparent;
	padding: 0;
	pointer-events: none;
}

.chat-phase-edge-marker {
	display: flex;
	width: 100%;
	justify-content: center;
	border: 0;
	background: transparent;
	padding: 0;
	pointer-events: none;
}

.chat-phase-edge-marker-inner {
	display: inline-flex;
	max-width: min(100%, 520px);
	align-items: center;
	gap: 6px;
	border: 1px solid rgba(191, 219, 254, .95);
	border-radius: 999px;
	background:
		radial-gradient(circle at 14% 0%, rgba(255,255,255,.96), transparent 34%),
		linear-gradient(135deg, rgba(239,246,255,.94), rgba(255,255,255,.78));
	box-shadow: 0 10px 24px rgba(37, 99, 235, .11), inset 0 1px 0 rgba(255,255,255,.86);
	padding: 4px 9px;
	font-size: 10px;
	font-weight: 800;
	line-height: 1.15;
	color: #1e3a8a;
	backdrop-filter: blur(16px) saturate(1.16);
	-webkit-backdrop-filter: blur(16px) saturate(1.16);
	pointer-events: auto;
	cursor: pointer;
	transition: transform .16s ease, box-shadow .16s ease;
}

.chat-phase-edge-marker-inner:hover {
	transform: translateY(-1px);
	box-shadow: 0 14px 32px rgba(37, 99, 235, .17), inset 0 1px 0 rgba(255,255,255,.9);
}

.chat-phase-edge-container[data-edge="bottom"] .chat-phase-edge-marker-inner:hover {
	transform: translateY(1px);
}

.chat-phase-edge-marker-icon {
	display: inline-flex;
	height: 15px;
	width: 15px;
	align-items: center;
	justify-content: center;
	flex: 0 0 auto;
	border-radius: 999px;
	background: rgba(37, 99, 235, .1);
	color: #2563eb;
	font-size: 9px;
}

.chat-phase-edge-marker-title {
	min-width: 0;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}

.chat-phase-edge-marker-meta {
	white-space: nowrap;
	color: rgba(71, 85, 105, .72);
	font-weight: 700;
}

.chat-phase-edge-marker[data-phase-warning="true"] .chat-phase-edge-marker-inner {
	border-color: rgba(252, 211, 77, .95);
	background: linear-gradient(135deg, rgba(255,251,235,.94), rgba(255,255,255,.80));
	box-shadow: 0 10px 24px rgba(245, 158, 11, .14), inset 0 1px 0 rgba(255,255,255,.86);
	color: #92400e;
}

.chat-phase-edge-marker[data-phase-warning="true"] .chat-phase-edge-marker-icon {
	background: rgba(245, 158, 11, .12);
	color: #b45309;
}
`;
	document.head.appendChild(style);
}

function textOf(node: Element | null) {
	return (node?.textContent || "").replace(/\s+/g, " ").trim();
}

function getPanel() {
	return document.querySelector<HTMLElement>(".glass-left-panel");
}

function getScroll(panel: HTMLElement) {
	return Array.from(panel.querySelectorAll<HTMLElement>("div"))
		.find((node) => {
			const cls = node.getAttribute("class") || "";
			return cls.includes("overflow-y-auto") && cls.includes("space-y-4");
		}) || null;
}

function getRows(scroll: HTMLElement) {
	return Array.from(scroll.children)
		.filter((node): node is HTMLElement => node instanceof HTMLElement)
		.filter((node) => !node.hasAttribute(DIVIDER_ATTR))
		.filter((node) => !node.hasAttribute(EDGE_ATTR))
		.filter((node) => !node.hasAttribute(EDGE_CONTAINER_ATTR))
		.filter((node) => textOf(node).length > 0);
}

function storageKey(taskId: string, phase: PhaseKey) {
	return `chat-phase-divider:${taskId}:${phase}:expanded`;
}

function currentTaskId() {
	return window.location.pathname.match(/\/task\/([^/]+)/)?.[1] || window.localStorage.getItem("currentTaskId") || "default";
}

function isExpanded(phase: PhaseKey) {
	return window.localStorage.getItem(storageKey(currentTaskId(), phase)) === "true";
}

function setExpanded(phase: PhaseKey, expanded: boolean) {
	window.localStorage.setItem(storageKey(currentTaskId(), phase), expanded ? "true" : "false");
}

function ensureDivider(scroll: HTMLElement, phase: PhaseKey) {
	let node = scroll.querySelector<HTMLElement>(`[${DIVIDER_ATTR}="${phase}"]`);
	if (!node) {
		node = document.createElement("button");
		node.type = "button";
		node.className = "chat-phase-divider";
		node.setAttribute(DIVIDER_ATTR, phase);
		node.addEventListener("click", () => {
			setExpanded(phase, !isExpanded(phase));
			requestAnimationFrame(applyPhaseDividers);
		});
	}
	return node;
}

function updateDivider(node: HTMLElement, phase: PhaseKey, label: string, rows: HTMLElement[]) {
	const expanded = isExpanded(phase);
	const warning = rows.some((row) => /失败|错误|改错|后台判别|需关注|停止/.test(textOf(row)));
	node.dataset.phaseExpanded = expanded ? "true" : "false";
	node.dataset.phaseWarning = warning ? "true" : "false";
	node.dataset.phaseLabel = label;
	node.dataset.phaseCount = String(rows.length);
	node.innerHTML = `
		<span class="chat-phase-divider-inner">
			<span class="chat-phase-divider-icon">${expanded ? "⌃" : "⌄"}</span>
			<span class="chat-phase-divider-title">已完成：${label}</span>
			<span class="chat-phase-divider-meta">${rows.length} 条记录 · ${expanded ? "点击折叠" : "点击展开"}</span>
		</span>
	`;
}

function setRowHidden(row: HTMLElement, hidden: boolean) {
	if (hidden) {
		if (row.getAttribute(HIDDEN_ATTR) !== "true") row.setAttribute(HIDDEN_ATTR, "true");
	} else if (row.hasAttribute(HIDDEN_ATTR)) {
		row.removeAttribute(HIDDEN_ATTR);
	}
}

function removeUnusedDividers(scroll: HTMLElement, used: Set<string>) {
	for (const divider of Array.from(scroll.querySelectorAll<HTMLElement>(`[${DIVIDER_ATTR}]`))) {
		const key = divider.getAttribute(DIVIDER_ATTR) || "";
		if (!used.has(key)) divider.remove();
	}
}

function ensureEdgeContainer(edge: EdgePosition) {
	let container = document.querySelector<HTMLElement>(`[${EDGE_CONTAINER_ATTR}="${edge}"]`);
	if (!container) {
		container = document.createElement("div");
		container.className = "chat-phase-edge-container";
		container.setAttribute(EDGE_CONTAINER_ATTR, edge);
		container.dataset.edge = edge;
		document.body.appendChild(container);
	}
	return container;
}

function hideEdgeContainer(edge: EdgePosition) {
	const container = document.querySelector<HTMLElement>(`[${EDGE_CONTAINER_ATTR}="${edge}"]`);
	if (!container) return;
	container.style.display = "none";
	container.innerHTML = "";
}

function hideAllEdgeMarkers() {
	hideEdgeContainer("top");
	hideEdgeContainer("bottom");
}

function positionEdgeContainer(container: HTMLElement, scroll: HTMLElement, edge: EdgePosition) {
	const rect = scroll.getBoundingClientRect();
	container.style.left = `${Math.max(0, rect.left + 10)}px`;
	container.style.width = `${Math.max(120, rect.width - 20)}px`;
	container.style.top = edge === "top" ? `${rect.top + 6}px` : "auto";
	container.style.bottom = edge === "bottom" ? `${Math.max(6, window.innerHeight - rect.bottom + 6)}px` : "auto";
}

function scrollToDivider(phase: string) {
	const panel = getPanel();
	const scroll = panel ? getScroll(panel) : null;
	const divider = scroll?.querySelector<HTMLElement>(`[${DIVIDER_ATTR}="${phase}"]`);
	divider?.scrollIntoView({ block: "center", behavior: "smooth" });
	setTimeout(updateEdgeMarkers, 260);
}

function createEdgeMarker(edge: EdgePosition, divider: HTMLElement) {
	const phase = divider.getAttribute(DIVIDER_ATTR) || "";
	const label = divider.dataset.phaseLabel || "阶段";
	const count = divider.dataset.phaseCount || "0";
	const expanded = divider.dataset.phaseExpanded === "true";
	const warning = divider.dataset.phaseWarning === "true";
	const marker = document.createElement("button");
	marker.type = "button";
	marker.className = "chat-phase-edge-marker";
	marker.setAttribute(EDGE_ATTR, edge);
	marker.dataset.edge = edge;
	marker.dataset.targetPhase = phase;
	marker.dataset.phaseWarning = warning ? "true" : "false";
	marker.addEventListener("click", () => scrollToDivider(phase));
	marker.innerHTML = `
		<span class="chat-phase-edge-marker-inner">
			<span class="chat-phase-edge-marker-icon">${edge === "top" ? "↑" : "↓"}</span>
			<span class="chat-phase-edge-marker-title">已完成：${label}</span>
			<span class="chat-phase-edge-marker-meta">${count}条 · ${expanded ? "展开" : "折叠"}</span>
		</span>
	`;
	return marker;
}

function showEdgeMarkers(edge: EdgePosition, dividers: HTMLElement[], scroll: HTMLElement) {
	const container = ensureEdgeContainer(edge);
	container.innerHTML = "";
	if (!dividers.length) {
		container.style.display = "none";
		return;
	}
	positionEdgeContainer(container, scroll, edge);
	container.style.display = "flex";
	for (const divider of dividers) {
		container.appendChild(createEdgeMarker(edge, divider));
	}
}

function updateEdgeMarkers() {
	const panel = getPanel();
	if (!panel) {
		hideAllEdgeMarkers();
		return;
	}
	const scroll = getScroll(panel);
	if (!scroll) {
		hideAllEdgeMarkers();
		return;
	}
	const dividers = Array.from(scroll.querySelectorAll<HTMLElement>(`[${DIVIDER_ATTR}]`));
	if (!dividers.length) {
		hideAllEdgeMarkers();
		return;
	}
	const scrollRect = scroll.getBoundingClientRect();
	const topLimit = scrollRect.top + 8;
	const bottomLimit = scrollRect.bottom - 8;
	const dividerRects = dividers.map((divider) => ({ divider, rect: divider.getBoundingClientRect() }));
	const above = dividerRects
		.filter((item) => item.rect.bottom < topLimit)
		.sort((a, b) => a.rect.top - b.rect.top)
		.map((item) => item.divider);
	const below = dividerRects
		.filter((item) => item.rect.top > bottomLimit)
		.sort((a, b) => a.rect.top - b.rect.top)
		.map((item) => item.divider);

	showEdgeMarkers("top", above, scroll);
	showEdgeMarkers("bottom", below, scroll);
}

function bindScrollListener(scroll: HTMLElement) {
	if (scrollListenerBoundTo === scroll) return;
	if (scrollListenerBoundTo) {
		scrollListenerBoundTo.removeEventListener("scroll", updateEdgeMarkers);
	}
	scrollListenerBoundTo = scroll;
	scroll.addEventListener("scroll", updateEdgeMarkers, { passive: true });
}

function applyPhaseDividers() {
	const panel = getPanel();
	if (!panel) {
		hideAllEdgeMarkers();
		return;
	}
	const scroll = getScroll(panel);
	if (!scroll) {
		hideAllEdgeMarkers();
		return;
	}
	bindScrollListener(scroll);
	const allText = textOf(panel);
	const rows = getRows(scroll);
	const used = new Set<string>();

	for (const row of rows) setRowHidden(row, false);

	for (const phase of PHASES) {
		if (!phase.complete(allText)) continue;
		const phaseRows = rows.filter((row) => phase.match(textOf(row)));
		if (!phaseRows.length) continue;
		const firstRow = phaseRows[0];
		const divider = ensureDivider(scroll, phase.key);
		updateDivider(divider, phase.key, phase.label, phaseRows);
		used.add(phase.key);
		// Anchor the fold control at the original start of the phase block.
		// The divider must not follow later messages or drift to the end of the hidden block.
		if (divider.nextSibling !== firstRow) {
			scroll.insertBefore(divider, firstRow);
		}
		const expanded = isExpanded(phase.key);
		for (const row of phaseRows) setRowHidden(row, !expanded);
	}

	removeUnusedDividers(scroll, used);
	updateEdgeMarkers();
}

export function installChatPhaseDividerDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined") return;
	installed = true;
	addStyle();
	setInterval(applyPhaseDividers, 900);
	window.addEventListener("resize", updateEdgeMarkers);
	window.addEventListener("storage", (event) => {
		if (event.key?.startsWith("chat-phase-divider:")) applyPhaseDividers();
	});
}
