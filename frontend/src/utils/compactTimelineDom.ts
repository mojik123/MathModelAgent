const STYLE_ID = "compact-timeline-progress-style";
let installed = false;

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
[data-compact-live-progress-hidden="true"] {
	display: none !important;
}

[data-running-card="true"] {
	position: relative !important;
	overflow: hidden !important;
	border-color: rgba(59, 130, 246, 0.55) !important;
	background:
		linear-gradient(135deg, rgba(239, 246, 255, 0.98), rgba(240, 253, 250, 0.94), rgba(245, 243, 255, 0.96)) !important;
	box-shadow:
		0 12px 28px rgba(37, 99, 235, 0.12),
		0 0 0 1px rgba(96, 165, 250, 0.12) inset !important;
}

[data-running-card="true"]::before {
	content: "";
	position: absolute;
	inset: -40%;
	background:
		linear-gradient(115deg,
			transparent 0%,
			rgba(96, 165, 250, 0.00) 32%,
			rgba(96, 165, 250, 0.28) 43%,
			rgba(45, 212, 191, 0.34) 50%,
			rgba(168, 85, 247, 0.24) 57%,
			rgba(96, 165, 250, 0.00) 68%,
			transparent 100%);
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
}

[data-running-card="true"] > * {
	position: relative;
	z-index: 1;
}

[data-stale-running-card="true"] {
	position: relative !important;
	overflow: hidden !important;
	border-color: rgba(226, 232, 240, 0.95) !important;
	background: rgba(248, 250, 252, 0.92) !important;
	box-shadow: 0 6px 16px rgba(15, 23, 42, 0.05) !important;
	opacity: 0.74;
}

[data-stale-running-card="true"] .animate-spin {
	animation: none !important;
	opacity: 0.42;
}

[data-stale-running-card="true"]::after {
	content: "已进入后续";
	position: absolute;
	right: 10px;
	bottom: 7px;
	font-size: 10px;
	font-weight: 700;
	color: rgba(100, 116, 139, 0.68);
}

@keyframes agentRunningFlow {
	0% { transform: translateX(-72%) rotate(4deg); }
	100% { transform: translateX(72%) rotate(4deg); }
}
`;
	document.head.appendChild(style);
}

function isLiveModelingProgress(text: string) {
	return (
		/正在检索文献/.test(text) ||
		/正在生成模型方案/.test(text) ||
		/正在生成建模方案/.test(text) ||
		/生成模型方案/.test(text)
	);
}

function isImportantCard(text: string) {
	return (
		/候选建模方案已生成/.test(text) ||
		/等待用户确认/.test(text) ||
		/建模方案已确认/.test(text) ||
		/问题划分已确认/.test(text) ||
		/代码手开始求解/.test(text) ||
		/求解完成/.test(text) ||
		/写作完成/.test(text) ||
		/任务执行失败/.test(text) ||
		/错误/.test(text)
	);
}

function isTerminalCard(text: string) {
	return (
		/已确认/.test(text) ||
		/已完成/.test(text) ||
		/完成/.test(text) ||
		/成功/.test(text) ||
		/失败/.test(text) ||
		/错误/.test(text) ||
		/任务执行失败/.test(text) ||
		/论文终稿完成/.test(text)
	);
}

function isActiveProgressCard(row: HTMLElement) {
	const text = row.textContent || "";
	if (!text.trim()) return false;
	if (isTerminalCard(text)) return false;
	return (
		Boolean(row.querySelector(".animate-spin")) ||
		/正在/.test(text) ||
		/开始/.test(text) ||
		/进行中/.test(text) ||
		/生成中/.test(text) ||
		/检索文献/.test(text)
	);
}

function closestTimelineRow(node: HTMLElement) {
	let current: HTMLElement | null = node;
	while (current && current.parentElement) {
		const parent = current.parentElement;
		const cls = current.getAttribute("class") || "";
		const parentCls = parent.getAttribute("class") || "";
		if (
			(cls.includes("justify-start") || cls.includes("justify-center")) &&
			parentCls.includes("overflow-y-auto")
		) {
			return current;
		}
		current = parent;
	}
	return node;
}

function getTimelineRows(panel: HTMLElement) {
	return Array.from(panel.querySelectorAll<HTMLElement>("div"))
		.map((node) => closestTimelineRow(node))
		.filter((node, index, arr) => arr.indexOf(node) === index)
		.filter((node) => (node.textContent || "").trim().length > 0);
}

function getMessageCard(row: HTMLElement) {
	const cards = Array.from(row.querySelectorAll<HTMLElement>("div"));
	return (
		cards.find((node) => {
			const cls = node.getAttribute("class") || "";
			return cls.includes("rounded-2xl") && cls.includes("shadow-sm") && !cls.includes("choice-attachment");
		}) || row
	);
}

function resetRuntimeDecorations(panel: HTMLElement) {
	for (const node of panel.querySelectorAll<HTMLElement>(
		"[data-running-card], [data-stale-running-card]",
	)) {
		node.removeAttribute("data-running-card");
		node.removeAttribute("data-stale-running-card");
	}
}

function compactLiveProgressCards() {
	const panel = document.querySelector<HTMLElement>(".glass-left-panel");
	if (!panel) return;
	resetRuntimeDecorations(panel);

	const rows = getTimelineRows(panel);
	const liveModelingRows = rows.filter((node) => {
		const text = node.textContent || "";
		return isLiveModelingProgress(text) && !isImportantCard(text);
	});

	if (liveModelingRows.length <= 1) {
		for (const node of liveModelingRows) node.removeAttribute("data-compact-live-progress-hidden");
	} else {
		const latest = liveModelingRows[liveModelingRows.length - 1];
		for (const node of liveModelingRows) {
			node.setAttribute(
				"data-compact-live-progress-hidden",
				node === latest ? "false" : "true",
			);
		}
		latest.removeAttribute("data-compact-live-progress-hidden");
	}

	const activeRows = rows.filter(
		(row) => row.getAttribute("data-compact-live-progress-hidden") !== "true" && isActiveProgressCard(row),
	);
	if (!activeRows.length) return;

	const latestActive = activeRows[activeRows.length - 1];
	for (const row of activeRows) {
		const card = getMessageCard(row);
		if (row === latestActive) {
			card.setAttribute("data-running-card", "true");
			card.removeAttribute("data-stale-running-card");
		} else {
			card.setAttribute("data-stale-running-card", "true");
			card.removeAttribute("data-running-card");
		}
	}
}

export function installCompactTimelineDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined") return;
	installed = true;
	addStyle();
	setInterval(compactLiveProgressCards, 350);
}
