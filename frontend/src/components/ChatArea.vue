<script setup lang="ts">
import { type TaskRuntimeStatus, getOriginalProblem } from "@/apis/commonApi";
import ModelingDiscussion from "@/components/ModelingDiscussion.vue";
import QuestionDiscussion from "@/components/QuestionDiscussion.vue";
import { AgentType } from "@/utils/enum";
import { isImageFile, normalizeImageFilename } from "@/utils/imageConstants";
import { resolveTaskImageUrl } from "@/utils/markdown";
import type {
	AgentMessage,
	InterpreterMessage,
	Message,
	ProgressMessage,
	SystemMessage,
	ToolMessage,
} from "@/utils/response";
import {
	AlertTriangle,
	Bot,
	CheckCircle2,
	ChevronDown,
	Clock3,
	Code2,
	Download,
	FileSpreadsheet,
	FileText,
	ImageIcon,
	LoaderCircle,
	MessageSquareText,
	PenLine,
	Sparkles,
	UserRound,
	Wrench,
} from "lucide-vue-next";
import { computed, nextTick, ref, watch } from "vue";

const props = withDefaults(
	defineProps<{
		messages: Message[];
		taskStatus?: TaskRuntimeStatus;
		collapsed?: boolean;
		taskId?: string;
	}>(),
	{ taskStatus: "ready" },
);

const emit = defineEmits<{
	questionConfirm: [];
	modelingConfirm: [];
	imageOpen: [filename: string];
	fileOpen: [filename: string];
}>();

interface TimelineEvent {
	id: string;
	side: "left" | "right" | "center";
	actor: string;
	role: string;
	type:
		| "stage"
		| "choice"
		| "progress"
		| "artifact"
		| "warning"
		| "error"
		| "user"
		| "raw";
	title: string;
	detail?: string;
	brief?: string;
	status?: "running" | "done" | "warning" | "error" | "waiting";
	timeLabel: string;
	questionIndex?: number | null;
	badges?: string[];
	artifacts?: string[];
	inputFiles?: string[];
	problemText?: string;
	choiceKind?: "question" | "modeling";
	progressText?: string;
	debugCount?: number;
	isGroup?: boolean;
	groupPhase?:
		| "question"
		| "writing"
		| "planning"
		| "modeling"
		| "coding"
		| "final"
		| "process";
	groupEvents?: TimelineEvent[];
	groupActors?: string[];
}

interface FlowStep {
	key: string;
	label: string;
	status: "pending" | "active" | "done" | "warning";
	detail: string;
}

type QuestionStatusType =
	| "pending"
	| "solving"
	| "debugging"
	| "judging"
	| "restarting"
	| "recoding"
	| "plotting"
	| "writing"
	| "done"
	| "failed";

interface QuestionStatus {
	index: number;
	label: string;
	status: QuestionStatusType;
	detail: string;
	debugCount?: number;
}

const scrollRef = ref<HTMLDivElement | null>(null);
const userScrolledUp = ref(false);
const inlineQuestionPanelOpen = ref(true);
const inlineModelingPanelOpen = ref(true);
const expandedProblemIds = ref<Set<string>>(new Set());
const legacyInputFiles = ref<string[]>([]);

const roleMap: Record<string, string> = {
	CoordinatorAgent: "任务协调",
	SubCoordinatorAgent: "子问题协调",
	ModelerAgent: "建模方案",
	CoderAgent: "代码求解",
	WriterAgent: "论文写作",
	SystemMonitor: "流程监控",
	User: "用户确认",
};

function messageText(m: Message) {
	return m.content ?? "";
}

const allMessageText = computed(() =>
	props.messages.map(messageText).join("\n"),
);
const hasStreamingMessage = computed(() =>
	props.messages.some(
		(message) =>
			message.msg_type === "agent" && message.stream_state === "streaming",
	),
);
const streamingSignature = computed(() =>
	props.messages
		.filter(
			(message) =>
				message.msg_type === "agent" && message.stream_state === "streaming",
		)
		.map((message) => `${message.id}:${(message.content ?? "").length}`)
		.join("|"),
);

const questionConfirmed = computed(() =>
	props.messages.some((m) => {
		const c = messageText(m);
		return (
			c.includes("问题划分已确认") ||
			c.includes("已复用问题划分") ||
			c.includes("用户确认了最终的问题划分方案")
		);
	}),
);

const modelingConfirmed = computed(() =>
	props.messages.some((m) => {
		const c = messageText(m);
		return (
			c.includes("建模方案已确认") ||
			c.includes("已复用建模方案选择") ||
			c.includes("用户确认全部问题的建模方案")
		);
	}),
);

const hasExplicitQuestionConfirmMessage = computed(() =>
	props.messages.some(
		(message) =>
			message.msg_type === "user" &&
			/用户确认了最终的问题划分方案/.test(messageText(message)),
	),
);

const hasExplicitModelingConfirmMessage = computed(() =>
	props.messages.some(
		(message) =>
			message.msg_type === "user" &&
			/用户确认全部问题的建模方案/.test(messageText(message)),
	),
);

function handleInlineQuestionConfirm() {
	inlineQuestionPanelOpen.value = false;
	emit("questionConfirm");
}

function handleInlineModelingConfirm() {
	inlineModelingPanelOpen.value = false;
	emit("modelingConfirm");
}

