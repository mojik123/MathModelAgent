const STYLE_ID = "chat-timeline-chronology-style";
const TIMELINE_SELECTOR = "[data-agent-timeline-scroll='true']";
const GENERATED_ATTR = "data-current-action-generated";
const HIDDEN_ATTR = "data-timeline-chronology-hidden";
const STAGE_ATTR = "data-timeline-chronology-stage";

let installed = false;
let scheduled = false;

interface StageOrder {
	key: string;
	rank: number;
}

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
	return document.querySelector<HTMLElement>(TIMELINE_SELECTOR);
}

function getRows(scroll: HTMLElement) {
	return Array.from(scroll.children).filter(
		(node): node is HTMLElement =>
			node instanceof HTMLElement &&
			!node.hasAttribute(GENERATED_ATTR) &&
			textOf(node).length > 0,
	);
}

function displayedMinute(row: HTMLElement) {
	const matches = Array.from(
		textOf(row).matchAll(/\b([01]\d|2[0-3]):([0-5]\d)\b/g),
	);
	const last = matches.at(-1);
	if (!last) return -1;
	return Number(last[1]) * 60 + Number(last[2]);
}

function isModelingRefinement(row: HTMLElement) {
	const text = textOf(row);
	if (!text.includes("ModelerAgent")) return false;
	if (/候选建模方案|建模方案附件|请选择|待确认/.test(text)) return false;
	return /详细建模方案细化|方案细化|整体建模方案/.test(text);
}

function questionIndex(row: HTMLElement) {
	const text = textOf(row);
	const isQuestionCard =
		/SubCoordinatorAgent|子问题组/.test(text) ||
		Boolean(row.querySelector("[data-agent-card='subcoordinator']"));
	if (!isQuestionCard) return null;
	const match = text.match(/\bQ(\d+)\b|子问题组\s*(\d+)|问题\s*(\d+)/i);
	if (!match) return null;
	const value = Number(match[1] || match[2] || match[3]);
	return Number.isFinite(value) && value > 0 ? value : null;
}

function stageOrder(row: HTMLElement): StageOrder {
	const text = textOf(row);

	if (
		/User/.test(text) &&
		/已确定题目信息|题目信息|题目原文|个附件/.test(text)
	) {
		return { key: "problem-input", rank: 0 };
	}
	if (/问题划分已确认|已确认问题划分/.test(text)) {
		return { key: "question-confirmation", rank: 200 };
	}
	if (
		/建模方案已确认|已确认建模方案/.test(text) ||
		(/建模方案附件/.test(text) && /已确认/.test(text))
	) {
		return { key: "modeling-confirmation", rank: 400 };
	}
	if (
		/CoordinatorAgent/.test(text) &&
		/任务规划|规划阶段|问题划分|题目解析|问题拆解/.test(text)
	) {
		return { key: "planning", rank: 100 };
	}
	if (
		/ModelerAgent/.test(text) &&
		/方案细化|建模阶段|整体建模方案|候选建模方案/.test(text)
	) {
		return { key: "modeling", rank: 300 };
	}
	if (
		/\bEDA\b|探索性数据分析|数据探索与代码求解|数据预处理与探索|数据来源与质量审计/i.test(
			text,
		)
	) {
		const writer = /WriterAgent|EDA 分析章节写作/.test(text);
		return {
			key: writer ? "eda-writing" : "eda-solving",
			rank: writer ? 510 : 500,
		};
	}

	const question = questionIndex(row);
	if (question) {
		return {
			key: `question-${question}`,
			rank: 600 + question * 10,
		};
	}
	if (/灵敏度|敏感性分析/.test(text)) {
		return { key: "sensitivity", rank: 900 };
	}
	if (/终稿|整体检查|论文生成完成|任务处理完成|最终审查/.test(text)) {
		return { key: "final", rank: 1100 };
	}
	if (/WriterAgent|并行写作|章节写作|论文写作/.test(text)) {
		return { key: "writing", rank: 1000 };
	}
	if (/图片修订|文本修订|AI 修改|用户请求停止|任务已停止/.test(text)) {
		return { key: "follow-up", rank: 1200 };
	}
	if (/CoderAgent|代码求解|模型计算/.test(text)) {
		return { key: "coding", rank: 550 };
	}
	return { key: "process", rank: 450 };
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

function setStage(row: HTMLElement, stage: string) {
	if (row.getAttribute(STAGE_ATTR) !== stage) {
		row.setAttribute(STAGE_ATTR, stage);
	}
}

function hideSupersededRefinements(rows: HTMLElement[]) {
	const refinements = rows.filter(isModelingRefinement);
	if (refinements.length < 2) return;
	const latest = [...refinements].sort((left, right) => {
		const minuteDelta = displayedMinute(right) - displayedMinute(left);
		if (minuteDelta) return minuteDelta;
		return rows.indexOf(right) - rows.indexOf(left);
	})[0];
	for (const row of refinements) setHidden(row, row !== latest);
}

function normalizeTimelineChronology() {
	const scroll = getTimelineScroll();
	if (!scroll) return;
	if (scroll.style.display !== "flex") scroll.style.display = "flex";
	if (scroll.style.flexDirection !== "column") {
		scroll.style.flexDirection = "column";
	}

	const rows = getRows(scroll);
	for (const [sourceIndex, row] of rows.entries()) {
		setHidden(row, false);
		const stage = stageOrder(row);
		setStage(row, stage.key);
		// 阶段权重决定主要顺序，原始 DOM 下标只负责同阶段内稳定排序。
		// 因此实时消息更新不会把 EDA 或其他前置阶段推到问题卡之后。
		setOrder(row, stage.rank * 10_000 + sourceIndex);
	}
	hideSupersededRefinements(rows);
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
	window.addEventListener("resize", scheduleNormalize, { passive: true });
	window.setInterval(scheduleNormalize, 650);
	scheduleNormalize();
}
