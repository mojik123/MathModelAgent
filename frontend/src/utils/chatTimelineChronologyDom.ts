const FIXED_ATTR = "data-timeline-chronology-fixed";

let installed = false;
let scheduled = false;

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
	const matches = Array.from(textOf(row).matchAll(/\b([01]\d|2[0-3]):([0-5]\d)\b/g));
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

function shouldMoveAfterConfirmation(
	row: HTMLElement,
	confirmation: HTMLElement,
) {
	const rowMinute = displayedMinute(row);
	const confirmationMinute = displayedMinute(confirmation);
	if (rowMinute != null && confirmationMinute != null) {
		const delta = rowMinute - confirmationMinute;
		return delta > 0 && delta < 12 * 60;
	}
	return /详细建模方案细化|整体建模方案/.test(textOf(row));
}

function normalizeTimelineChronology() {
	const scroll = getTimelineScroll();
	if (!scroll) return;
	const rows = getRows(scroll);
	const confirmation = rows.filter(isModelingConfirmation).at(-1);
	if (!confirmation) return;

	const confirmationIndex = rows.indexOf(confirmation);
	if (confirmationIndex <= 0) return;

	const misplaced = rows
		.slice(0, confirmationIndex)
		.filter(isModelingRefinement)
		.filter((row) => shouldMoveAfterConfirmation(row, confirmation));
	if (!misplaced.length) return;

	let anchor = confirmation;
	for (const row of misplaced) {
		if (anchor.nextElementSibling !== row) anchor.after(row);
		row.setAttribute(FIXED_ATTR, "true");
		anchor = row;
	}
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
	const observer = new MutationObserver(scheduleNormalize);
	observer.observe(document.body, {
		childList: true,
		subtree: true,
		characterData: true,
	});
	scheduleNormalize();
}
