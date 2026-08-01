const STYLE_ID = "chat-choice-card-dom-style";
const HIDDEN_ATTR = "data-choice-card-duplicate-hidden";
const PINNED_ATTR = "data-choice-card-pinned-latest";
const WIDE_ROW_ATTR = "data-choice-card-wide-row";
const WIDE_SHELL_ATTR = "data-choice-card-wide-shell";
const WIDE_BUBBLE_ATTR = "data-choice-card-wide-bubble";
const CONFIRMATION_ROW_ATTR = "data-question-confirmation-flow-row";
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

[${WIDE_ROW_ATTR}="true"] {
	width: 100% !important;
	max-width: none !important;
}

[${WIDE_SHELL_ATTR}="true"] {
	width: 100% !important;
	max-width: none !important;
	flex: 1 1 auto !important;
}

[${WIDE_BUBBLE_ATTR}="true"] {
	width: auto !important;
	max-width: none !important;
	flex: 1 1 0% !important;
}

[${WIDE_BUBBLE_ATTR}="true"] .choice-attachment,
[${WIDE_BUBBLE_ATTR}="true"] .agent-conversation-inline-panel,
[${WIDE_BUBBLE_ATTR}="true"] .question-discussion,
[${WIDE_BUBBLE_ATTR}="true"] .modeling-discussion {
	width: 100% !important;
	max-width: none !important;
}

[${WIDE_BUBBLE_ATTR}="true"] .question-discussion {
	max-height: none !important;
}

[${CONFIRMATION_ROW_ATTR}="true"] {
	display: flex;
	width: 100%;
	justify-content: flex-end;
	padding: 0 0 1px;
}

[${CONFIRMATION_ROW_ATTR}="true"] [data-question-confirmation-shell="true"] {
	display: flex;
	max-width: min(86%, 720px);
	align-items: flex-start;
	gap: 6px;
	flex-direction: row-reverse;
}

[${CONFIRMATION_ROW_ATTR}="true"] [data-question-confirmation-avatar="true"] {
	display: flex;
	width: 28px;
	height: 28px;
	flex: 0 0 auto;
	align-items: center;
	justify-content: center;
	margin-top: 4px;
	border-radius: 9999px;
	background: rgb(15 23 42);
	color: white;
	font-size: 11px;
	font-weight: 800;
	box-shadow: 0 1px 3px rgba(15, 23, 42, .18);
}

[${CONFIRMATION_ROW_ATTR}="true"] [data-question-confirmation-bubble="true"] {
	min-width: 0;
	border: 1px solid rgb(30 41 59);
	border-radius: 16px 5px 16px 16px;
	background: rgb(15 23 42);
	padding: 10px 12px;
	color: white;
	box-shadow: 0 1px 3px rgba(15, 23, 42, .16);
}

[${CONFIRMATION_ROW_ATTR}="true"] [data-question-confirmation-meta="true"] {
	display: flex;
	align-items: center;
	gap: 6px;
	font-size: 10px;
	line-height: 1.2;
	color: rgba(255, 255, 255, .52);
}

[${CONFIRMATION_ROW_ATTR}="true"] [data-question-confirmation-title="true"] {
	display: flex;
	align-items: center;
	gap: 6px;
	margin-top: 4px;
	font-size: 14px;
	font-weight: 700;
	line-height: 1.35;
}

[${CONFIRMATION_ROW_ATTR}="true"] [data-question-confirmation-detail="true"] {
	margin-top: 5px;
	font-size: 12px;
	line-height: 1.55;
	color: rgba(255, 255, 255, .76);
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
	return (
		Array.from(panel.querySelectorAll<HTMLElement>("div")).find((node) => {
			const cls = node.getAttribute("class") || "";
			return cls.includes("overflow-y-auto") && cls.includes("space-y-4");
		}) ||
		panel.querySelector<HTMLElement>("[data-agent-timeline-scroll='true']") ||
		null
	);
}

function getRows(scroll: HTMLElement) {
	return Array.from(scroll.children)
		.filter((node): node is HTMLElement => node instanceof HTMLElement)
		.filter((node) => textOf(node).length > 0);
}

function choiceKind(row: HTMLElement): "question" | "modeling" | "" {
	const text = textOf(row);
	if (text.includes("问题划分附件") || text.includes("问题划分已生成，请确认"))
		return "question";
	if (text.includes("建模方案附件") || text.includes("候选建模方案已生成，请选择"))
		return "modeling";
	return "";
}

function isPendingChoice(row: HTMLElement) {
	const text = textOf(row);
	return (
		/待确认|需要用户确认|请确认|请选择|确认问题划分|确认各问建模方案|确认建模方案/.test(
			text,
		) &&
		!/已确认问题划分|问题划分已确认|已确认建模方案|建模方案已确认/.test(
			text,
		)
	);
}

