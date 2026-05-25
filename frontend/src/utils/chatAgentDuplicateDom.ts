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

function getCard(row: HTMLElement) {
	return Array.from(row.querySelectorAll<HTMLElement>("div"))
		.find((node) => {
			const cls = node.getAttribute("class") || "";
			return cls.includes("rounded-2xl") && cls.includes("shadow-sm") && !cls.includes("choice-attachment");
		}) || null;
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

function setBadge(row: HTMLElement, count: number) {
	const card = getCard(row);
	if (!card) return;
	let badge = card.querySelector<HTMLElement>(`[${BADGE_ATTR}]`);
	if (!badge) {
		badge = document.createElement("div");
		badge.className = "agent-merge-badge";
		badge.setAttribute(BADGE_ATTR, "true");
		card.appendChild(badge);
	}
	badge.textContent = `已合并 ${count} 条同阶段过程更新`;
}

function isRawCoderProcess(text: string) {
	return (
		/CoderAgent/.test(text) &&
		/(输出结果摘要|正在思考与生成)/.test(text) &&
		/(代码介绍|所属阶段|功能说明|预测产出|EDA|敏感性|灵敏度|求解|作图|绘图|分析)/.test(text)
	);
}

function isRawWriterProcess(text: string) {
	return (
		/WriterAgent/.test(text) &&
		/(输出结果摘要|正在思考与生成)/.test(text) &&
		/(所属阶段|章节|写作|论文|终稿|摘要|正文|模型)/.test(text)
	);
}

function extractStage(text: string) {
	const stage = text.match(/所属阶段\s*[:：]?\s*([A-Za-z0-9_\-\u4e00-\u9fa5]+)/i)?.[1];
	if (stage) return stage.toLowerCase();
	if (/EDA|描述性|数据预处理|成本利润|异类验证|豆类/.test(text)) return "eda";
	if (/敏感性|灵敏度|sensitivity/i.test(text)) return "sensitivity";
	if (/终稿|整体检查|final/i.test(text)) return "final";
	const q = text.match(/(?:第\s*|Q|ques)(\d+)\s*问/i)?.[1];
	if (q) return `q${q}`;
	return "general";
}

function rowGroupKey(row: HTMLElement) {
	const text = textOf(row);
	if (isRawCoderProcess(text)) return `coder:${extractStage(text)}`;
	if (isRawWriterProcess(text)) return `writer:${extractStage(text)}`;
	return "";
}

function shouldPrefer(row: HTMLElement) {
	const text = textOf(row);
	if (/运行中|正在思考与生成/.test(text)) return 2;
	if (/输出结果摘要/.test(text)) return 1;
	return 0;
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

	const groups = new Map<string, HTMLElement[]>();
	for (const row of rows) {
		const key = rowGroupKey(row);
		if (!key) continue;
		const list = groups.get(key) || [];
		list.push(row);
		groups.set(key, list);
	}

	for (const [, list] of groups) {
		if (list.length <= 1) continue;
		let keep = list[list.length - 1];
		for (const row of list) {
			if (shouldPrefer(row) > shouldPrefer(keep)) keep = row;
		}
		for (const row of list) setHidden(row, row !== keep);
		setBadge(keep, list.length - 1);
	}
}

export function installChatAgentDuplicateDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined") return;
	installed = true;
	addStyle();
	setInterval(collapseDuplicateAgentCards, 900);
}
