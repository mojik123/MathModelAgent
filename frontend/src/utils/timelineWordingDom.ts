import { useTaskStore } from "@/stores/task";
import { AgentType } from "@/utils/enum";
import type { Message } from "@/utils/response";
import type { Pinia } from "pinia";

const STYLE_ID = "timeline-wording-dom-style";
const LOW_VALUE_DETAIL_ATTR = "data-timeline-low-value-detail";
const AGENT_NAMES = [
	"CoordinatorAgent",
	"SubCoordinatorAgent",
	"ModelerAgent",
	"CoderAgent",
	"WriterAgent",
] as const;

type AgentName = (typeof AGENT_NAMES)[number];

let installed = false;

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
[${LOW_VALUE_DETAIL_ATTR}="true"] {
	display: none !important;
}
`;
	document.head.appendChild(style);
}

function textOf(node: Element | null) {
	return (node?.textContent || "").replace(/\s+/g, " ").trim();
}

function messageText(message: Message) {
	return (message.content ?? "").replace(/\s+/g, " ").trim();
}

function getPanel() {
	return document.querySelector<HTMLElement>(".glass-left-panel");
}

function getTimelineScroll(panel: HTMLElement) {
	return (
		panel.querySelector<HTMLElement>("[data-agent-timeline-scroll='true']") ||
		Array.from(panel.querySelectorAll<HTMLElement>("div")).find((node) => {
			const cls = node.getAttribute("class") || "";
			return cls.includes("overflow-y-auto") && cls.includes("space-y-4");
		}) ||
		null
	);
}

function getTimelineRows(panel: HTMLElement) {
	const scroll = getTimelineScroll(panel);
	if (!scroll) return [];
	return Array.from(scroll.children).filter(
		(node): node is HTMLElement => node instanceof HTMLElement && textOf(node).length > 0,
	);
}

function getMessageCard(row: HTMLElement) {
	return (
		row.querySelector<HTMLElement>("[data-agent-card]") ||
		Array.from(row.querySelectorAll<HTMLElement>("div")).find((node) => {
			const cls = node.getAttribute("class") || "";
			return (
				cls.includes("rounded-2xl") &&
				cls.includes("shadow-sm") &&
				!cls.includes("choice-attachment")
			);
		}) ||
		null
	);
}

function actorSpan(card: HTMLElement) {
	return (
		Array.from(card.querySelectorAll<HTMLElement>("span")).find((node) =>
			AGENT_NAMES.includes(textOf(node) as AgentName),
		) || null
	);
}

function actorOf(card: HTMLElement): AgentName | "" {
	const actor = textOf(actorSpan(card));
	return AGENT_NAMES.includes(actor as AgentName) ? (actor as AgentName) : "";
}

function titleSpan(card: HTMLElement) {
	const container = Array.from(card.querySelectorAll<HTMLElement>("div")).find(
		(node) => {
			const cls = node.getAttribute("class") || "";
			return cls.includes("text-sm") && cls.includes("font-semibold");
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

function roleSpan(card: HTMLElement) {
	const actor = actorSpan(card);
	const next = actor?.nextElementSibling;
	return next instanceof HTMLElement ? next : null;
}

function questionIndexOf(message: Message) {
	if (message.msg_type === "agent" && typeof message.question_index === "number") {
		return message.question_index;
	}
	const content = messageText(message);
	const identity =
		message.msg_type === "agent"
			? `${message.group_id ?? ""} ${message.agent_instance_id ?? ""}`
			: "";
	const match = `${identity} ${content}`.match(
		/(?:第\s*|Q|q(?:ues)?|子问题组#|组#)(\d+)\s*(?:问)?/,
	);
	return match ? Number(match[1]) : null;
}

function matchesAgent(message: Message, actor: AgentName) {
	if (message.msg_type === "agent" && message.agent_type === actor) return true;
	const content = messageText(message);
	const aliases: Record<AgentName, RegExp> = {
		CoordinatorAgent: /CoordinatorAgent|协调者|协调手/,
		SubCoordinatorAgent: /SubCoordinatorAgent|子问题协调/,
		ModelerAgent: /ModelerAgent|建模手|建模方案/,
		CoderAgent: /CoderAgent|代码手|代码求解|执行代码/,
		WriterAgent: /WriterAgent|论文手|写作手|论文写作/,
	};
	return aliases[actor].test(content);
}

function recentAgentText(messages: Message[], actor: AgentName, limit = 30) {
	const result: string[] = [];
	for (let index = messages.length - 1; index >= 0 && result.length < limit; index--) {
		const message = messages[index];
		if (!matchesAgent(message, actor)) continue;
		const content = messageText(message);
		if (content) result.unshift(content);
	}
	return result.join("\n");
}

function recentWorkflowText(messages: Message[], limit = 80) {
	return messages
		.slice(-limit)
		.map(messageText)
		.filter(Boolean)
		.join("\n");
}

function lastMatchIndex(text: string, pattern: RegExp) {
	let latest = -1;
	const lines = text.split("\n");
	for (let index = 0; index < lines.length; index++) {
		if (pattern.test(lines[index])) latest = index;
	}
	return latest;
}

function coderSubject(messages: Message[], cardText: string) {
	const corpus = `${recentAgentText(messages, AgentType.CODER)}\n${recentWorkflowText(messages)}\n${cardText}`;
	const stages = [
		{
			label: "灵敏度分析与代码求解",
			index: lastMatchIndex(corpus, /灵敏度|敏感性分析/),
		},
		{
			label: "EDA 数据探索与代码求解",
			index: lastMatchIndex(
				corpus,
				/\bEDA\b|探索性数据分析|数据探索|描述性统计|数据预处理|数据清洗/i,
			),
		},
		{
			label: "优化模型计算与寻优",
			index: lastMatchIndex(corpus, /Pareto|寻优|多目标优化|优化求解/),
		},
		{
			label: "结果可视化与绘图",
			index: lastMatchIndex(corpus, /结果可视化|绘图|生成图表|图像绘制/),
		},
	];
	const latest = stages.sort((left, right) => right.index - left.index)[0];
	return latest && latest.index >= 0 ? latest.label : "模型计算与代码求解";
}

function writerSubject(messages: Message[], cardText: string) {
	const corpus = `${recentAgentText(messages, AgentType.WRITER)}\n${cardText}`;
	if (/灵敏度|敏感性分析/.test(corpus)) return "灵敏度分析章节写作";
	if (/\bEDA\b|探索性数据分析|数据探索/.test(corpus))
		return "EDA 分析章节写作";
	if (/摘要|关键词/.test(corpus)) return "摘要与关键词写作";
	if (/问题重述/.test(corpus)) return "问题重述章节写作";
	if (/模型假设/.test(corpus)) return "模型假设章节写作";
	if (/符号说明/.test(corpus)) return "符号说明章节写作";
	if (/模型评价|优缺点/.test(corpus)) return "模型评价章节写作";
	return "论文内容写作";
}

function statusSuffix(title: string) {
	const raw = title.split("·").slice(1).join("·").trim();
	if (/写作完成|求解完成|已完成/.test(raw)) return "已完成";
	if (/写作中|求解中|进行中/.test(raw)) return "进行中";
	return raw || "进行中";
}

function stripAgentPrefix(text: string) {
	return text
		.replace(
			/^(?:CoordinatorAgent|SubCoordinatorAgent|ModelerAgent|CoderAgent|WriterAgent|协调者|建模手|代码手|论文手|写作手)\s*(?:[·:：-]\s*)?/,
			"",
		)
		.trim();
}

function normalizeThinkingText(text: string) {
	return text
		.replace(/^正在思考与生成$/, "正在思考")
		.replace(/^正在思考与生成\s*[：:]?/, "正在思考：")
		.replace(/正在思考与生成/g, "正在思考")
		.replace(/：$/, "")
		.trim();
}

function questionTitle(
	messages: Message[],
	questionIndex: number,
	currentStatus: string,
) {
	let latestActor: AgentName | "" = "";
	for (let index = messages.length - 1; index >= 0; index--) {
		const message = messages[index];
		if (questionIndexOf(message) !== questionIndex) continue;
		if (message.msg_type === "agent" && AGENT_NAMES.includes(message.agent_type as AgentName)) {
			latestActor = message.agent_type as AgentName;
			break;
		}
	}
	if (/重写/.test(currentStatus)) return `问题 ${questionIndex} 的代码重写 · 进行中`;
	if (/改错|判别/.test(currentStatus))
		return `问题 ${questionIndex} 的代码调试 · 进行中`;
	if (/写作/.test(currentStatus) || latestActor === AgentType.WRITER) {
		return `问题 ${questionIndex} 的论文写作 · ${/完成/.test(currentStatus) ? "已完成" : "进行中"}`;
	}
	if (/求解/.test(currentStatus) || latestActor === AgentType.CODER) {
		return `问题 ${questionIndex} 的模型求解 · ${/完成/.test(currentStatus) ? "已完成" : "进行中"}`;
	}
	return `问题 ${questionIndex} 的求解与写作 · ${statusSuffix(`· ${currentStatus}`)}`;
}

function normalizeTitle(
	title: string,
	actor: AgentName | "",
	messages: Message[],
	cardText: string,
) {
	const cleaned = normalizeThinkingText(stripAgentPrefix(title));
	const status = statusSuffix(cleaned);
	const questionMatch = cleaned.match(/^子问题组\s*(\d+)\s*·\s*(.+)$/);
	if (questionMatch) {
		return questionTitle(messages, Number(questionMatch[1]), questionMatch[2]);
	}
	if (/^建模阶段\s*·/.test(cleaned))
		return `详细建模方案细化 · ${status}`;
	if (/^代码求解\s*·/.test(cleaned))
		return `${coderSubject(messages, cardText)} · ${status}`;
	if (/^并行写作组\s*·/.test(cleaned))
		return `论文各章节并行写作 · ${status}`;
	if (/^规划阶段\s*·/.test(cleaned))
		return `问题划分与任务规划 · ${status}`;
	if (/^终稿整合\s*·/.test(cleaned))
		return `论文终稿整合与质量检查 · ${status}`;
	if (/^阶段过程\s*·/.test(cleaned)) return `任务处理 · ${status}`;
	if (cleaned === "输出结果摘要") {
		if (actor === AgentType.MODELER) return "建模方案输出完成";
		if (actor === AgentType.CODER) return "代码求解结果已生成";
		if (actor === AgentType.WRITER) return writerSubject(messages, cardText);
		if (actor === AgentType.COORDINATOR) return "问题分析结果已生成";
	}
	return cleaned;
}

function normalizeRole(card: HTMLElement) {
	const role = roleSpan(card);
	if (!role) return;
	const replacements: Record<string, string> = {
		规划阶段: "任务规划",
		建模阶段: "方案细化",
		代码求解: "模型计算",
		并行写作组: "章节写作",
		"EDA 章节": "章节写作",
		终稿整合: "终稿检查",
	};
	const current = textOf(role);
	const replacement = replacements[current];
	if (replacement && current !== replacement) role.textContent = replacement;
}

function isLowValueDetail(text: string) {
	return [
		/^该步骤已完成[。.]?$/,
		/^(?:.+\s)?已完成本阶段，结果已汇总[。.]?$/,
		/^该组结果已提交汇总[。.]?$/,
		/^结果已完成结构化整理，可在对应阶段卡片中查看[。.]?$/,
	].some((pattern) => pattern.test(text));
}

function normalizeDetails(card: HTMLElement) {
	for (const detail of card.querySelectorAll<HTMLElement>("p.message-detail")) {
		const original = textOf(detail);
		if (!original) continue;
		const cleaned = stripAgentPrefix(original)
			.replace(/该步骤已完成[。.]?/g, "")
			.replace(/\s+/g, " ")
			.trim();
		const shouldHide = !cleaned || isLowValueDetail(original) || isLowValueDetail(cleaned);
		if (shouldHide) {
			detail.setAttribute(LOW_VALUE_DETAIL_ATTR, "true");
			continue;
		}
		detail.removeAttribute(LOW_VALUE_DETAIL_ATTR);
		if (cleaned !== original) detail.textContent = cleaned;
	}
}

function normalizeLiveSummaries(card: HTMLElement) {
	for (const span of card.querySelectorAll<HTMLElement>("span")) {
		const original = textOf(span);
		if (!original || !/[·:：]/.test(original)) continue;
		if (
			!/^(?:CoordinatorAgent|SubCoordinatorAgent|ModelerAgent|CoderAgent|WriterAgent|协调者|建模手|代码手|论文手|写作手)\s*[·:：-]/.test(
				original,
			)
		)
			continue;
		const cleaned = normalizeThinkingText(stripAgentPrefix(original));
		if (cleaned && cleaned !== original) span.textContent = cleaned;
	}
}

function normalizeCard(card: HTMLElement, messages: Message[]) {
	const actor = actorOf(card);
	const title = titleSpan(card);
	if (title) {
		const original = textOf(title);
		const normalized = normalizeTitle(original, actor, messages, textOf(card));
		if (normalized && normalized !== original) title.textContent = normalized;
	}
	normalizeRole(card);
	normalizeDetails(card);
	normalizeLiveSummaries(card);
}

export function installTimelineWordingDomPatch(pinia: Pinia) {
	if (installed || typeof window === "undefined" || typeof document === "undefined")
		return;
	installed = true;
	addStyle();
	const taskStore = useTaskStore(pinia);
	const apply = () => {
		const panel = getPanel();
		if (!panel) return;
		for (const row of getTimelineRows(panel)) {
			const card = getMessageCard(row);
			if (card) normalizeCard(card, taskStore.messages);
		}
	};
	setInterval(apply, 320);
}
