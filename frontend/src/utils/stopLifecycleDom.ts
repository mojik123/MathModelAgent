const STYLE_ID = "stop-lifecycle-dom-style";
const KIND_ATTR = "data-stop-lifecycle-kind";
const HIDDEN_ATTR = "data-stop-lifecycle-hidden";
const STOPPING_ATTR = "data-stop-lifecycle-stopping";
const TERMINAL_ATTR = "data-stop-lifecycle-terminal";

let installed = false;
let scheduled = false;

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
+[${HIDDEN_ATTR}="true"] {
+	display: none !important;
+}
+
+[${TERMINAL_ATTR}="true"] [data-agent-card],
+[${TERMINAL_ATTR}="true"] [data-running-card],
+[${TERMINAL_ATTR}="true"] [data-stale-running-card] {
+	animation: none !important;
+	border-color: rgb(203 213 225) !important;
+	background: linear-gradient(135deg, rgba(248, 250, 252, .98), rgba(241, 245, 249, .94)) !important;
+	box-shadow: 0 1px 3px rgba(15, 23, 42, .08) !important;
+}
+
+[${TERMINAL_ATTR}="true"] .animate-spin,
+[${TERMINAL_ATTR}="true"] [class*="animate-pulse"] {
+	display: none !important;
+}
+
+[${TERMINAL_ATTR}="true"] [data-stop-lifecycle-status="true"] {
+	border-color: rgb(203 213 225) !important;
+	background: rgb(241 245 249) !important;
+	color: rgb(71 85 105) !important;
+}
+
+[${STOPPING_ATTR}="true"] [data-stop-lifecycle-status="true"] {
+	border-color: rgb(253 230 138) !important;
+	background: rgb(254 252 232) !important;
+	color: rgb(161 98 7) !important;
+}
+`;
	document.head.appendChild(style);
}

function textOf(node: Element | null) {
	return (node?.textContent || "").replace(/\s+/g, " ").trim();
}

function getTimelineScroll() {
	return document.querySelector<HTMLElement>(
		"[data-agent-timeline-scroll='true']",
	);
}

function getRows(scroll: HTMLElement) {
	return Array.from(scroll.children).filter(
		(node): node is HTMLElement =>
			node instanceof HTMLElement && textOf(node).length > 0,
	);
}

function getCard(row: HTMLElement) {
	return (
		row.querySelector<HTMLElement>("[data-agent-card]") ||
		Array.from(row.querySelectorAll<HTMLElement>("div")).find((node) => {
			const cls = node.getAttribute("class") || "";
			return cls.includes("rounded-2xl") && cls.includes("shadow-sm");
		}) ||
		null
	);
}

function stopKind(row: HTMLElement): "request" | "final" | "" {
	const stored = row.getAttribute(KIND_ATTR);
	if (stored === "request" || stored === "final") return stored;
	const text = textOf(row);
	if (!/SystemMonitor|流程监控/.test(text)) return "";
	if (/停止指令已发送|正在安全停止当前步骤|安全停止当前步骤/.test(text)) {
		row.setAttribute(KIND_ATTR, "request");
		return "request";
	}
	if (/任务已停止/.test(text)) {
		row.setAttribute(KIND_ATTR, "final");
		return "final";
	}
	return "";
}

function titleNode(card: HTMLElement) {
	const container = Array.from(card.querySelectorAll<HTMLElement>("div")).find(
		(node) => {
			const cls = node.getAttribute("class") || "";
			return (
				cls.includes("text-sm") &&
				cls.includes("font-semibold") &&
				/停止/.test(textOf(node))
			);
		},
	);
	if (!container) return null;
	return (
		Array.from(container.children)
			.filter((node): node is HTMLElement => node instanceof HTMLElement)
			.filter((node) => node.tagName === "SPAN")
			.at(-1) || null
	);
}

function setTitle(card: HTMLElement, value: string) {
	const node = titleNode(card);
	if (node && textOf(node) !== value) node.textContent = value;
}

function setDetail(card: HTMLElement, value: string) {
	const details = Array.from(
		card.querySelectorAll<HTMLElement>("p.message-detail"),
	).filter((node) => /停止/.test(textOf(node)));
	for (const [index, detail] of details.entries()) {
		if (index === 0) {
			if (textOf(detail) !== value) detail.textContent = value;
			detail.style.display = "";
		} else {
			detail.style.display = "none";
		}
	}
}

function setStatus(card: HTMLElement, value: "停止中" | "已停止") {
	const candidates = Array.from(
		card.querySelectorAll<HTMLElement>("span, div"),
	).filter((node) => {
		if (node.children.length) return false;
		return /^(运行中|进行中|停止中|已停止)$/.test(textOf(node));
	});
	for (const node of candidates) {
		if (textOf(node) !== value) node.textContent = value;
		node.setAttribute("data-stop-lifecycle-status", "true");
	}
}

function normalizeStopping(row: HTMLElement) {
	row.setAttribute(STOPPING_ATTR, "true");
	row.removeAttribute(TERMINAL_ATTR);
	row.removeAttribute(HIDDEN_ATTR);
	const card = getCard(row);
	if (!card) return;
	setTitle(card, "正在安全停止当前步骤");
	setDetail(card, "停止指令已发送，等待当前步骤安全退出。");
	setStatus(card, "停止中");
}

function normalizeTerminal(primary: HTMLElement, duplicate?: HTMLElement) {
	primary.setAttribute(TERMINAL_ATTR, "true");
	primary.removeAttribute(STOPPING_ATTR);
	primary.removeAttribute(HIDDEN_ATTR);
	const card = getCard(primary);
	if (card) {
		card.removeAttribute("data-running-card");
		card.removeAttribute("data-stale-running-card");
		setTitle(card, "任务已停止");
		setDetail(card, "停止指令已完成，当前步骤已安全终止。");
		setStatus(card, "已停止");
	}
	if (duplicate && duplicate !== primary) {
		duplicate.setAttribute(HIDDEN_ATTR, "true");
		duplicate.removeAttribute(STOPPING_ATTR);
		duplicate.removeAttribute(TERMINAL_ATTR);
	}
}

function mergeStopLifecycle() {
	const scroll = getTimelineScroll();
	if (!scroll) return;
	const rows = getRows(scroll);
	for (const row of rows) {
		if (!stopKind(row)) continue;
		row.removeAttribute(HIDDEN_ATTR);
		row.removeAttribute(STOPPING_ATTR);
		row.removeAttribute(TERMINAL_ATTR);
	}

	let pendingRequest: HTMLElement | null = null;
	for (const row of rows) {
		const kind = stopKind(row);
		if (kind === "request") {
			if (pendingRequest) normalizeStopping(pendingRequest);
			pendingRequest = row;
			continue;
		}
		if (kind !== "final") continue;
		if (pendingRequest) {
			normalizeTerminal(pendingRequest, row);
			pendingRequest = null;
		} else {
			normalizeTerminal(row);
		}
	}
	if (pendingRequest) normalizeStopping(pendingRequest);
}

function scheduleMerge() {
	if (scheduled) return;
	scheduled = true;
	requestAnimationFrame(() => {
		scheduled = false;
		mergeStopLifecycle();
	});
}

export function installStopLifecycleDomPatch() {
	if (
		installed ||
		typeof window === "undefined" ||
		typeof document === "undefined"
	) {
		return;
	}
	installed = true;
	addStyle();
	const observer = new MutationObserver(scheduleMerge);
	observer.observe(document.body, {
		childList: true,
		subtree: true,
		characterData: true,
	});
	window.setInterval(scheduleMerge, 700);
	scheduleMerge();
}
