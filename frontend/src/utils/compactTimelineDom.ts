const STYLE_ID = "compact-timeline-progress-style";
let installed = false;

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
[data-compact-live-progress-hidden="true"] { display: none !important; }
[data-chat-duplicate-flow-overview="true"] { display: none !important; }

[data-agent-card] {
	position: relative !important;
	overflow: hidden !important;
	isolation: isolate !important;
	backdrop-filter: blur(18px) saturate(1.18) !important;
	-webkit-backdrop-filter: blur(18px) saturate(1.18) !important;
	border-width: 1px !important;
	box-shadow:
		0 10px 26px rgba(15, 23, 42, 0.055),
		inset 0 1px 0 rgba(255, 255, 255, 0.78),
		inset 0 -1px 0 rgba(255, 255, 255, 0.34) !important;
}
[data-agent-card]::before {
	content: "";
	position: absolute;
	inset: 0;
	background:
		radial-gradient(circle at 18% 0%, rgba(255,255,255,.72), transparent 34%),
		linear-gradient(135deg, rgba(255,255,255,.46), rgba(255,255,255,.16));
	pointer-events: none;
	z-index: 0;
}
[data-agent-card] > * { position: relative; z-index: 1; }

[data-agent-card="system"] { border-color: rgba(100, 116, 139, 0.22) !important; background: linear-gradient(135deg, rgba(248,250,252,.88), rgba(241,245,249,.72)) !important; }
[data-agent-card="coordinator"] { border-color: rgba(59, 130, 246, 0.24) !important; background: linear-gradient(135deg, rgba(239,246,255,.9), rgba(240,249,255,.72)) !important; }
[data-agent-card="subcoordinator"] { border-color: rgba(14, 165, 233, 0.22) !important; background: linear-gradient(135deg, rgba(240,249,255,.9), rgba(236,254,255,.70)) !important; }
[data-agent-card="modeler"] { border-color: rgba(139, 92, 246, 0.23) !important; background: linear-gradient(135deg, rgba(245,243,255,.92), rgba(250,245,255,.70)) !important; }
[data-agent-card="coder"] { border-color: rgba(20, 184, 166, 0.24) !important; background: linear-gradient(135deg, rgba(240,253,250,.92), rgba(236,253,245,.70)) !important; }
[data-agent-card="writer"] { border-color: rgba(245, 158, 11, 0.24) !important; background: linear-gradient(135deg, rgba(255,251,235,.92), rgba(255,247,237,.70)) !important; }
[data-agent-card="user"] { border-color: rgba(30, 41, 59, 0.35) !important; background: linear-gradient(135deg, rgba(15,23,42,.96), rgba(30,41,59,.92)) !important; }

