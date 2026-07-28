const STYLE_ID = "chat-timeline-chronology-style";
const HIDDEN_ATTR = "data-timeline-chronology-hidden";

let installed = false;
let scheduled = false;

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
[${HIDDEN_ATTR}="true"] {
	display: none !important;
}
`;
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

function displayedMinute(row: HTMLElement) {
	const matches = Array.from(
		textOf(row).matchAll(/\b([01]\d|2[0-3]):([0-5]\d)\b/g),
	);
	const last = matches.at(-1);
	if (!last) return null;
	return Number(last[1]) * 60 + Number(last[2]);
}

function isModelingConfirmation(row: HTMLElement) {
	const text = textOf(row);
	return (
		text.includes("建模方案已确认") ||
		(text.includes("建模方案附件") && text.includes("已确认"))
	);
}

function isModelingRefinement(row: HTMLElement) {
	const text = textOf(row);
	if (!text.includes("ModelerAgent")) return false;
	if (/候选建模方案|建模方案附件|请选择|待确认/.test(text)) return false;
	return /详细建模方案细化|方案细化|整体建模方案/.test(text);
}

function isLaterThanConfirmation(
	row: HTMLElement,
	confirmation: HTMLElement,
) {
	const rowMinute = displayedMinute(row);
	const confirmationMinute = displayedMinute(confirmation);
	if (rowMinute == null || confirmationMinute == null) return false;
	const delta = rowMinute - confirmationMinute;
	return delta > 0 && delta < 12 * 60;
}

function setHidden(row: HTMLElement, hidden: boolean) {
	if (hidden) {
		if (row.getAttribute(HIDDEN_ATTR) !== "true") {
			row.setAttribute(HIDDEN_ATTR, "true");
		}
		return;
	}
	if (row.hasAttribute(HIDDEN_ATTR)) row.removeAttribute(HIDDEN_ATTR);
}

function setOrder(row: HTMLElement, order: number) {
	const value = String(order);
	if (row.style.order !== value) row.style.order = value;
}

function latestRow(rows: HTMLElement[]) {
	return [...rows].sort((left, right) => {
		const leftMinute = displayedMinute(left) ?? -1;
		const rightMinute = displayedMinute(right) ?? -1;
		if (leftMinute !== rightMinute) return rightMinute - leftMinute;
		return rows.indexOf(right) - rows.indexOf(left);
	})[0];
}

function normalizeTimelineChronology() {
	const scroll = getTimelineScroll();
	if (!scroll) return;

	if (scroll.style.display !== "flex") scroll.style.display = "flex";
	if (scroll.style.flexDirection !== "column") {
		scroll.style.flexDirection = "column";
	}

	const rows = getRows(scroll);
	for (const [index, row] of rows.entries()) {
		setHidden(row, false);
		setOrder(row, index * 10);
	}

	const confirmation = rows.filter(isModelingConfirmation).at(-1);
	if (!confirmation) return;

	const refinements = rows.filter(isModelingRefinement);
	const postConfirmationRefinements = refinements.filter((row) =>
		isLaterThanConfirmation(row, confirmation),
	);
	if (!postConfirmationRefinements.length) return;

	const currentRefinement = latestRow(postConfirmationRefinements);
	for (const row of refinements) {
		setHidden(row, row !== currentRefinement);
	}

	const confirmationIndex = rows.indexOf(confirmation);
	setOrder(currentRefinement, confirmationIndex * 10 + 1);
}

function scheduleNormalize() {
	if (scheduled) return;
	scheduled = true;
	requestAnimationFrame(() => {
		scheduled = false;
		normalizeTimelineChronology();
	});
}

export function installChatTimelineChronologyDomPatch() {
	if (
		installed ||
		typeof window === "undefined" ||
		typeof document === "undefined"
	) {
		return;
	}
	installed = true;
	addStyle();
	const observer = new MutationObserver(scheduleNormalize);
	observer.observe(document.body, {
		childList: true,
		subtree: true,
		characterData: true,
	});
	scheduleNormalize();
}
