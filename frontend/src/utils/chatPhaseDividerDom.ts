const STYLE_ID = "chat-phase-divider-style";
const DIVIDER_ATTR = "data-chat-phase-divider";
const HIDDEN_ATTR = "data-chat-phase-hidden";
let installed = false;

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

function applyPhaseDividers() {
	const panel = getPanel();
	if (!panel) return;
	const scroll = getScroll(panel);
	if (!scroll) return;
	const allText = textOf(panel);
	const rows = getRows(scroll);
	const used = new Set<string>();

	for (const row of rows) setRowHidden(row, false);

	for (const phase of PHASES) {
		if (!phase.complete(allText)) continue;
		const phaseRows = rows.filter((row) => phase.match(textOf(row)));
		if (!phaseRows.length) continue;
		const lastRow = phaseRows[phaseRows.length - 1];
		const divider = ensureDivider(scroll, phase.key);
		updateDivider(divider, phase.key, phase.label, phaseRows);
		used.add(phase.key);
		if (lastRow.nextSibling !== divider) {
			scroll.insertBefore(divider, lastRow.nextSibling);
		}
		const expanded = isExpanded(phase.key);
		for (const row of phaseRows) setRowHidden(row, !expanded);
	}

	removeUnusedDividers(scroll, used);
}

export function installChatPhaseDividerDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined") return;
	installed = true;
	addStyle();
	setInterval(applyPhaseDividers, 900);
	window.addEventListener("storage", (event) => {
		if (event.key?.startsWith("chat-phase-divider:")) applyPhaseDividers();
	});
}