[data-agent-avatar] {
	box-shadow: 0 10px 24px rgba(15,23,42,.12), inset 0 1px 0 rgba(255,255,255,.45) !important;
}
[data-agent-avatar="system"] { background: linear-gradient(135deg, #64748b, #94a3b8) !important; }
[data-agent-avatar="coordinator"] { background: linear-gradient(135deg, #2563eb, #38bdf8) !important; }
[data-agent-avatar="subcoordinator"] { background: linear-gradient(135deg, #0284c7, #22d3ee) !important; }
[data-agent-avatar="modeler"] { background: linear-gradient(135deg, #7c3aed, #c084fc) !important; }
[data-agent-avatar="coder"] { background: linear-gradient(135deg, #0f766e, #2dd4bf) !important; }
[data-agent-avatar="writer"] { background: linear-gradient(135deg, #d97706, #fbbf24) !important; }
[data-agent-avatar="user"] { background: linear-gradient(135deg, #0f172a, #334155) !important; }

[data-running-card="true"] {
	position: relative !important;
	overflow: hidden !important;
	border-color: rgba(59, 130, 246, 0.55) !important;
	box-shadow:
		0 14px 32px rgba(37, 99, 235, 0.13),
		0 0 0 1px rgba(96, 165, 250, 0.16) inset,
		inset 0 1px 0 rgba(255,255,255,.82) !important;
}
[data-running-card="true"]::before {
	content: "";
	position: absolute;
	inset: -40%;
	background:
		linear-gradient(115deg,
			transparent 0%, rgba(96, 165, 250, 0.00) 32%,
			rgba(96, 165, 250, 0.24) 43%, rgba(45, 212, 191, 0.30) 50%,
			rgba(168, 85, 247, 0.20) 57%, rgba(96, 165, 250, 0.00) 68%, transparent 100%);
	transform: translateX(-70%) rotate(4deg);
	animation: agentRunningFlow 2.4s linear infinite;
	pointer-events: none;
	z-index: 0;
}
[data-running-card="true"]::after {
	content: "运行中";
	position: absolute;
	right: 12px;
	bottom: 8px;
	font-size: 10px;
	font-weight: 700;
	letter-spacing: .04em;
	color: rgba(37, 99, 235, 0.62);
	z-index: 1;
	pointer-events: none;
}
[data-running-card="true"] > * { position: relative; z-index: 1; }

[data-stale-running-card="true"] {
	position: relative !important;
	overflow: hidden !important;
	border-color: rgba(226, 232, 240, 0.95) !important;
	background: rgba(248, 250, 252, 0.74) !important;
	box-shadow: 0 6px 16px rgba(15, 23, 42, 0.04) !important;
	opacity: 0.70;
}
[data-stale-running-card="true"] .animate-spin { animation: none !important; opacity: 0.42; }
[data-stale-running-card="true"]::after {
	content: "已进入后续";
	position: absolute;
	right: 10px;
	bottom: 7px;
	font-size: 10px;
	font-weight: 700;
	color: rgba(100, 116, 139, 0.68);
	pointer-events: none;
}

@keyframes agentRunningFlow {
	0% { transform: translateX(-72%) rotate(4deg); }
	100% { transform: translateX(72%) rotate(4deg); }
}
`;
	document.head.appendChild(style);
}

function setAttrIfChanged(node: HTMLElement, name: string, value: string | null) {
	if (value === null) {
		if (node.hasAttribute(name)) node.removeAttribute(name);
		return;
	}
	if (node.getAttribute(name) !== value) node.setAttribute(name, value);
}

function textOf(node: HTMLElement) {
	return (node.textContent || "").replace(/\s+/g, " ").trim();
}

function isLiveModelingProgress(text: string) {
	return /正在检索文献|正在生成模型方案|正在生成建模方案|生成模型方案/.test(text);
}

function isImportantCard(text: string) {
	return /候选建模方案已生成|等待用户确认|建模方案已确认|问题划分已确认|代码手开始求解|求解完成|写作完成|任务执行失败|错误/.test(text);
}

function isTerminalCard(text: string) {
	return /已确认|已完成|完成|成功|失败|错误|任务执行失败|论文终稿完成/.test(text);
}

function isActiveProgressCard(row: HTMLElement) {
	const text = textOf(row);
	if (!text || isTerminalCard(text)) return false;
	return Boolean(row.querySelector(".animate-spin")) || /正在|开始|进行中|生成中|检索文献/.test(text);
}

function getTimelineScroll(panel: HTMLElement) {
	return Array.from(panel.querySelectorAll<HTMLElement>("div")).find((node) => {
		const cls = node.getAttribute("class") || "";
		return cls.includes("overflow-y-auto") && cls.includes("space-y-4");
	}) || null;
}

function closestTimelineRow(node: HTMLElement, scroll: HTMLElement) {
	let current: HTMLElement | null = node;
	while (current && current.parentElement) {
		const parent = current.parentElement;
		const cls = current.getAttribute("class") || "";
		if (parent === scroll && (cls.includes("justify-start") || cls.includes("justify-center") || cls.includes("justify-end"))) return current;
		current = parent;
	}
	return null;
}

function getTimelineRows(panel: HTMLElement) {
	const scroll = getTimelineScroll(panel);
	if (!scroll) return [];
	return Array.from(scroll.querySelectorAll<HTMLElement>("div"))
		.map((node) => closestTimelineRow(node, scroll))
		.filter((node): node is HTMLElement => Boolean(node))
		.filter((node, index, arr) => arr.indexOf(node) === index)
		.filter((node) => textOf(node).length > 0);
}

function getMessageCard(row: HTMLElement) {
	const directCards = Array.from(row.children).flatMap((child) => Array.from(child.querySelectorAll<HTMLElement>("div")));
	return directCards.find((node) => {
		const cls = node.getAttribute("class") || "";
		return cls.includes("rounded-2xl") && cls.includes("shadow-sm") && !cls.includes("choice-attachment");
	}) || null;
}

function getAvatar(row: HTMLElement) {
	return Array.from(row.querySelectorAll<HTMLElement>("div")).find((node) => {
		const cls = node.getAttribute("class") || "";
		return cls.includes("h-8") && cls.includes("w-8") && cls.includes("rounded-full");
	}) || null;
}

function agentKind(row: HTMLElement) {
	const text = textOf(row);
	if (text.includes("User")) return "user";
	if (text.includes("CoderAgent")) return "coder";
	if (text.includes("WriterAgent")) return "writer";
	if (text.includes("ModelerAgent")) return "modeler";
	if (text.includes("SubCoordinatorAgent")) return "subcoordinator";
	if (text.includes("CoordinatorAgent")) return "coordinator";
	return "system";
}

function hideDuplicateChatFlowOverview(panel: HTMLElement) {
	const candidates = Array.from(panel.querySelectorAll<HTMLElement>("div"));
	for (const node of candidates) {
		const text = textOf(node);
		const cls = node.getAttribute("class") || "";
		const parentText = textOf(node.parentElement as HTMLElement);
		const shouldHide =
			cls.includes("rounded-2xl") &&
			cls.includes("border") &&
			cls.includes("shadow-sm") &&
			text.includes("当前流程") &&
			text.includes("确认、求解、写作与终稿状态集中显示") &&
			!parentText.includes("Agent 对话流 当前") &&
			text.length < 260;
		setAttrIfChanged(node, "data-chat-duplicate-flow-overview", shouldHide ? "true" : null);
	}
}

function decorateAgentCards(rows: HTMLElement[]) {
	const currentCards = new Set<HTMLElement>();
	const currentAvatars = new Set<HTMLElement>();
	for (const row of rows) {
		const kind = agentKind(row);
		const card = getMessageCard(row);
		if (card) {
			currentCards.add(card);
			setAttrIfChanged(card, "data-agent-card", kind);
		}
		const avatar = getAvatar(row);
		if (avatar) {
			currentAvatars.add(avatar);
			setAttrIfChanged(avatar, "data-agent-avatar", kind);
		}
	}
	const panel = document.querySelector<HTMLElement>(".glass-left-panel");
	if (!panel) return;
	for (const card of panel.querySelectorAll<HTMLElement>("[data-agent-card]")) {
		if (!currentCards.has(card)) card.removeAttribute("data-agent-card");
	}
	for (const avatar of panel.querySelectorAll<HTMLElement>("[data-agent-avatar]")) {
		if (!currentAvatars.has(avatar)) avatar.removeAttribute("data-agent-avatar");
	}
}

function compactLiveProgressRows(rows: HTMLElement[]) {
	const liveRows = rows.filter((row) => {
		const text = textOf(row);
		return isLiveModelingProgress(text) && !isImportantCard(text);
	});
	const latestLive = liveRows.at(-1) || null;
	for (const row of rows) {
		const shouldHide = liveRows.length > 1 && liveRows.includes(row) && row !== latestLive;
		setAttrIfChanged(row, "data-compact-live-progress-hidden", shouldHide ? "true" : null);
	}
}

function decorateRunningRows(rows: HTMLElement[]) {
	const visibleActiveRows = rows.filter((row) => row.getAttribute("data-compact-live-progress-hidden") !== "true" && isActiveProgressCard(row));
	const latestActive = visibleActiveRows.at(-1) || null;
	const desired = new Map<HTMLElement, "running" | "stale" | "none">();
	for (const row of rows) {
		const card = getMessageCard(row);
		if (!card) continue;
		if (!visibleActiveRows.includes(row)) desired.set(card, "none");
		else desired.set(card, row === latestActive ? "running" : "stale");
	}
	for (const [card, state] of desired.entries()) {
		setAttrIfChanged(card, "data-running-card", state === "running" ? "true" : null);
		setAttrIfChanged(card, "data-stale-running-card", state === "stale" ? "true" : null);
	}
	const panel = document.querySelector<HTMLElement>(".glass-left-panel");
	if (!panel) return;
	for (const card of panel.querySelectorAll<HTMLElement>("[data-running-card], [data-stale-running-card]")) {
		if (!desired.has(card)) {
			card.removeAttribute("data-running-card");
			card.removeAttribute("data-stale-running-card");
		}
	}
}

function compactLiveProgressCards() {
	const panel = document.querySelector<HTMLElement>(".glass-left-panel");
	if (!panel) return;
	hideDuplicateChatFlowOverview(panel);
	const rows = getTimelineRows(panel);
	decorateAgentCards(rows);
	compactLiveProgressRows(rows);
	decorateRunningRows(rows);
}

export function installCompactTimelineDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined") return;
	installed = true;
	addStyle();
	setInterval(compactLiveProgressCards, 900);
}