function timeLabel(input?: string | null) {
	if (!input) return "";
	const d = new Date(input);
	if (Number.isNaN(d.getTime())) return "";
	return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function firstLine(content?: string | null) {
	return (content ?? "").split("\n")[0]?.trim() ?? "";
}

function stripMarkdown(content: string) {
	return content
		.replace(/```[\s\S]*?```/g, "[代码/结构化内容]")
		.replace(/[#>*_`]/g, "")
		.replace(/\s+/g, " ")
		.trim();
}

function brief(content?: string | null, max = 180) {
	const s = stripMarkdown(content ?? "");
	return s.length > max ? `${s.slice(0, max)}…` : s;
}

function tailBrief(content?: string | null, max = 520) {
	const s = stripMarkdown(content ?? "");
	return s.length > max ? `…${s.slice(-max)}` : s;
}

function readableBrief(content?: string | null, max = 320) {
	const normalized = (content ?? "")
		.replace(/```(?:json)?/gi, "")
		.replace(/\\n/g, "\n")
		.replace(/\r\n?/g, "\n")
		.split("\n")
		.map((line) => line.replace(/^[#>*`\s]+/, "").trim())
		.filter(Boolean)
		.join("\n");
	return normalized.length > max
		? `${normalized.slice(0, max).trimEnd()}…`
		: normalized;
}

function structuredPayload(content: string): Record<string, unknown> | null {
	const normalized = content
		.trim()
		.replace(/^```(?:json)?\s*/i, "")
		.replace(/\s*```$/, "");
	const start = normalized.indexOf("{");
	const end = normalized.lastIndexOf("}");
	if (start < 0 || end <= start) return null;
	try {
		const parsed = JSON.parse(normalized.slice(start, end + 1));
		return parsed && typeof parsed === "object" && !Array.isArray(parsed)
			? parsed
			: null;
	} catch {
		return null;
	}
}

function structuredAgentSummary(
	content: string,
	actor: string,
): Pick<TimelineEvent, "title" | "detail"> | null {
	const payload = structuredPayload(content);
	if (!payload) return null;

	const payloadTitle =
		typeof payload.title === "string" ? payload.title.trim() : "";
	const questions = Array.isArray(payload.questions) ? payload.questions : [];
	const rawCount =
		payload.quescount ?? payload.question_count ?? questions.length;
	const questionCount =
		typeof rawCount === "number"
			? rawCount
			: Number.parseInt(String(rawCount || ""), 10);

	if (actor === "CoordinatorAgent") {
		const details = [
			payloadTitle ? `题目：${payloadTitle}` : "",
			Number.isFinite(questionCount) && questionCount > 0
				? `问题拆解：已识别 ${questionCount} 个小问`
				: "",
			"完整内容已整理到下方的问题划分卡片。",
		].filter(Boolean);
		return {
			title: "题目解析完成",
			detail: details.join("\n"),
		};
	}

	if (actor === "ModelerAgent") {
		return {
			title: "建模方案整理完成",
			detail: "结构化方案已整理到下方的建模确认卡片。",
		};
	}

	return {
		title: "结构化结果已生成",
		detail: payloadTitle
			? `结果：${payloadTitle}`
			: "结果已完成结构化整理，可在对应阶段卡片中查看。",
	};
}

function isLowValueAgent(text: string) {
	const normalized = stripMarkdown(text);
	return [
		/^Agent 模型配置[：:]/,
		/识别用户意图和拆解问题(?:ing)?/,
		/协调者正在分析问题结构/,
		/ModelerAgent 正在结合题目目标.*筛选候选模型/,
		/ModelerAgent 已完成模型比选并传递给 User/,
	].some((pattern) => pattern.test(normalized));
}

function detectQuestionIndex(text: string, msg?: Message): number | null {
	if (
		msg?.msg_type === "agent" &&
		[AgentType.COORDINATOR, AgentType.MODELER].includes(msg.agent_type)
	) {
		return null;
	}
	if (msg?.msg_type === "agent" && typeof msg.question_index === "number") {
		return msg.question_index;
	}
	const groupIdentity =
		msg?.msg_type === "agent"
			? (msg.group_id ?? msg.agent_instance_id ?? "")
			: "";
	const fromGroup = String(groupIdentity).match(/q(?:ues)?(\d+)|组#(\d+)/i);
	if (fromGroup) return Number(fromGroup[1] || fromGroup[2]);
	const m = text.match(/(?:\[组#|子问题组#|第\s*)(\d+)/);
	if (m) return Number(m[1]);
	const q = text.match(/q(?:ues)?(\d+)/i);
	if (q) return Number(q[1]);
	return null;
}

function actorFromMessage(msg: Message, text: string): string {
	if (msg.msg_type === "user") return "User";
	if (msg.msg_type === "progress") return "SystemMonitor";
	if (msg.msg_type === "agent") {
		switch (msg.agent_type) {
			case AgentType.COORDINATOR:
				return "CoordinatorAgent";
			case AgentType.SUB_COORDINATOR:
				return "SubCoordinatorAgent";
			case AgentType.MODELER:
				return "ModelerAgent";
			case AgentType.CODER:
				return "CoderAgent";
			case AgentType.WRITER:
				return "WriterAgent";
		}
	}
	const instance =
		msg.msg_type === "agent"
			? (msg.agent_instance_id ?? msg.group_id ?? "")
			: "";
	if (instance.includes("sub_coordinator")) return "SubCoordinatorAgent";
	if (instance.includes("modeler")) return "ModelerAgent";
	if (instance.includes("coder")) return "CoderAgent";
	if (instance.includes("writer")) return "WriterAgent";
	if (/问题划分|拆解|Coordinator|协调/.test(text)) return "CoordinatorAgent";
	if (/建模|Modeler|模型方案|候选方案/.test(text)) return "ModelerAgent";
	if (/代码|Coder|求解|执行|改错|错误判别/.test(text)) return "CoderAgent";
	if (/论文|Writer|写作|终稿|图片修订|文本修订/.test(text))
		return "WriterAgent";
	return "SystemMonitor";
}

function isLowValueSystem(text: string) {
	const drop = [
		"代码手调用execute_code工具",
		"代码手调用task_complete工具",
		"写作手调用",
		"创建代码沙盒",
		"代码沙盒",
		"创建完成",
		"开始执行代码",
		"代码执行完成",
		"初始化代码手",
		"任务已创建",
		"任务开始处理",
		"消息已发布",
		"保存",
		"Agent 模型配置",
		"传递：工作指令",
		"代码手自行反思纠错",
		"代码手根据协调者建议反思纠错",
		"协调者后台判别不阻塞当前尝试",
		"正在检索文献依据",
		"正在生成模型方案",
		"候选方案生成完成",
		"模型候选方案生成完成",
		"并行生成候选模型方案",
	];
	return drop.some((key) => text.includes(key));
}

function artifactNames(text: string) {
	const set = new Set<string>();
	const re =
		/[\w\-.\u4e00-\u9fa5/]+\.(?:xlsx|xls|csv|png|jpg|jpeg|svg|pdf|md|docx|py)/gi;
	for (const m of text.matchAll(re)) set.add(m[0]);
	return Array.from(set).slice(0, 6);
}

function imageArtifactNames(items?: string[]) {
	return (items ?? []).filter((item) => isImageFile(item));
}

function nonImageArtifactNames(items?: string[]) {
	return (items ?? []).filter((item) => !isImageFile(item));
}

function imageArtifactUrl(filename: string) {
	return resolveTaskImageUrl(filename, props.taskId);
}

function imageEvent(
	msg: Message,
	content: string,
	actor: string,
	questionIndex: number | null,
): TimelineEvent | null {
	const images = artifactNames(content).filter((item) => isImageFile(item));
	if (
		!images.length ||
		!/图片生成完成|已生成图片描述|图片修订完成|图片已重新生成/.test(content)
	) {
		return null;
	}
	const updated = /修订|重新生成/.test(content);
	const firstImage = normalizeImageFilename(images[0]);
	return {
		id: msg.id,
		side: "left",
		actor,
		role: roleMap[actor] ?? "Agent",
		type: "artifact",
		status: "done",
		title:
			images.length > 1
				? `${updated ? "已更新" : "已生成"} ${images.length} 张图片`
				: `${updated ? "图片已更新" : "图片生成完成"}：${firstImage}`,
		detail: "图片已加入右侧图片结果，可直接点击下方缩略图查看。",
		timeLabel: timeLabel(msg.created_at),
		questionIndex,
		badges: [
			...(questionIndex ? [`Q${questionIndex}`] : []),
			updated ? "图片更新" : "新图片",
		],
		artifacts: images,
	};
}

function systemEvent(msg: SystemMessage): TimelineEvent | null {
	const content = msg.content ?? "";
	const line = firstLine(content);
	const actor = actorFromMessage(msg, content);
	const q = detectQuestionIndex(content, msg);
	const base = {
		id: msg.id,
		side: "left" as const,
		actor,
		role: roleMap[actor] ?? "Agent",
		timeLabel: timeLabel(msg.created_at),
		questionIndex: q,
	};
	const generatedImage = imageEvent(msg, content, actor, q);
	if (generatedImage) return generatedImage;

	if (line.includes("等待用户确认问题划分")) {
		return {
			...base,
			type: "choice",
			status: questionConfirmed.value ? "done" : "waiting",
			actor: "CoordinatorAgent",
			role: roleMap.CoordinatorAgent,
			title: questionConfirmed.value
				? "问题划分已确认"
				: "问题划分已生成，请确认",
			detail: questionConfirmed.value
				? "该步骤已完成。"
				: "可在这条对话消息内直接修改、增删问题卡片，确认后继续进入建模方案选择。",
			choiceKind: "question",
			badges: questionConfirmed.value ? ["已确认"] : ["需要用户确认"],
		};
	}
	if (line.includes("问题划分已确认") || line.includes("已复用问题划分")) {
		if (hasExplicitQuestionConfirmMessage.value) return null;
		return {
			...base,
			side: "right",
			actor: "User",
			role: roleMap.User,
			type: "user",
			status: "done",
			title: "已确认问题划分",
			detail: "进入建模方案生成阶段。",
		};
	}
	if (line.includes("等待用户确认各问建模方案")) {
		return {
			...base,
			type: "choice",
			status: modelingConfirmed.value ? "done" : "waiting",
			actor: "ModelerAgent",
			role: roleMap.ModelerAgent,
			title: modelingConfirmed.value
				? "建模方案已确认"
				: "候选建模方案已生成，请选择",
			detail: modelingConfirmed.value
				? "该步骤已完成。"
				: "可在这条对话消息内直接选择每一问的建模方案，也可以要求重新生成。",
			choiceKind: "modeling",
			badges: modelingConfirmed.value ? ["已确认"] : ["需要用户确认"],
		};
	}
	if (line.includes("建模方案已确认") || line.includes("已复用建模方案选择")) {
		if (hasExplicitModelingConfirmMessage.value) return null;
		return {
			...base,
			side: "right",
			actor: "User",
			role: roleMap.User,
			type: "user",
			status: "done",
			title: "已确认建模方案",
			detail: "进入整体建模方案生成阶段。",
		};
	}
	if (/问题拆解完成，共\s*\d+\s*个小问/.test(line)) {
		return {
			...base,
			actor: "CoordinatorAgent",
			role: roleMap.CoordinatorAgent,
			type: "stage",
			status: "done",
			title: "题目解析与问题拆解完成",
			detail: line,
		};
	}
	if (
		/建模手.*(?:深度调研完成|整体建模方案.*(?:完成|已生成)|已从断点恢复整体建模方案)/.test(
			line,
		)
	) {
		return {
			...base,
			actor: "ModelerAgent",
			role: roleMap.ModelerAgent,
			type: "stage",
			status: "done",
			title: "整体建模方案生成完成",
			detail: line,
		};
	}
	if (/建模手.*正在.*(?:生成|调研)/.test(line)) {
		return {
			...base,
			actor: "ModelerAgent",
			role: roleMap.ModelerAgent,
			type: "stage",
			status: "running",
			title: "正在生成整体建模方案",
			detail: line,
		};
	}
	if (isLowValueSystem(line)) return null;

	if (/代码手开始求解/.test(line))
		return {
			...base,
			actor: "CoderAgent",
			role: roleMap.CoderAgent,
			type: "stage",
			status: "running",
			title: q ? `第 ${q} 问开始求解` : "开始代码求解",
			detail: line,
			badges: q ? [`Q${q}`] : [],
		};
	if (/代码手求解成功/.test(line))
		return {
			...base,
			actor: "CoderAgent",
			role: roleMap.CoderAgent,
			type: "artifact",
			status: "done",
			title: q ? `第 ${q} 问求解完成` : "代码求解完成",
			detail: "结果已移交给写作阶段。",
			artifacts: artifactNames(content),
			badges: q ? [`Q${q}`] : [],
		};
	if (/论文手开始写/.test(line))
		return {
			...base,
			actor: "WriterAgent",
			role: roleMap.WriterAgent,
			type: "stage",
			status: "running",
			title: q ? `第 ${q} 问开始写作` : "开始论文写作",
			detail: line,
			badges: q ? [`Q${q}`] : [],
		};
	if (/论文手完成/.test(line))
		return {
			...base,
			actor: "WriterAgent",
			role: roleMap.WriterAgent,
			type: "artifact",
			status: "done",
			title: q ? `第 ${q} 问写作完成` : "写作完成",
			detail: "已生成对应论文段落。",
			artifacts: artifactNames(content),
			badges: q ? [`Q${q}`] : [],
		};
	if (/子问题组#\d+.*启动/.test(line))
		return {
			...base,
			actor: "SubCoordinatorAgent",
			role: roleMap.SubCoordinatorAgent,
			type: "stage",
			status: "running",
			title: q ? `子问题组 ${q} 启动` : "子问题组启动",
			detail: line,
			badges: q ? [`Q${q}`] : [],
		};
	if (/子问题组#\d+.*完成/.test(line))
		return {
			...base,
			actor: "SubCoordinatorAgent",
			role: roleMap.SubCoordinatorAgent,
			type: "stage",
			status: "done",
			title: q ? `子问题组 ${q} 完成` : "子问题组完成",
			detail: "该组结果已提交汇总。",
			badges: q ? [`Q${q}`] : [],
		};
	if (/协调者后台错误判别已启动/.test(line))
		return {
			...base,
			actor: "CoderAgent",
			role: roleMap.CoderAgent,
			type: "progress",
			status: "warning",
			title: "多次改错，协调者后台判别中",
			detail: line,
			progressText: "Coder 继续自行修复，协调者后台判断是否需要换新 Coder。",
			badges: q ? [`Q${q}`, "后台判别"] : ["后台判别"],
		};
	if (/协调者后台错误判别完成|协调者重复错误判别/.test(line)) {
		const restart =
			content.includes("should_restart=true") ||
			content.includes("切换新 Coder");
		return {
			...base,
			actor: "CoderAgent",
			role: roleMap.CoderAgent,
			type: restart ? "warning" : "progress",
			status: restart ? "warning" : "running",
			title: restart ? "反复出错，准备换新 Coder" : "协调者给出改错建议",
			detail: brief(content, 260),
			badges: q ? [`Q${q}`, "改错"] : ["改错"],
		};
	}
	if (/备用\s*Coder|备用\d+|重写中|重新组织方案/.test(line))
		return {
			...base,
			actor: "CoderAgent",
			role: roleMap.CoderAgent,
			type: "warning",
			status: "warning",
			title: "备用 Coder 接手重写",
			detail: brief(content, 220),
			badges: q ? [`Q${q}`, "重写"] : ["重写"],
		};
	if (/已停止|任务执行失败|失败|错误/.test(line))
		return {
			...base,
			type: "error",
			status: "error",
			title: line.slice(0, 80),
			detail: brief(content, 240),
			badges: q ? [`Q${q}`] : [],
		};
	if (/完成终稿整体检查|论文生成完成/.test(line))
		return {
			...base,
			actor: "WriterAgent",
			role: roleMap.WriterAgent,
			type: "artifact",
			status: "done",
			title: "论文终稿完成",
			detail: "可以在右侧论文预览或导出菜单查看结果。",
			artifacts: artifactNames(content),
		};
	if (
		/开始终稿整体检查|集成协调者|并行写作启动|开始灵敏度分析|启动 EDA/.test(
			line,
		)
	)
		return {
			...base,
			type: "stage",
			status: "running",
			title: line.slice(0, 80),
			detail: brief(content, 220),
		};
	if (artifactNames(content).length)
		return {
			...base,
			type: "artifact",
			status: "done",
			title: "生成产物",
			detail: brief(content, 180),
			artifacts: artifactNames(content),
		};
	return {
		...base,
		type: "stage",
		status: msg.type === "success" ? "done" : "running",
		title: line || "流程更新",
		detail: brief(content, 180),
	};
}

function agentEvent(msg: AgentMessage): TimelineEvent | null {
	const content = msg.content ?? "";
	if (!content.trim()) return null;
	const actor = actorFromMessage(msg, content);
	if (isLowValueAgent(content)) return null;
	const q = detectQuestionIndex(content, msg);
	const generatedImage = imageEvent(msg, content, actor, q);
	if (generatedImage) return generatedImage;
	const isStreaming = msg.stream_state === "streaming";
	const structured = isStreaming
		? null
		: structuredAgentSummary(content, actor);
	const isStructuredStream =
		isStreaming &&
		["CoordinatorAgent", "ModelerAgent"].includes(actor) &&
		content.trimStart().startsWith("{");
	const streamingTitle =
		actor === "CoordinatorAgent"
			? "正在解析题目并拆分问题"
			: actor === "ModelerAgent"
				? "正在生成建模方案"
				: "正在思考与生成";
	return {
		id: msg.id,
		side: "left",
		actor,
		role: roleMap[actor] ?? "Agent",
		type: "raw",
		status: isStreaming ? "running" : "done",
		title: structured?.title ?? (isStreaming ? streamingTitle : "输出结果摘要"),
		detail:
			structured?.detail ??
			(isStructuredStream
				? "正在整理结构化结果，完成后将显示简明摘要。"
				: isStreaming
					? readableBrief(tailBrief(content, 720), 520)
					: readableBrief(content, 320)),
		brief:
			content.length > 400
				? isStreaming
					? tailBrief(content, 240)
					: brief(content, 180)
				: undefined,
		timeLabel: timeLabel(msg.created_at),
		questionIndex: q,
		badges: q ? [`Q${q}`] : [],
	};
}

function toolEvent(msg: ToolMessage): TimelineEvent | null {
	if (msg.tool_name !== "execute_code") return null;
	const executeMessage = msg as InterpreterMessage;
	const code = executeMessage.input?.code ?? "";
	const output = executeMessage.output ?? [];
	const hasError = output.some((item) => item.res_type === "error");
	const desc = executeMessage.description || "执行 Python 代码";
	if (!hasError) return null;
	const text = `${executeMessage.content ?? ""}\n${desc}\n${code}`;
	const q = detectQuestionIndex(text, executeMessage);
	return {
		id: msg.id,
		side: "left",
		actor: "CoderAgent",
		role: roleMap.CoderAgent,
		type: "progress",
		status: "warning",
		title: "代码执行出错，正在改错",
		detail: brief(desc || code, 180),
		timeLabel: timeLabel(msg.created_at),
		questionIndex: q,
		badges: q ? [`Q${q}`, "改错"] : ["改错"],
		debugCount: 1,
	};
}

function progressEvent(msg: ProgressMessage): TimelineEvent | null {
	if (!msg.description && msg.percentage == null) return null;
	if (msg.percentage === 0 && /准备中/.test(msg.description ?? "")) return null;
	return {
		id: msg.id,
		side: "center",
		actor: "SystemMonitor",
		role: roleMap.SystemMonitor,
		type: "progress",
		status: msg.percentage >= 100 ? "done" : "running",
		title: msg.description || "任务进度更新",
		progressText: `${msg.percentage ?? 0}%`,
		timeLabel: timeLabel(msg.created_at),
	};
}

const initialUserMessageId = computed(
	() =>
		props.messages.find(
			(message) =>
				message.msg_type === "user" &&
				!message.action &&
				!/用户请求启动或恢复当前建模工作流/.test(message.content ?? ""),
		)?.id ?? "",
);

function userEvent(msg: Message): TimelineEvent | null {
	const content = msg.content ?? "";
	const common = {
		id: msg.id,
		side: "right" as const,
		actor: "User",
		role: roleMap.User,
		type: "user" as const,
		status: "done" as const,
		timeLabel: timeLabel(msg.created_at),
	};
	if (/用户确认了最终的问题划分方案|用户确认全部问题的建模方案/.test(content)) {
		// 对应确认卡本身会切换为“已确认”，不再额外生成重复的用户气泡。
		return null;
	}
	if (/用户请求 ModelerAgent 筛选候选模型/.test(content)) return null;
	if (msg.id === initialUserMessageId.value) {
		const messageFiles = msg.msg_type === "user" ? (msg.files ?? []) : [];
		const inputFiles = messageFiles.length
			? messageFiles
			: legacyInputFiles.value;
		return {
			...common,
			title: "已确定题目信息",
			problemText: content,
			inputFiles,
			badges: inputFiles.length ? [`${inputFiles.length} 个附件`] : [],
		};
	}
	if (/用户一键应用 AI 推荐的最优模型方案|选择最优模型方案/.test(content)) {
		return {
			...common,
			title: "选择最优模型方案",
		};
	}
	const title = brief(content, 80) || "用户确认";
	const detail = brief(content, 220);
	return {
		...common,
		title,
		detail: detail && detail !== title ? detail : undefined,
	};
}

function toEvent(msg: Message): TimelineEvent | null {
	if (
		msg.msg_type === "user" &&
		/用户请求启动或恢复当前建模工作流/.test(msg.content ?? "")
	) {
		return null;
	}
	if (msg.msg_type === "user") return userEvent(msg);
	if (msg.msg_type === "system") return systemEvent(msg);
	if (msg.msg_type === "agent") return agentEvent(msg);
	if (msg.msg_type === "tool") return toolEvent(msg as ToolMessage);
	if (msg.msg_type === "progress") return progressEvent(msg as ProgressMessage);
	return null;
}

function isDebugEvent(ev: TimelineEvent) {
	return (
		ev.actor === "CoderAgent" &&
		ev.type === "progress" &&
		(ev.title === "代码执行出错，正在改错" ||
			/^第\s*\d+\s*次改错/.test(ev.title))
	);
}

const rawEvents = computed(
	() => props.messages.map(toEvent).filter(Boolean) as TimelineEvent[],
);
const timelineEvents = computed(() => {
	const out: TimelineEvent[] = [];
	const seenImages = new Set<string>();
	const seenChoiceKinds = new Set<NonNullable<TimelineEvent["choiceKind"]>>();
	for (const rawEvent of rawEvents.value) {
		const eventImages = imageArtifactNames(rawEvent.artifacts);
		const unseenImages = eventImages.filter((image) => !seenImages.has(image));
		if (eventImages.length && !unseenImages.length) continue;
		for (const image of unseenImages) seenImages.add(image);
		const ev =
			eventImages.length === unseenImages.length
				? rawEvent
				: {
						...rawEvent,
						artifacts: [
							...nonImageArtifactNames(rawEvent.artifacts),
							...unseenImages,
						],
					};
		if (ev.type === "choice" && ev.choiceKind) {
			if (seenChoiceKinds.has(ev.choiceKind)) continue;
			seenChoiceKinds.add(ev.choiceKind);
		}
		const prev = out[out.length - 1];
		if (
			prev &&
			isDebugEvent(prev) &&
			isDebugEvent(ev) &&
			prev.questionIndex === ev.questionIndex
		) {
			const count = (prev.debugCount ?? 1) + 1;
			out[out.length - 1] = {
				...ev,
				id: prev.id,
				title: `第 ${count} 次改错`,
				detail:
					"连续代码执行出错，Coder 正在自行修复；必要时协调者会后台判别是否需要换新 Coder。",
				progressText: `累计 ${count} 次改错`,
				debugCount: count,
				badges: Array.from(
					new Set([...(prev.badges ?? []), ...(ev.badges ?? [])]),
				),
			};
			continue;
		}
		if (isDebugEvent(ev)) {
			out.push({
				...ev,
				title: "第 1 次改错",
				progressText: "累计 1 次改错",
				debugCount: 1,
			});
			continue;
		}
		if (
			prev &&
			prev.actor === ev.actor &&
			prev.type === ev.type &&
			prev.title === ev.title &&
			ev.type !== "choice" &&
			prev.side === ev.side &&
			prev.questionIndex === ev.questionIndex
		) {
			out[out.length - 1] = {
				...ev,
				id: prev.id,
				badges: Array.from(
					new Set([...(prev.badges ?? []), ...(ev.badges ?? [])]),
				),
			};
			continue;
		}
		out.push(ev);
	}
	return out;
});

function isRevisionEvent(ev: TimelineEvent) {
	const text = `${ev.title}\n${ev.detail ?? ""}`;
	return /图片修订|文本修订|AI 修改|修订启动|修订完成/.test(text);
}

function groupKeyOf(ev: TimelineEvent) {
	if (ev.type === "choice" || ev.side !== "left" || isRevisionEvent(ev))
		return "";
	const text = `${ev.title}\n${ev.detail ?? ""}`;
	if (
		ev.questionIndex &&
		["SubCoordinatorAgent", "CoderAgent", "WriterAgent"].includes(ev.actor)
	) {
		return `question-${ev.questionIndex}`;
	}
	if (
		!ev.questionIndex &&
		ev.actor === "WriterAgent" &&
		/并行写作|论文手开始写|论文手完成|正在思考与生成|输出结果摘要/.test(text) &&
		!/终稿|整体检查/.test(text)
	) {
		return "writing-parallel";
	}
	if (ev.actor === "CoderAgent") return "phase-coding";
	if (ev.actor === "SubCoordinatorAgent") return "phase-coding";
	if (ev.actor === "ModelerAgent") return "phase-modeling";
	if (ev.actor === "WriterAgent")
		return /终稿|整体检查|论文生成/.test(text)
			? "phase-final"
			: "writing-parallel";
	if (ev.actor === "CoordinatorAgent")
		return /集成|整合|终稿|整体检查|论文生成/.test(text)
			? "phase-final"
			: "phase-planning";
	return "";
}

function groupStatus(events: TimelineEvent[]): TimelineEvent["status"] {
	if (events.some((ev) => ev.status === "error")) return "error";
	if (events.some((ev) => ev.status === "warning")) return "warning";
	const latest = events[events.length - 1];
	if (latest?.status === "running" || latest?.status === "waiting")
		return latest.status;
	return events.length && events.every((ev) => ev.status === "done")
		? "done"
		: (latest?.status ?? "running");
}

function groupTitle(group: TimelineEvent) {
	const events = group.groupEvents ?? [];
	const latest = events[events.length - 1];
	if (group.groupPhase === "writing") {
		if (group.status === "done") return "并行写作组 · 已完成";
		if (group.status === "warning") return "并行写作组 · 需关注";
		if (group.status === "error") return "并行写作组 · 已停止";
		return "并行写作组 · 写作中";
	}
	if (group.groupPhase !== "question") {
		const label = phaseLabel(group.groupPhase);
		if (group.status === "done") return `${label} · 已完成`;
		if (group.status === "warning") return `${label} · 需关注`;
		if (group.status === "error") return `${label} · 已停止`;
		return `${label} · 进行中`;
	}
	const q = group.questionIndex;
	if (group.status === "error") return `子问题组 ${q} · 已停止`;
	if (group.status === "warning") {
		if (/重写|备用/.test(latest?.title ?? "")) return `子问题组 ${q} · 重写中`;
		if (/判别/.test(latest?.title ?? "")) return `子问题组 ${q} · 后台判别中`;
		return `子问题组 ${q} · 改错中`;
	}
	if (latest?.actor === "WriterAgent") {
		return latest.status === "done"
			? `子问题组 ${q} · 写作完成`
			: `子问题组 ${q} · 写作中`;
	}
	if (/求解完成|子问题组 \d+ 完成/.test(latest?.title ?? ""))
		return `子问题组 ${q} · 求解完成`;
	if (group.status === "done") return `子问题组 ${q} · 已完成`;
	return `子问题组 ${q} · 求解中`;
}

function pushUnique<T>(source: T[] | undefined, values: T[]) {
	return Array.from(new Set([...(source ?? []), ...values]));
}

function groupPhaseFromKey(key: string): TimelineEvent["groupPhase"] {
	if (key.startsWith("question-")) return "question";
	if (key === "writing-parallel") return "writing";
	if (key === "phase-planning") return "planning";
	if (key === "phase-modeling") return "modeling";
	if (key === "phase-coding") return "coding";
	if (key === "phase-final") return "final";
	return "process";
}

function phaseLabel(phase?: TimelineEvent["groupPhase"]) {
	if (phase === "planning") return "规划阶段";
	if (phase === "modeling") return "建模阶段";
	if (phase === "coding") return "代码求解";
	if (phase === "final") return "终稿整合";
	if (phase === "writing") return "并行写作组";
	return "阶段过程";
}

function phaseActor(
	phase?: TimelineEvent["groupPhase"],
	fallback = "SystemMonitor",
) {
	if (phase === "planning" || phase === "final") return "CoordinatorAgent";
	if (phase === "modeling") return "ModelerAgent";
	if (phase === "coding") return "CoderAgent";
	if (phase === "writing") return "WriterAgent";
	if (phase === "question") return "SubCoordinatorAgent";
	return fallback;
}

function makeGroupEvent(key: string, ev: TimelineEvent): TimelineEvent {
	const phase = groupPhaseFromKey(key);
	const isWriting = phase === "writing";
	const isQuestion = phase === "question";
	const actor = phaseActor(phase, ev.actor);
	const group: TimelineEvent = {
		id: `group-${key}-${ev.id}`,
		side: "left",
		actor,
		role: isQuestion ? "子问题组" : phaseLabel(phase),
		type: "stage",
		status: ev.status,
		title: "",
		detail: "",
		timeLabel: ev.timeLabel,
		questionIndex: ev.questionIndex,
		badges: isQuestion
			? ev.questionIndex
				? [`Q${ev.questionIndex}`, "子问题组"]
				: ["子问题组"]
			: [],
		artifacts: [],
		debugCount: 0,
		isGroup: true,
		groupPhase: phase,
		groupEvents: [],
		groupActors: [],
	};
	return group;
}

function updateGroupProgressText(group: TimelineEvent) {
	if (group.status === "done") {
		group.progressText = undefined;
		return;
	}
	group.progressText = group.debugCount
		? `累计 ${group.debugCount} 次改错 / 重试`
		: undefined;
}

function updateGroup(group: TimelineEvent, ev: TimelineEvent) {
	group.groupEvents = [...(group.groupEvents ?? []), ev];
	group.groupActors = pushUnique(group.groupActors, [ev.actor]);
	group.badges = pushUnique(group.badges, ev.badges ?? []);
	group.artifacts = pushUnique(group.artifacts, ev.artifacts ?? []);
	group.debugCount = (group.debugCount ?? 0) + (ev.debugCount ?? 0);
	group.timeLabel = ev.timeLabel || group.timeLabel;
	group.status = groupStatus(group.groupEvents);
	group.title = groupTitle(group);
	const actors = group.groupActors
		.map((actor) => roleMap[actor] ?? actor)
		.join(" / ");
	group.detail =
		group.status === "done"
			? `${actors || group.role} 已完成本阶段，结果已汇总。`
			: "";
	updateGroupProgressText(group);
}

function latestGroupEvent(group: TimelineEvent) {
	const events = group.groupEvents ?? [];
	return events[events.length - 1];
}

function hasDistinctDetail(ev?: TimelineEvent) {
	if (!ev?.detail) return false;
	const detail = stripMarkdown(ev.detail);
	const title = stripMarkdown(ev.title);
	return Boolean(
		detail &&
			detail !== title &&
			(ev.status === "warning" || ev.status === "error" || ev.type === "raw"),
	);
}

function taskCompletedForDisplay() {
	return (
		/论文生成完成|任务处理完成|完成终稿整体检查/.test(allMessageText.value) ||
		props.taskStatus === "completed"
	);
}

function taskStoppedForDisplay() {
	return (
		/任务执行失败|任务已停止|已中断/.test(allMessageText.value) ||
		["failed", "stopped", "interrupted"].includes(props.taskStatus)
	);
}

function normalizeDisplayStatus(status: TimelineEvent["status"]) {
	if (taskCompletedForDisplay() && status !== "warning" && status !== "error")
		return "done";
	if (taskStoppedForDisplay() && (status === "running" || status === "waiting"))
		return "warning";
	return status;
}

function normalizeDisplayEvent(ev: TimelineEvent): TimelineEvent {
	const normalized: TimelineEvent = {
		...ev,
		status: normalizeDisplayStatus(ev.status),
	};
	if (ev.groupEvents?.length) {
		normalized.groupEvents = ev.groupEvents.map(normalizeDisplayEvent);
	}
	return normalized;
}

const displayEvents = computed(() => {
	const out: TimelineEvent[] = [];
	const groupMap = new Map<string, TimelineEvent>();
	for (const ev of timelineEvents.value) {
		if (ev.type === "progress") {
			continue;
		}

		const key = groupKeyOf(ev);
		if (!key) {
			out.push(ev);
			continue;
		}
		const existingGroup = groupMap.get(key);
		if (existingGroup) {
			updateGroup(existingGroup, ev);
		} else {
			const group = makeGroupEvent(key, ev);
			groupMap.set(key, group);
			out.push(group);
			updateGroup(group, ev);
		}
	}
	return out.map(normalizeDisplayEvent);
});

const hasQuestionWait = computed(() =>
	allMessageText.value.includes("等待用户确认问题划分"),
);
const hasModelingWait = computed(() =>
	allMessageText.value.includes("等待用户确认各问建模方案"),
);
const hasSolvingStarted = computed(() =>
	/代码手开始求解|子问题组#\d+.*启动|开始求解/.test(allMessageText.value),
);
const hasSolvingDone = computed(() =>
	/代码手求解成功|子问题组#\d+.*完成/.test(allMessageText.value),
);
const hasSolvingPhaseDone = computed(() =>
	/并行写作启动|开始终稿整体检查|论文生成完成|任务处理完成/.test(
		allMessageText.value,
	),
);
const hasWritingStarted = computed(() =>
	/论文手开始写|并行写作启动|开始终稿整体检查/.test(allMessageText.value),
);
const hasWritingDone = computed(() =>
	/开始终稿整体检查|论文生成完成|完成终稿整体检查|任务处理完成/.test(
		allMessageText.value,
	),
);
const hasFinalDone = computed(
	() =>
		/论文生成完成|任务处理完成|完成终稿整体检查/.test(allMessageText.value) ||
		props.taskStatus === "completed",
);
const hasFlowWarning = computed(() =>
	/任务执行失败|已停止|should_restart=true|切换新 Coder|后台判别/.test(
		allMessageText.value,
	),
);

const flowSteps = computed<FlowStep[]>(() => {
	const planningDone =
		hasQuestionWait.value ||
		questionConfirmed.value ||
		modelingConfirmed.value ||
		hasSolvingStarted.value;
	const solvingQuestions = questionStatuses.value.filter((q) =>
		[
			"solving",
			"debugging",
			"judging",
			"restarting",
			"recoding",
			"plotting",
		].includes(q.status),
	);
	const writingQuestions = questionStatuses.value.filter((q) =>
		["writing"].includes(q.status),
	);
	const solvingDetail = solvingQuestions.length
		? `${solvingQuestions.length} 个子问题并行求解`
		: "子问题求解中";
	const writingDetail = writingQuestions.length
		? `${writingQuestions.length} 个子问题并行写作`
		: "写作中";
	return [
		{
			key: "planning",
			label: "规划",
			status: planningDone
				? "done"
				: props.messages.length
					? "active"
					: "pending",
			detail: planningDone ? "题目拆解完成" : "等待题目拆解",
		},
		{
			key: "question",
			label: "问题确认",
			status: questionConfirmed.value
				? "done"
				: hasQuestionWait.value
					? "active"
					: "pending",
			detail: questionConfirmed.value
				? "已确认"
				: hasQuestionWait.value
					? "等待用户确认"
					: "未开始",
		},
		{
			key: "modeling",
			label: "建模确认",
			status: modelingConfirmed.value
				? "done"
				: hasModelingWait.value
					? "active"
					: questionConfirmed.value
						? "active"
						: "pending",
			detail: modelingConfirmed.value
				? "已确认"
				: hasModelingWait.value
					? "等待方案选择"
					: questionConfirmed.value
						? "生成方案中"
						: "未开始",
		},
		{
			key: "solving",
			label: "代码求解",
			status: hasSolvingPhaseDone.value
				? "done"
				: hasSolvingStarted.value
					? hasFlowWarning.value
						? "warning"
						: "active"
					: "pending",
			detail: hasSolvingPhaseDone.value
				? "已移交写作"
				: hasSolvingStarted.value
					? solvingDetail
					: "未开始",
		},
		{
			key: "writing",
			label: "论文写作",
			status: hasWritingDone.value
				? "done"
				: hasWritingStarted.value || hasSolvingDone.value
					? "active"
					: "pending",
			detail: hasWritingDone.value
				? "章节写作完成"
				: hasWritingStarted.value || hasSolvingDone.value
					? writingDetail
					: "未开始",
		},
		{
			key: "final",
			label: "终稿",
			status: hasFinalDone.value
				? "done"
				: hasWritingDone.value
					? "active"
					: "pending",
			detail: hasFinalDone.value
				? "终稿完成"
				: hasWritingDone.value
					? "终稿整合中"
					: "未开始",
		},
	];
});

const questionStatuses = computed<QuestionStatus[]>(() => {
	const map = new Map<number, QuestionStatus>();
	function ensure(index: number) {
		const existing = map.get(index);
		if (existing) return existing;
		const created: QuestionStatus = {
			index,
			label: `Q${index}`,
			status: "pending",
			detail: "等待",
			debugCount: 0,
		};
		map.set(index, created);
		return created;
	}
	for (const msg of props.messages) {
		const text = messageText(msg);
		const q = detectQuestionIndex(text, msg);
		if (!q) continue;
		const item = ensure(q);
		const isDone = item.status === "done";
		if (/论文手完成|子问题组#\d+.*完成/.test(text)) {
			item.status = "done";
			item.detail = "完成";
			continue;
		}
		if (isDone) continue;
		if (/任务执行失败|代码手已停止|失败/.test(text)) {
			item.status = "failed";
			item.detail = "失败";
			continue;
		}
		if (/备用\s*Coder|备用\d+|重写中|重新组织方案/.test(text)) {
			item.status = "recoding";
			item.detail = "备用重写中";
			continue;
		}
		if (/should_restart=true|准备换新\s*Coder|切换新\s*Coder/.test(text)) {
			item.status = "restarting";
			item.detail = "准备换人";
			continue;
		}
		if (/协调者后台错误判别已启动|后台判别中/.test(text)) {
			item.status = "judging";
			item.detail = "后台判别中";
			continue;
		}
		if (/代码执行出错|Traceback|执行错误|改错|同类错误/.test(text)) {
			item.debugCount = (item.debugCount ?? 0) + 1;
			item.status = "debugging";
			item.detail = `第 ${item.debugCount} 次改错`;
			continue;
		}
		if (/代码手求解成功|论文手开始写/.test(text)) {
			item.status = "writing";
			item.detail = "写作中";
			continue;
		}
		if (/代码手开始求解|子问题组#\d+.*启动/.test(text)) {
			item.status = "solving";
			item.detail = "求解中";
		}
	}
	return Array.from(map.values())
		.sort((a, b) => a.index - b.index)
		.slice(0, 8);
});

const activeWork = computed(() => {
	const container = [...displayEvents.value]
		.reverse()
		.find(
			(event) =>
				event.status === "running" ||
				event.status === "warning" ||
				event.status === "waiting",
		);
	const latest = container?.isGroup ? latestGroupEvent(container) : container;
	if (!container || !latest) {
		return {
			actor: "SystemMonitor",
			role: "流程监控",
			title: props.taskStatus === "completed" ? "任务已完成" : "等待任务启动",
			status: props.taskStatus === "completed" ? "done" : "waiting",
		};
	}
	return {
		actor: latest.actor,
		role: roleMap[latest.actor] ?? latest.role,
		title: latest.title,
		status: latest.status ?? container.status ?? "running",
	};
});
const progressSummary = computed(() => {
	const total = displayEvents.value.length;
	const done = displayEvents.value.filter((e) => e.status === "done").length;
	const warnings = displayEvents.value.filter(
		(e) => e.status === "warning" || e.status === "error",
	).length;
	return { total, done, warnings };
});

function actorIcon(actor: string) {
	if (actor === "User") return UserRound;
	if (actor === "CoderAgent") return Code2;
	if (actor === "WriterAgent") return PenLine;
	if (actor === "ModelerAgent") return Sparkles;
	if (actor === "SystemMonitor") return Clock3;
	if (actor === "SubCoordinatorAgent") return Wrench;
	return Bot;
}

function statusIcon(ev: TimelineEvent) {
	if (ev.status === "done") return CheckCircle2;
	if (ev.status === "warning") return AlertTriangle;
	if (ev.status === "error") return AlertTriangle;
	if (ev.type === "choice") return MessageSquareText;
	return LoaderCircle;
}

function toggleProblemDetail(eventId: string) {
	const next = new Set(expandedProblemIds.value);
	if (next.has(eventId)) {
		next.delete(eventId);
	} else {
		next.add(eventId);
	}
	expandedProblemIds.value = next;
}

function inputFileType(filename: string) {
	const extension = filename.split(".").pop()?.toLowerCase() ?? "";
	if (extension === "xlsx" || extension === "xls") return "Excel 数据";
	if (extension === "csv") return "CSV 数据";
	if (extension === "docx" || extension === "doc") return "Word 文档";
	if (extension === "txt" || extension === "md") return "文本数据";
	return "附件";
}

function inputFileIcon(filename: string) {
	const extension = filename.split(".").pop()?.toLowerCase() ?? "";
	return ["xlsx", "xls", "csv"].includes(extension)
		? FileSpreadsheet
		: FileText;
}

async function loadLegacyInputFiles(taskId?: string) {
	legacyInputFiles.value = [];
	if (!taskId) return;
	try {
		const response = await getOriginalProblem(taskId);
		const supportedExtensions = new Set(["txt", "csv", "xlsx"]);
		legacyInputFiles.value = (response.data.files ?? []).filter((filename) => {
			const extension = filename.split(".").pop()?.toLowerCase() ?? "";
			return !filename.includes("/") && supportedExtensions.has(extension);
		});
	} catch {
		// 旧任务附件读取失败时仍保留紧凑的题目信息卡片。
	}
}

function flowStepClass(status: FlowStep["status"]) {
	if (status === "done") return "border-blue-200 bg-blue-50 text-blue-700";
	if (status === "active")
		return "border-emerald-200 bg-emerald-50 text-emerald-700 shadow-[0_0_0_2px_rgba(16,185,129,0.08)]";
	if (status === "warning")
		return "border-amber-200 bg-amber-50 text-amber-700 shadow-[0_0_0_2px_rgba(245,158,11,0.08)]";
	return "border-slate-200 bg-slate-50 text-slate-400";
}

function questionStatusClass(status: QuestionStatusType) {
	if (status === "done") return "border-blue-200 bg-blue-50 text-blue-700";
	if (status === "solving")
		return "border-emerald-200 bg-emerald-50 text-emerald-700";
	if (status === "writing")
		return "border-violet-200 bg-violet-50 text-violet-700";
	if (status === "debugging")
		return "border-amber-200 bg-amber-50 text-amber-700";
	if (status === "judging")
		return "border-orange-200 bg-orange-50 text-orange-700";
	if (status === "restarting" || status === "recoding")
		return "border-red-200 bg-red-50 text-red-700";
	if (status === "failed") return "border-red-300 bg-red-100 text-red-800";
	if (status === "plotting") return "border-cyan-200 bg-cyan-50 text-cyan-700";
	return "border-slate-200 bg-slate-50 text-slate-400";
}

function scrollStreamingDetailsToBottom() {
	nextTick(() => {
		const el = scrollRef.value;
		if (!el) return;
		for (const node of el.querySelectorAll<HTMLElement>(
			"[data-streaming-detail='true']",
		)) {
			node.scrollTop = node.scrollHeight;
		}
	});
}

function scrollToBottom(force = false) {
	const el = scrollRef.value;
	if (!el) return;
	if (!force && userScrolledUp.value) return;
	nextTick(() =>
		el.scrollTo({
			top: el.scrollHeight,
			behavior: hasStreamingMessage.value ? "auto" : "smooth",
		}),
	);
}

function onScroll() {
	const el = scrollRef.value;
	if (!el) return;
	userScrolledUp.value = el.scrollHeight - el.scrollTop - el.clientHeight > 120;
}

watch(
	() => props.taskId,
	(taskId) => loadLegacyInputFiles(taskId),
	{ immediate: true },
);
watch(
	() => props.messages.length,
	() => scrollToBottom(),
	{ flush: "post" },
);
watch(
	streamingSignature,
	() => {
		if (!streamingSignature.value) return;
		scrollToBottom();
		scrollStreamingDetailsToBottom();
	},
	{ flush: "post" },
);
watch(
	displayEvents,
	() => {
		if (!hasStreamingMessage.value) return;
		scrollStreamingDetailsToBottom();
	},
	{ flush: "post" },
);
</script>

<template>
	<div class="flex h-full min-h-0 flex-col bg-slate-50/70">
		<div class="border-b border-slate-200/80 bg-white/80 px-3 py-2.5 backdrop-blur">
			<div class="flex min-w-0 items-center gap-2">
				<div class="flex shrink-0 items-center gap-1.5 text-slate-800">
					<MessageSquareText class="h-4 w-4 text-blue-600" />
					<span class="text-xs font-bold">Agent 流程</span>
				</div>
				<div class="h-4 w-px shrink-0 bg-slate-200" />
				<div class="flex min-w-0 flex-1 items-center gap-1.5 rounded-lg border border-emerald-100 bg-emerald-50/70 px-2 py-1">
					<LoaderCircle
						v-if="activeWork.status === 'running'"
						class="h-3.5 w-3.5 shrink-0 animate-spin text-emerald-600"
					/>
					<AlertTriangle
						v-else-if="activeWork.status === 'warning' || activeWork.status === 'error'"
						class="h-3.5 w-3.5 shrink-0 text-amber-600"
					/>
					<CheckCircle2
						v-else-if="activeWork.status === 'done'"
						class="h-3.5 w-3.5 shrink-0 text-blue-600"
					/>
					<Clock3 v-else class="h-3.5 w-3.5 shrink-0 text-slate-400" />
					<span class="shrink-0 text-[10px] font-semibold text-emerald-700">
						{{ activeWork.status === 'running' ? '正在工作' : activeWork.status === 'done' ? '已完成' : activeWork.status === 'waiting' ? '等待中' : '需关注' }}
					</span>
					<span class="shrink-0 text-[10px] text-slate-400">{{ activeWork.actor }}</span>
					<span class="truncate text-[11px] font-semibold text-slate-800">{{ activeWork.title }}</span>
				</div>
				<div class="shrink-0 text-[10px] text-slate-500">
					{{ progressSummary.done }}/{{ progressSummary.total }}
					<span v-if="progressSummary.warnings" class="text-amber-600">· {{ progressSummary.warnings }} 提醒</span>
				</div>
			</div>

			<div class="mt-2 flex items-center gap-1 overflow-x-auto pb-0.5">
				<div
					v-for="step in flowSteps"
					:key="step.key"
					class="flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold"
					:class="flowStepClass(step.status)"
					:title="step.detail"
				>
					<CheckCircle2 v-if="step.status === 'done'" class="h-3 w-3" />
					<LoaderCircle v-else-if="step.status === 'active'" class="h-3 w-3 animate-spin" />
					<AlertTriangle v-else-if="step.status === 'warning'" class="h-3 w-3" />
					<span v-else class="h-1.5 w-1.5 rounded-full bg-current opacity-50" />
					{{ step.label }}
				</div>
				<div class="mx-1 h-3 w-px shrink-0 bg-slate-200" />
				<div
					v-for="q in questionStatuses"
					:key="q.index"
					class="shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold"
					:class="questionStatusClass(q.status)"
				>
					{{ q.label }} · {{ q.detail }}
				</div>
			</div>
		</div>

		<div
			ref="scrollRef"
			data-agent-timeline-scroll="true"
			class="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-3 py-3"
			@scroll="onScroll"
		>
			<div v-if="displayEvents.length === 0" class="flex h-full items-center justify-center text-sm text-slate-400">任务消息会以对话流形式显示在这里。</div>

			<div v-for="ev in displayEvents" :key="ev.id" class="flex" :class="{ 'justify-end': ev.side === 'right', 'justify-center': ev.side === 'center', 'justify-start': ev.side === 'left' }">
				<div v-if="ev.side === 'center'" class="max-w-[90%] rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-500 shadow-sm">{{ ev.title }} <span v-if="ev.progressText" class="ml-1 font-mono text-blue-600">{{ ev.progressText }}</span></div>

				<div v-else class="flex max-w-[98%] gap-1.5" :class="{ 'flex-row-reverse': ev.side === 'right' }">
					<div class="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full shadow-sm" :class="{ 'bg-blue-600 text-white': ev.side === 'left' && ev.status !== 'warning' && ev.status !== 'error', 'bg-amber-500 text-white': ev.status === 'warning', 'bg-red-500 text-white': ev.status === 'error', 'bg-slate-900 text-white': ev.side === 'right' }"><component :is="actorIcon(ev.actor)" class="h-3.5 w-3.5" /></div>

					<div class="min-w-0 rounded-2xl border px-3 py-2.5 shadow-sm" :class="{ 'rounded-tl-md border-slate-200 bg-white text-slate-800': ev.side === 'left' && ev.status !== 'warning' && ev.status !== 'error', 'rounded-tr-md border-slate-800 bg-slate-900 text-white': ev.side === 'right', 'rounded-tl-md border-amber-200 bg-amber-50 text-amber-950': ev.status === 'warning', 'rounded-tl-md border-red-200 bg-red-50 text-red-950': ev.status === 'error', 'subproblem-group-card': ev.isGroup }">
						<div class="flex items-start justify-between gap-3">
							<div class="min-w-0">
								<div class="flex flex-wrap items-center gap-1.5"><span class="text-[11px] font-semibold opacity-70">{{ ev.actor }}</span><span class="text-[10px] opacity-45">{{ ev.role }}</span><span v-for="badge in ev.badges" :key="badge" class="rounded-full border px-1.5 py-0.5 text-[10px] opacity-80">{{ badge }}</span></div>
								<div class="mt-1 flex items-center gap-1.5 text-sm font-semibold"><component :is="statusIcon(ev)" class="h-3.5 w-3.5" :class="{ 'animate-spin': ev.status === 'running' }" /><span>{{ ev.title }}</span></div>
							</div>
							<span class="shrink-0 text-[10px] opacity-45">{{ ev.timeLabel }}</span>
						</div>

						<p v-if="ev.detail && !ev.isGroup" class="message-detail mt-1.5 whitespace-pre-wrap break-words text-xs leading-relaxed opacity-80" :class="{ 'streaming-detail': ev.status === 'running' && ev.type === 'raw' }" :data-streaming-detail="ev.status === 'running' && ev.type === 'raw' ? 'true' : undefined">{{ ev.detail }}</p>
						<div v-if="ev.problemText" class="mt-2 flex flex-wrap gap-1.5">
							<button
								type="button"
								class="inline-flex max-w-full items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-2.5 py-1 text-[11px] font-medium transition hover:bg-white/15"
								:title="expandedProblemIds.has(ev.id) ? '收起题目信息' : '查看题目信息'"
								@click="toggleProblemDetail(ev.id)"
							>
								<FileText class="h-3.5 w-3.5 shrink-0 text-blue-200" />
								<span>题目信息</span>
								<span class="opacity-55">题目文本</span>
								<ChevronDown class="h-3 w-3 shrink-0 transition-transform" :class="{ 'rotate-180': expandedProblemIds.has(ev.id) }" />
							</button>
							<button
								v-for="file in ev.inputFiles"
								:key="file"
								type="button"
								class="inline-flex max-w-full items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-2.5 py-1 text-[11px] font-medium transition hover:bg-white/15"
								:title="`下载 ${file}`"
								@click="emit('fileOpen', file)"
							>
								<component :is="inputFileIcon(file)" class="h-3.5 w-3.5 shrink-0 text-emerald-200" />
								<span class="max-w-44 truncate">{{ file }}</span>
								<span class="shrink-0 opacity-55">{{ inputFileType(file) }}</span>
								<Download class="h-3 w-3 shrink-0 opacity-60" />
							</button>
						</div>
						<p
							v-if="ev.problemText && expandedProblemIds.has(ev.id)"
							class="message-detail mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap break-words rounded-xl border border-white/10 bg-white/5 px-2.5 py-2 text-xs leading-relaxed opacity-80"
						>
							{{ ev.problemText }}
						</p>
						<p v-if="ev.progressText && !ev.isGroup" class="mt-1.5 rounded-lg border border-current/10 bg-white/45 px-2 py-1 text-[11px] opacity-90">{{ ev.progressText }}</p>

						<div v-if="ev.groupEvents?.length && ev.status !== 'done' && latestGroupEvent(ev)" class="mt-2 rounded-xl border border-slate-200/70 bg-white/60 px-2.5 py-2 shadow-inner">
							<div class="flex items-center gap-1.5 text-[11px]">
								<span class="flex shrink-0 items-center gap-1 rounded-full bg-emerald-50 px-1.5 py-0.5 font-bold text-emerald-700">
									<span class="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
									当前
								</span>
								<span class="min-w-0 flex-1 truncate font-semibold text-slate-700">{{ latestGroupEvent(ev)?.actor }} · {{ latestGroupEvent(ev)?.title }}</span>
								<span class="shrink-0 text-[10px] text-slate-400">{{ latestGroupEvent(ev)?.timeLabel }}</span>
							</div>
							<div
								v-if="hasDistinctDetail(latestGroupEvent(ev))"
								class="message-detail streaming-detail mt-1.5 whitespace-pre-line break-words text-[11px] leading-relaxed text-slate-500"
								data-streaming-detail="true"
							>
								{{ latestGroupEvent(ev)?.detail }}
							</div>
						</div>

						<div v-if="ev.type === 'choice'" class="choice-attachment mt-3 overflow-hidden rounded-2xl border border-slate-200 bg-white text-slate-800 shadow-sm">
							<div class="flex items-start justify-between gap-3 border-b border-slate-100 bg-slate-50 px-3 py-2">
								<div class="min-w-0">
									<div class="flex items-center gap-1.5 text-[11px] font-bold text-slate-700">
										<MessageSquareText class="h-3.5 w-3.5 text-blue-600" />
										<span>{{ ev.choiceKind === 'question' ? '问题划分附件' : '建模方案附件' }}</span>
									</div>
									<p class="mt-0.5 truncate text-[10px] text-slate-500">
										{{ ev.choiceKind === 'question'
											? (questionConfirmed ? '问题划分已确认，流程会继续进入建模方案。' : '请确认题目拆成哪些子问题，可先修改再确认。')
											: (modelingConfirmed ? '建模方案已确认，ModelerAgent 将先生成整体方案。' : '请为每一问选择建模方案，可重新生成或自定义。') }}
									</p>
								</div>
								<div class="flex shrink-0 items-center gap-1.5">
									<span class="rounded-full px-2 py-0.5 text-[10px] font-semibold" :class="(ev.choiceKind === 'question' ? questionConfirmed : modelingConfirmed) ? 'bg-blue-50 text-blue-700' : 'bg-amber-50 text-amber-700'">
										{{ (ev.choiceKind === 'question' ? questionConfirmed : modelingConfirmed) ? '已确认' : '待确认' }}
									</span>
									<button
										v-if="!(ev.choiceKind === 'question' ? questionConfirmed : modelingConfirmed)"
										class="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-600 hover:bg-slate-100"
										@click="ev.choiceKind === 'question' ? (inlineQuestionPanelOpen = !inlineQuestionPanelOpen) : (inlineModelingPanelOpen = !inlineModelingPanelOpen)"
									>
										{{ ev.choiceKind === 'question' ? (inlineQuestionPanelOpen ? '收起' : '展开') : (inlineModelingPanelOpen ? '收起' : '展开') }}
									</button>
								</div>
							</div>

							<div v-if="ev.choiceKind === 'question' && questionConfirmed" class="flex items-center gap-2 px-3 py-3 text-xs text-blue-700">
								<CheckCircle2 class="h-4 w-4 shrink-0" />
								<span>问题划分已确认，后续 Agent 将基于该问题结构生成建模方案。</span>
							</div>
							<div v-else-if="ev.choiceKind === 'modeling' && modelingConfirmed" class="flex items-center gap-2 px-3 py-3 text-xs text-blue-700">
								<CheckCircle2 class="h-4 w-4 shrink-0" />
								<span>建模方案已确认，ModelerAgent 将先生成整体建模方案，再交给 Coder 求解。</span>
							</div>
							<div v-else class="agent-conversation-inline-panel p-2 text-xs text-slate-800">
								<QuestionDiscussion
									v-if="ev.choiceKind === 'question' && props.taskId"
									:task_id="props.taskId"
									:expanded="inlineQuestionPanelOpen"
									:locked="false"
									:disabled="false"
									@toggle="inlineQuestionPanelOpen = !inlineQuestionPanelOpen"
									@confirm="handleInlineQuestionConfirm"
								/>
								<ModelingDiscussion
									v-else-if="ev.choiceKind === 'modeling'"
									:expanded="inlineModelingPanelOpen"
									:locked="false"
									:disabled="false"
									@toggle="inlineModelingPanelOpen = !inlineModelingPanelOpen"
									@confirm="handleInlineModelingConfirm"
								/>
							</div>
						</div>

						<div v-if="imageArtifactNames(ev.artifacts).length" class="mt-3">
							<div class="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold text-slate-500">
								<ImageIcon class="h-3 w-3 text-blue-500" />
								<span>图片产物</span>
								<span class="rounded-full bg-blue-50 px-1.5 py-0.5 text-blue-600">{{ imageArtifactNames(ev.artifacts).length }} 张</span>
							</div>
							<div class="grid max-h-72 grid-cols-2 gap-2 overflow-y-auto pr-1">
								<button
									v-for="file in imageArtifactNames(ev.artifacts)"
									:key="file"
									type="button"
									class="group/image overflow-hidden rounded-xl border border-slate-200 bg-white/80 text-left shadow-sm transition hover:border-blue-300 hover:shadow-md"
									:title="`查看图片 ${file}`"
									@click="emit('imageOpen', file)"
								>
									<div class="flex h-24 items-center justify-center overflow-hidden bg-slate-50">
										<img :src="imageArtifactUrl(file)" :alt="normalizeImageFilename(file)" class="h-full w-full object-contain transition duration-200 group-hover/image:scale-[1.03]" loading="lazy" />
									</div>
									<div class="flex items-center gap-1.5 border-t border-slate-100 px-2 py-1.5 text-[10px] font-medium text-slate-600">
										<ImageIcon class="h-3 w-3 shrink-0 text-blue-500" />
										<span class="truncate">{{ normalizeImageFilename(file) }}</span>
									</div>
								</button>
							</div>
						</div>
						<div v-if="nonImageArtifactNames(ev.artifacts).length" class="mt-3 grid gap-1.5">
							<div v-for="file in nonImageArtifactNames(ev.artifacts)" :key="file" class="flex items-center gap-2 rounded-xl border border-current/10 bg-white/55 px-2.5 py-1.5 text-xs"><FileText class="h-3.5 w-3.5 opacity-70" /><span class="truncate">{{ file }}</span></div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>

<style>
.agent-conversation-inline-panel .question-discussion,
.agent-conversation-inline-panel .modeling-discussion {
	display: flex !important;
	max-height: none !important;
	border-radius: 0.75rem;
	border: 1px solid rgba(226, 232, 240, 0.8);
	box-shadow: none !important;
}

.agent-conversation-inline-panel .question-discussion > button,
.agent-conversation-inline-panel .modeling-discussion > button {
	display: none !important;
}

.choice-attachment .question-discussion,
.choice-attachment .modeling-discussion {
	background: transparent !important;
}

.subproblem-group-card {
	min-width: min(620px, 100%);
	background:
		radial-gradient(circle at 14% 0%, rgba(255, 255, 255, 0.82), transparent 38%),
		linear-gradient(135deg, rgba(255, 255, 255, 0.88), rgba(241, 245, 249, 0.74)) !important;
	backdrop-filter: blur(18px) saturate(1.15);
	-webkit-backdrop-filter: blur(18px) saturate(1.15);
}

.streaming-detail {
	max-height: 8.5rem;
	overflow-y: auto;
	padding-right: 0.25rem;
	scrollbar-width: thin;
}

.message-detail {
	overflow-wrap: anywhere;
	word-break: break-word;
}

</style>