function setHidden(row: HTMLElement, hidden: boolean) {
	if (hidden) {
		if (row.getAttribute(HIDDEN_ATTR) !== "true")
			row.setAttribute(HIDDEN_ATTR, "true");
	} else if (row.hasAttribute(HIDDEN_ATTR)) {
		row.removeAttribute(HIDDEN_ATTR);
	}
}

function setPinned(row: HTMLElement, pinned: boolean) {
	if (pinned) {
		if (row.getAttribute(PINNED_ATTR) !== "true")
			row.setAttribute(PINNED_ATTR, "true");
	} else if (row.hasAttribute(PINNED_ATTR)) {
		row.removeAttribute(PINNED_ATTR);
	}
}

function latestByKind(rows: HTMLElement[], kind: "question" | "modeling") {
	return rows.filter((row) => choiceKind(row) === kind).at(-1) || null;
}

function hasLaterGenerationRows(
	rows: HTMLElement[],
	choiceRow: HTMLElement,
	kind: "question" | "modeling",
) {
	const index = rows.indexOf(choiceRow);
	if (index < 0) return false;
	const later = rows.slice(index + 1).map(textOf).join("\n");
	if (kind === "question") {
		return /问题划分|拆解|CoordinatorAgent|正在思考与生成|输出结果摘要/.test(
			later,
		);
	}
	return /第\s*\d+\s*问|Q\d+|建模方案|生成模型方案|生成建模方案|ModelerAgent|正在思考与生成|输出结果摘要/.test(
		later,
	);
}

function movePendingChoiceToLatest(
	scroll: HTMLElement,
	rows: HTMLElement[],
	row: HTMLElement,
	kind: "question" | "modeling",
) {
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

function markChoiceCardWide(row: HTMLElement) {
	const attachment = row.querySelector<HTMLElement>(".choice-attachment");
	if (!attachment) return;
	const bubble = attachment.parentElement;
	const shell = bubble?.parentElement;
	row.setAttribute(WIDE_ROW_ATTR, "true");
	if (shell) shell.setAttribute(WIDE_SHELL_ATTR, "true");
	if (bubble) bubble.setAttribute(WIDE_BUBBLE_ATTR, "true");
}

function hasVisibleQuestionConfirmation(
	rows: HTMLElement[],
	questionRow: HTMLElement,
) {
	return rows.some((row) => {
		if (row === questionRow || row.hasAttribute(CONFIRMATION_ROW_ATTR)) return false;
		if (choiceKind(row)) return false;
		return /已确认问题划分|确认问题划分/.test(textOf(row));
	});
}

function createQuestionConfirmationRow() {
	const row = document.createElement("div");
	row.setAttribute(CONFIRMATION_ROW_ATTR, "true");
	row.innerHTML = `
		<div data-question-confirmation-shell="true">
			<div data-question-confirmation-avatar="true" aria-hidden="true">U</div>
			<div data-question-confirmation-bubble="true">
				<div data-question-confirmation-meta="true">
					<span>用户</span>
					<span>用户确认</span>
				</div>
				<div data-question-confirmation-title="true">
					<span aria-hidden="true">✓</span>
					<span>已确认问题划分</span>
				</div>
				<div data-question-confirmation-detail="true">确认当前问题结构，继续进入建模方案选择阶段。</div>
			</div>
		</div>
	`;
	return row;
}

function syncQuestionConfirmationFlow(
	scroll: HTMLElement,
	rows: HTMLElement[],
	questionRow: HTMLElement | null,
) {
	const injected = scroll.querySelector<HTMLElement>(
		`[${CONFIRMATION_ROW_ATTR}="true"]`,
	);
	if (!questionRow) {
		injected?.remove();
		return;
	}
	const confirmed = /问题划分已确认|已确认问题划分/.test(textOf(questionRow));
	if (!confirmed || hasVisibleQuestionConfirmation(rows, questionRow)) {
		injected?.remove();
		return;
	}
	const confirmationRow = injected ?? createQuestionConfirmationRow();
	if (questionRow.nextElementSibling !== confirmationRow) {
		questionRow.after(confirmationRow);
	}
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
			markChoiceCardWide(row);
		}
		if (latest) {
			movePendingChoiceToLatest(scroll, rows, latest, kind);
		}
	}

	const refreshedRows = getRows(scroll);
	const latestQuestion = latestByKind(refreshedRows, "question");
	syncQuestionConfirmationFlow(scroll, refreshedRows, latestQuestion);
}

export function installChatChoiceCardDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined")
		return;
	installed = true;
	addStyle();
	setInterval(normalizeChoiceCards, 350);
}
