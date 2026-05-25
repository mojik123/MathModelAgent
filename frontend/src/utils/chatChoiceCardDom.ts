const STYLE_ID = "chat-choice-card-dom-style";
const HIDDEN_ATTR = "data-choice-card-duplicate-hidden";
const PINNED_ATTR = "data-choice-card-pinned-latest";
let installed = false;

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
[${HIDDEN_ATTR}="true"] {
	display: none !important;
}

[${PINNED_ATTR}="true"] {
	margin-top: 10px !important;
}

[${PINNED_ATTR}="true"]::before {
	content: "当前待确认";
	display: flex;
	width: fit-content;
	margin: 0 auto 6px auto;
	border: 1px solid rgba(96, 165, 250, .28);
	border-radius: 999px;
	background: rgba(239, 246, 255, .88);
	padding: 3px 9px;
	font-size: 10px;
	font-weight: 700;
	color: rgba(29, 78, 216, .9);
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

function choiceKind(row: HTMLElement): "question" | "modeling" | "" {
	const text = textOf(row);
	if (text.includes("问题划分附件") || text.includes("问题划分已生成，请确认")) return "question";
	if (text.includes("建模方案附件") || text.includes("候选建模方案已生成，请选择")) return "modeling";
	return "";
}

function isPendingChoice(row: HTMLElement) {
	const text = textOf(row);
	return /待确认|需要用户确认|请确认|请选择|确认问题划分|确认各问建模方案|确认建模方案/.test(text)
		&& !/已确认问题划分|问题划分已确认|已确认建模方案|建模方案已确认/.test(text);
}

function setHidden(row: HTMLElement, hidden: boolean) {
	if (hidden) {
		if (row.getAttribute(HIDDEN_ATTR) !== "true") row.setAttribute(HIDDEN_ATTR, "true");
	} else if (row.hasAttribute(HIDDEN_ATTR)) {
		row.removeAttribute(HIDDEN_ATTR);
	}
}

function setPinned(row: HTMLElement, pinned: boolean) {
	if (pinned) {
		if (row.getAttribute(PINNED_ATTR) !== "true") row.setAttribute(PINNED_ATTR, "true");
	} else if (row.hasAttribute(PINNED_ATTR)) {
		row.removeAttribute(PINNED_ATTR);
	}
}

function latestByKind(rows: HTMLElement[], kind: "question" | "modeling") {
	return rows.filter((row) => choiceKind(row) === kind).at(-1) || null;
}

function hasLaterGenerationRows(rows: HTMLElement[], choiceRow: HTMLElement, kind: "question" | "modeling") {
	const index = rows.indexOf(choiceRow);
	if (index < 0) return false;
	const later = rows.slice(index + 1).map(textOf).join("\n");
	if (kind === "question") {
		return /问题划分|拆解|CoordinatorAgent|正在思考与生成|输出结果摘要/.test(later);
	}
	return /第\s*\d+\s*问|Q\d+|建模方案|生成模型方案|生成建模方案|ModelerAgent|正在思考与生成|输出结果摘要/.test(later);
}

function movePendingChoiceToLatest(scroll: HTMLElement, rows: HTMLElement[], row: HTMLElement, kind: "question" | "modeling") {
	if (!isPendingChoice(row)) {
		setPinned(row, false);
		return;
	}
	const shouldMove = hasLaterGenerationRows(rows, row, kind) || row !== rows.at(-1);
	if (!shouldMove) {
		setPinned(row, false);
		return;
	}
	setPinned(row, true);
	scroll.appendChild(row);
}

function normalizeChoiceCards() {
	const panel = getPanel();
	if (!panel) return;
	const scroll = getScroll(panel);
	if (!scroll) return;
	const rows = getRows(scroll);

	for (const row of rows) {
		if (row.hasAttribute(HIDDEN_ATTR)) row.removeAttribute(HIDDEN_ATTR);
		if (row.hasAttribute(PINNED_ATTR)) row.removeAttribute(PINNED_ATTR);
	}

	for (const kind of ["question", "modeling"] as const) {
		const choiceRows = rows.filter((row) => choiceKind(row) === kind);
		if (!choiceRows.length) continue;
		const latest = latestByKind(rows, kind);
		for (const row of choiceRows) {
			setHidden(row, row !== latest);
		}
		if (latest) {
			movePendingChoiceToLatest(scroll, rows, latest, kind);
		}
	}
}

export function installChatChoiceCardDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined") return;
	installed = true;
	addStyle();
	setInterval(normalizeChoiceCards, 700);
}
