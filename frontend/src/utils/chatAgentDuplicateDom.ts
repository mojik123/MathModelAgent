const STYLE_ID = "chat-agent-duplicate-style";
const HIDDEN_ATTR = "data-agent-duplicate-hidden";
const BADGE_ATTR = "data-agent-merge-badge";
let installed = false;

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
[${HIDDEN_ATTR}="true"] {
	display: none !important;
}

.agent-merge-badge {
	display: inline-flex;
	align-items: center;
	gap: 4px;
	margin-top: 8px;
	border: 1px solid rgba(59, 130, 246, .16);
	border-radius: 999px;
	background: rgba(239, 246, 255, .72);
	color: rgba(29, 78, 216, .86);
	font-size: 10px;
	font-weight: 700;
	line-height: 1;
	padding: 5px 8px;
	backdrop-filter: blur(10px);
	-webkit-backdrop-filter: blur(10px);
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
		.filter((node) => textOf(node).length > 0);
}

function setHidden(row: HTMLElement, hidden: boolean) {
	if (hidden) {
		if (row.getAttribute(HIDDEN_ATTR) !== "true") row.setAttribute(HIDDEN_ATTR, "true");
	} else if (row.hasAttribute(HIDDEN_ATTR)) {
		row.removeAttribute(HIDDEN_ATTR);
	}
}

function clearBadge(row: HTMLElement) {
	for (const badge of row.querySelectorAll<HTMLElement>(`[${BADGE_ATTR}]`)) badge.remove();
}

function collapseDuplicateAgentCards() {
	const panel = getPanel();
	if (!panel) return;
	const scroll = getScroll(panel);
	if (!scroll) return;
	const rows = getRows(scroll);

	for (const row of rows) {
		setHidden(row, false);
		clearBadge(row);
	}
}

export function installChatAgentDuplicateDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined") return;
	installed = true;
	addStyle();
	setInterval(collapseDuplicateAgentCards, 900);
}
