<script setup lang="ts">
import type { TaskRuntimeStatus } from "@/apis/commonApi";
import type { Message, ProgressMessage, ToolMessage } from "@/utils/response";
import { AgentType } from "@/utils/enum";
import QuestionDiscussion from "@/components/QuestionDiscussion.vue";
import ModelingDiscussion from "@/components/ModelingDiscussion.vue";
import {
	Bot,
	CheckCircle2,
	Clock3,
	Code2,
	FileText,
	LoaderCircle,
	MessageSquareText,
	PenLine,
	Sparkles,
	UserRound,
	Wrench,
	AlertTriangle,
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
}>();

interface TimelineEvent {
	id: string;
	side: "left" | "right" | "center";
	actor: string;
	role: string;
	type: "stage" | "choice" | "progress" | "artifact" | "warning" | "error" | "user" | "raw";
	title: string;
	detail?: string;
	brief?: string;
	status?: "running" | "done" | "warning" | "error" | "waiting";
	timeLabel: string;
	questionIndex?: number | null;
	badges?: string[];
	artifacts?: string[];
	choiceKind?: "question" | "modeling";
	progressText?: string;
}

interface FlowStep {
	key: string;
	label: string;
	status: "pending" | "active" | "done" | "warning";
	detail: string;
}

interface QuestionStatus {
	index: number;
	label: string;
	status: "pending" | "solving" | "writing" | "done" | "warning";
	detail: string;
}

const scrollRef = ref<HTMLDivElement | null>(null);
const userScrolledUp = ref(false);
const inlineQuestionPanelOpen = ref(true);
const inlineModelingPanelOpen = ref(true);

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

const allMessageText = computed(() => props.messages.map(messageText).join("\n"));

const questionConfirmed = computed(() =>
	props.messages.some((m) => {
		const c = messageText(m);
		return c.includes("问题划分已确认") || c.includes("已复用问题划分") || c.includes("用户确认了最终的问题划分方案");
	}),
);

const modelingConfirmed = computed(() =>
	props.messages.some((m) => {
		const c = messageText(m);
		return c.includes("建模方案已确认") || c.includes("已复用建模方案选择") || c.includes("用户确认全部问题的建模方案");
	}),
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

function detectQuestionIndex(text: string, msg?: any): number | null {
	if (typeof msg?.question_index === "number") return msg.question_index;
	const m = text.match(/(?:\[组#|子问题组#|第\s*)(\d+)/);
	if (m) return Number(m[1]);
	const q = text.match(/q(?:ues)?(\d+)/i);
	if (q) return Number(q[1]);
	return null;
}

function actorFromMessage(msg: Message, text: string): string {
	const anyMsg = msg as any;
	const instance = anyMsg.agent_instance_id || anyMsg.group_id || "";
	if (msg.msg_type === "user") return "User";
	if (msg.msg_type === "progress") return "SystemMonitor";
	if (instance.includes("sub_coordinator")) return "SubCoordinatorAgent";
	if (instance.includes("modeler")) return "ModelerAgent";
	if (instance.includes("coder")) return "CoderAgent";
	if (instance.includes("writer")) return "WriterAgent";
	if (msg.msg_type === "agent") {
		switch ((msg as any).agent_type) {
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
	if (/问题划分|拆解|Coordinator|协调/.test(text)) return "CoordinatorAgent";
	if (/建模|Modeler|模型方案|候选方案/.test(text)) return "ModelerAgent";
	if (/代码|Coder|求解|执行|改错|错误判别/.test(text)) return "CoderAgent";
	if (/论文|Writer|写作|终稿|图片修订|文本修订/.test(text)) return "WriterAgent";
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
		"传递：工作指令",
	];
	return drop.some((key) => text.includes(key));
}

function artifactNames(text: string) {
	const set = new Set<string>();
	const re = /[\w\-.\u4e00-\u9fa5/]+\.(?:xlsx|xls|csv|png|jpg|jpeg|svg|pdf|md|docx|py)/gi;
	for (const m of text.matchAll(re)) set.add(m[0]);
	return Array.from(set).slice(0, 6);
}

function systemEvent(msg: Message): TimelineEvent | null {
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

	if (line.includes("等待用户确认问题划分")) {
		return {
			...base,
			type: "choice",
			status: questionConfirmed.value ? "done" : "waiting",
			actor: "CoordinatorAgent",
			role: roleMap.CoordinatorAgent,
			title: questionConfirmed.value ? "问题划分已确认" : "问题划分已生成，请确认",
			detail: questionConfirmed.value ? "该步骤已完成。" : "可在这条对话消息内直接修改、增删问题卡片，确认后继续进入建模方案选择。",
			choiceKind: "question",
			badges: questionConfirmed.value ? ["已确认"] : ["需要用户确认"],
		};
	}
	if (line.includes("问题划分已确认") || line.includes("已复用问题划分")) {
		return { ...base, side: "right", actor: "User", role: roleMap.User, type: "user", status: "done", title: "已确认问题划分", detail: "进入建模方案生成阶段。" };
	}
	if (line.includes("等待用户确认各问建模方案")) {
		return {
			...base,
			type: "choice",
			status: modelingConfirmed.value ? "done" : "waiting",
			actor: "ModelerAgent",
			role: roleMap.ModelerAgent,
			title: modelingConfirmed.value ? "建模方案已确认" : "候选建模方案已生成，请选择",
			detail: modelingConfirmed.value ? "该步骤已完成。" : "可在这条对话消息内直接选择每一问的建模方案，也可以要求重新生成。",
			choiceKind: "modeling",
			badges: modelingConfirmed.value ? ["已确认"] : ["需要用户确认"],
		};
	}
	if (line.includes("建模方案已确认") || line.includes("已复用建模方案选择")) {
		return { ...base, side: "right", actor: "User", role: roleMap.User, type: "user", status: "done", title: "已确认建模方案", detail: "开始进入代码求解。" };
	}
	if (isLowValueSystem(line)) return null;

	if (/代码手开始求解/.test(line)) return { ...base, actor: "CoderAgent", role: roleMap.CoderAgent, type: "stage", status: "running", title: q ? `第 ${q} 问开始求解` : "开始代码求解", detail: line, badges: q ? [`Q${q}`] : [] };
	if (/代码手求解成功/.test(line)) return { ...base, actor: "CoderAgent", role: roleMap.CoderAgent, type: "artifact", status: "done", title: q ? `第 ${q} 问求解完成` : "代码求解完成", detail: "结果已移交给写作阶段。", artifacts: artifactNames(content), badges: q ? [`Q${q}`] : [] };
	if (/论文手开始写/.test(line)) return { ...base, actor: "WriterAgent", role: roleMap.WriterAgent, type: "stage", status: "running", title: q ? `第 ${q} 问开始写作` : "开始论文写作", detail: line, badges: q ? [`Q${q}`] : [] };
	if (/论文手完成/.test(line)) return { ...base, actor: "WriterAgent", role: roleMap.WriterAgent, type: "artifact", status: "done", title: q ? `第 ${q} 问写作完成` : "写作完成", detail: "已生成对应论文段落。", artifacts: artifactNames(content), badges: q ? [`Q${q}`] : [] };
	if (/子问题组#\d+.*启动/.test(line)) return { ...base, actor: "SubCoordinatorAgent", role: roleMap.SubCoordinatorAgent, type: "stage", status: "running", title: q ? `子问题组 ${q} 启动` : "子问题组启动", detail: line, badges: q ? [`Q${q}`] : [] };
	if (/子问题组#\d+.*完成/.test(line)) return { ...base, actor: "SubCoordinatorAgent", role: roleMap.SubCoordinatorAgent, type: "stage", status: "done", title: q ? `子问题组 ${q} 完成` : "子问题组完成", detail: "该组结果已提交汇总。", badges: q ? [`Q${q}`] : [] };
	if (/协调者后台错误判别已启动/.test(line)) return { ...base, actor: "CoderAgent", role: roleMap.CoderAgent, type: "progress", status: "warning", title: "多次改错，协调者后台判别中", detail: line, progressText: "Coder 继续自行修复，协调者后台判断是否需要换新 Coder。", badges: q ? [`Q${q}`, "后台判别"] : ["后台判别"] };
	if (/协调者后台错误判别完成|协调者重复错误判别/.test(line)) {
		const restart = content.includes("should_restart=true") || content.includes("切换新 Coder");
		return { ...base, actor: "CoderAgent", role: roleMap.CoderAgent, type: restart ? "warning" : "progress", status: restart ? "warning" : "running", title: restart ? "反复出错，准备换新 Coder" : "协调者给出改错建议", detail: brief(content, 260), badges: q ? [`Q${q}`, "改错"] : ["改错"] };
	}
	if (/已停止|任务执行失败|失败|错误/.test(line)) return { ...base, type: "error", status: "error", title: line.slice(0, 80), detail: brief(content, 240), badges: q ? [`Q${q}`] : [] };
	if (/完成终稿整体检查|论文生成完成/.test(line)) return { ...base, actor: "WriterAgent", role: roleMap.WriterAgent, type: "artifact", status: "done", title: "论文终稿完成", detail: "可以在右侧论文预览或导出菜单查看结果。", artifacts: artifactNames(content) };
	if (/开始终稿整体检查|集成协调者|并行写作启动|开始灵敏度分析|启动 EDA/.test(line)) return { ...base, type: "stage", status: "running", title: line.slice(0, 80), detail: brief(content, 220) };
	if (artifactNames(content).length) return { ...base, type: "artifact", status: "done", title: "生成产物", detail: brief(content, 180), artifacts: artifactNames(content) };
	return { ...base, type: "stage", status: msg.msg_type === "system" && (msg as any).type === "success" ? "done" : "running", title: line || "流程更新", detail: brief(content, 180) };
}

function agentEvent(msg: Message): TimelineEvent | null {
	const content = msg.content ?? "";
	if (!content.trim()) return null;
	const actor = actorFromMessage(msg, content);
	const q = detectQuestionIndex(content, msg);
	const isStreaming = (msg as any).stream_state === "streaming";
	return { id: msg.id, side: "left", actor, role: roleMap[actor] ?? "Agent", type: "raw", status: isStreaming ? "running" : "done", title: isStreaming ? "正在思考与生成" : "输出结果摘要", detail: brief(content, 260), brief: content.length > 400 ? brief(content, 180) : undefined, timeLabel: timeLabel(msg.created_at), questionIndex: q, badges: q ? [`Q${q}`] : [] };
}

function toolEvent(msg: ToolMessage): TimelineEvent | null {
	if (msg.tool_name !== "execute_code") return null;
	const code = String((msg.input as any)?.code ?? "");
	const output = Array.isArray(msg.output) ? msg.output : [];
	const hasError = output.some((o: any) => o?.res_type === "error");
	const desc = msg.description || "执行 Python 代码";
	if (!hasError) return null;
	return { id: msg.id, side: "left", actor: "CoderAgent", role: roleMap.CoderAgent, type: "progress", status: "warning", title: "代码执行出错，正在改错", detail: brief(desc || code, 180), timeLabel: timeLabel(msg.created_at), badges: ["改错"] };
}

function progressEvent(msg: ProgressMessage): TimelineEvent | null {
	if (!msg.description && msg.percentage == null) return null;
	return { id: msg.id, side: "center", actor: "SystemMonitor", role: roleMap.SystemMonitor, type: "progress", status: msg.percentage >= 100 ? "done" : "running", title: msg.description || "任务进度更新", progressText: `${msg.percentage ?? 0}%`, timeLabel: timeLabel(msg.created_at) };
}

function toEvent(msg: Message): TimelineEvent | null {
	if (msg.msg_type === "user") return { id: msg.id, side: "right", actor: "User", role: roleMap.User, type: "user", status: "done", title: brief(msg.content, 80) || "用户确认", detail: brief(msg.content, 220), timeLabel: timeLabel(msg.created_at) };
	if (msg.msg_type === "system") return systemEvent(msg);
	if (msg.msg_type === "agent") return agentEvent(msg);
	if (msg.msg_type === "tool") return toolEvent(msg as ToolMessage);
	if (msg.msg_type === "progress") return progressEvent(msg as ProgressMessage);
	return null;
}

const rawEvents = computed(() => props.messages.map(toEvent).filter(Boolean) as TimelineEvent[]);
const timelineEvents = computed(() => {
	const out: TimelineEvent[] = [];
	for (const ev of rawEvents.value) {
		const prev = out[out.length - 1];
		if (prev && prev.actor === ev.actor && prev.type === ev.type && prev.title === ev.title && ev.type !== "choice" && prev.side === ev.side) {
			out[out.length - 1] = { ...ev, badges: Array.from(new Set([...(prev.badges ?? []), ...(ev.badges ?? [])])) };
			continue;
		}
		out.push(ev);
	}
	return out;
});

const hasQuestionWait = computed(() => allMessageText.value.includes("等待用户确认问题划分"));
const hasModelingWait = computed(() => allMessageText.value.includes("等待用户确认各问建模方案"));
const hasSolvingStarted = computed(() => /代码手开始求解|子问题组#\d+.*启动|开始求解/.test(allMessageText.value));
const hasSolvingDone = computed(() => /代码手求解成功|子问题组#\d+.*完成/.test(allMessageText.value));
const hasWritingStarted = computed(() => /论文手开始写|并行写作启动|开始终稿整体检查/.test(allMessageText.value));
const hasWritingDone = computed(() => /论文手完成|论文生成完成|完成终稿整体检查/.test(allMessageText.value));
const hasFinalDone = computed(() => /论文生成完成|任务处理完成|完成终稿整体检查/.test(allMessageText.value) || props.taskStatus === "completed");
const hasFlowWarning = computed(() => /任务执行失败|已停止|should_restart=true|切换新 Coder|后台判别/.test(allMessageText.value));

const flowSteps = computed<FlowStep[]>(() => {
	const planningDone = hasQuestionWait.value || questionConfirmed.value || modelingConfirmed.value || hasSolvingStarted.value;
	return [
		{
			key: "planning",
			label: "规划",
			status: planningDone ? "done" : props.messages.length ? "active" : "pending",
			detail: planningDone ? "题目拆解完成" : "等待题目拆解",
		},
		{
			key: "question",
			label: "问题确认",
			status: questionConfirmed.value ? "done" : hasQuestionWait.value ? "active" : "pending",
			detail: questionConfirmed.value ? "已确认" : hasQuestionWait.value ? "等待用户确认" : "未开始",
		},
		{
			key: "modeling",
			label: "建模确认",
			status: modelingConfirmed.value ? "done" : hasModelingWait.value ? "active" : questionConfirmed.value ? "active" : "pending",
			detail: modelingConfirmed.value ? "已确认" : hasModelingWait.value ? "等待方案选择" : questionConfirmed.value ? "生成方案中" : "未开始",
		},
		{
			key: "solving",
			label: "代码求解",
			status: hasWritingStarted.value || hasWritingDone.value ? "done" : hasSolvingStarted.value ? (hasFlowWarning.value ? "warning" : "active") : "pending",
			detail: hasWritingStarted.value || hasWritingDone.value ? "已移交写作" : hasSolvingStarted.value ? "子问题求解中" : "未开始",
		},
		{
			key: "writing",
			label: "论文写作",
			status: hasWritingDone.value ? "done" : hasWritingStarted.value || hasSolvingDone.value ? "active" : "pending",
			detail: hasWritingDone.value ? "章节写作完成" : hasWritingStarted.value || hasSolvingDone.value ? "写作中" : "未开始",
		},
		{
			key: "final",
			label: "终稿",
			status: hasFinalDone.value ? "done" : hasWritingDone.value ? "active" : "pending",
			detail: hasFinalDone.value ? "终稿完成" : hasWritingDone.value ? "终稿整合中" : "未开始",
		},
	];
});

const questionStatuses = computed<QuestionStatus[]>(() => {
	const map = new Map<number, QuestionStatus>();
	function ensure(index: number) {
		if (!map.has(index)) {
			map.set(index, { index, label: `Q${index}`, status: "pending", detail: "等待" });
		}
		return map.get(index)!;
	}
	for (const msg of props.messages) {
		const text = messageText(msg);
		const q = detectQuestionIndex(text, msg as any);
		if (!q) continue;
		const item = ensure(q);
		if (/已停止|失败|错误|后台判别|should_restart=true|切换新 Coder/.test(text) && item.status !== "done") {
			item.status = "warning";
			item.detail = "需关注";
		}
		if (/代码手开始求解|子问题组#\d+.*启动/.test(text) && item.status !== "done") {
			item.status = item.status === "warning" ? "warning" : "solving";
			item.detail = item.status === "warning" ? "改错中" : "求解中";
		}
		if (/代码手求解成功|论文手开始写/.test(text) && item.status !== "done") {
			item.status = "writing";
			item.detail = "写作中";
		}
		if (/论文手完成|子问题组#\d+.*完成/.test(text)) {
			item.status = "done";
			item.detail = "完成";
		}
	}
	return Array.from(map.values()).sort((a, b) => a.index - b.index).slice(0, 8);
});

const currentStage = computed(() => [...timelineEvents.value].reverse().find((e) => e.status === "running" || e.status === "warning" || e.status === "waiting")?.title ?? (props.taskStatus === "completed" ? "任务已完成" : "等待开始"));
const progressSummary = computed(() => {
	const total = timelineEvents.value.length;
	const done = timelineEvents.value.filter((e) => e.status === "done").length;
	const warnings = timelineEvents.value.filter((e) => e.status === "warning" || e.status === "error").length;
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

function flowStepClass(status: FlowStep["status"]) {
	if (status === "done") return "border-blue-200 bg-blue-50 text-blue-700";
	if (status === "active") return "border-emerald-200 bg-emerald-50 text-emerald-700 shadow-[0_0_0_2px_rgba(16,185,129,0.08)]";
	if (status === "warning") return "border-amber-200 bg-amber-50 text-amber-700 shadow-[0_0_0_2px_rgba(245,158,11,0.08)]";
	return "border-slate-200 bg-slate-50 text-slate-400";
}

function questionStatusClass(status: QuestionStatus["status"]) {
	if (status === "done") return "border-blue-200 bg-blue-50 text-blue-700";
	if (status === "solving") return "border-emerald-200 bg-emerald-50 text-emerald-700";
	if (status === "writing") return "border-violet-200 bg-violet-50 text-violet-700";
	if (status === "warning") return "border-amber-200 bg-amber-50 text-amber-700";
	return "border-slate-200 bg-slate-50 text-slate-400";
}

function scrollToBottom(force = false) {
	const el = scrollRef.value;
	if (!el) return;
	if (!force && userScrolledUp.value) return;
	nextTick(() => el.scrollTo({ top: el.scrollHeight, behavior: "smooth" }));
}

function onScroll() {
	const el = scrollRef.value;
	if (!el) return;
	userScrolledUp.value = el.scrollHeight - el.scrollTop - el.clientHeight > 120;
}

watch(() => props.messages.length, () => scrollToBottom(), { flush: "post" });
</script>

<template>
	<div class="flex h-full min-h-0 flex-col bg-slate-50/70">
		<div class="border-b border-slate-200/80 bg-white/75 px-4 py-3 backdrop-blur">
			<div class="flex items-center justify-between gap-3">
				<div class="min-w-0">
					<div class="flex items-center gap-2"><MessageSquareText class="h-4 w-4 text-blue-600" /><span class="text-sm font-semibold text-slate-900">Agent 对话流</span></div>
					<p class="mt-1 truncate text-xs text-slate-500">当前：{{ currentStage }}</p>
				</div>
				<div class="shrink-0 rounded-full border border-slate-200 bg-white px-3 py-1 text-[11px] text-slate-600">{{ progressSummary.done }}/{{ progressSummary.total }} 已完成<span v-if="progressSummary.warnings" class="ml-1 text-amber-600">· {{ progressSummary.warnings }} 个需关注</span></div>
			</div>

			<div class="mt-3 rounded-2xl border border-slate-200 bg-white/80 p-2.5 shadow-sm">
				<div class="mb-2 flex items-center justify-between gap-2">
					<span class="text-[11px] font-semibold text-slate-600">当前流程</span>
					<span class="truncate text-[10px] text-slate-400">确认、求解、写作与终稿状态集中显示</span>
				</div>
				<div class="grid grid-cols-3 gap-1.5 xl:grid-cols-6">
					<div v-for="step in flowSteps" :key="step.key" class="rounded-xl border px-2 py-1.5" :class="flowStepClass(step.status)">
						<div class="flex items-center justify-between gap-1">
							<span class="text-[11px] font-bold">{{ step.label }}</span>
							<span class="text-[9px] opacity-70">{{ step.status === 'done' ? '完成' : step.status === 'active' ? '进行中' : step.status === 'warning' ? '需关注' : '等待' }}</span>
						</div>
						<div class="mt-0.5 truncate text-[10px] opacity-75">{{ step.detail }}</div>
					</div>
				</div>
				<div v-if="questionStatuses.length" class="mt-2 flex flex-wrap gap-1.5">
					<div v-for="q in questionStatuses" :key="q.index" class="rounded-full border px-2 py-1 text-[10px] font-semibold" :class="questionStatusClass(q.status)">
						{{ q.label }} · {{ q.detail }}
					</div>
				</div>
			</div>
		</div>

		<div ref="scrollRef" class="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-5" @scroll="onScroll">
			<div v-if="timelineEvents.length === 0" class="flex h-full items-center justify-center text-sm text-slate-400">任务消息会以对话流形式显示在这里。</div>

			<div v-for="ev in timelineEvents" :key="ev.id" class="flex" :class="{ 'justify-end': ev.side === 'right', 'justify-center': ev.side === 'center', 'justify-start': ev.side === 'left' }">
				<div v-if="ev.side === 'center'" class="max-w-[90%] rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-500 shadow-sm">{{ ev.title }} <span v-if="ev.progressText" class="ml-1 font-mono text-blue-600">{{ ev.progressText }}</span></div>

				<div v-else class="flex max-w-[96%] gap-2" :class="{ 'flex-row-reverse': ev.side === 'right' }">
					<div class="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full shadow-sm" :class="{ 'bg-blue-600 text-white': ev.side === 'left' && ev.status !== 'warning' && ev.status !== 'error', 'bg-amber-500 text-white': ev.status === 'warning', 'bg-red-500 text-white': ev.status === 'error', 'bg-slate-900 text-white': ev.side === 'right' }"><component :is="actorIcon(ev.actor)" class="h-4 w-4" /></div>

					<div class="min-w-0 rounded-2xl border px-3.5 py-3 shadow-sm" :class="{ 'rounded-tl-md border-slate-200 bg-white text-slate-800': ev.side === 'left' && ev.status !== 'warning' && ev.status !== 'error', 'rounded-tr-md border-slate-800 bg-slate-900 text-white': ev.side === 'right', 'rounded-tl-md border-amber-200 bg-amber-50 text-amber-950': ev.status === 'warning', 'rounded-tl-md border-red-200 bg-red-50 text-red-950': ev.status === 'error' }">
						<div class="flex items-start justify-between gap-3">
							<div class="min-w-0">
								<div class="flex flex-wrap items-center gap-1.5"><span class="text-[11px] font-semibold opacity-70">{{ ev.actor }}</span><span class="text-[10px] opacity-45">{{ ev.role }}</span><span v-for="badge in ev.badges" :key="badge" class="rounded-full border px-1.5 py-0.5 text-[10px] opacity-80">{{ badge }}</span></div>
								<div class="mt-1 flex items-center gap-1.5 text-sm font-semibold"><component :is="statusIcon(ev)" class="h-3.5 w-3.5" :class="{ 'animate-spin': ev.status === 'running' }" /><span>{{ ev.title }}</span></div>
							</div>
							<span class="shrink-0 text-[10px] opacity-45">{{ ev.timeLabel }}</span>
						</div>

						<p v-if="ev.detail" class="mt-2 whitespace-pre-wrap text-xs leading-relaxed opacity-80">{{ ev.detail }}</p>
						<p v-if="ev.progressText" class="mt-2 rounded-xl border border-current/10 bg-white/45 px-2.5 py-1.5 text-xs opacity-90">{{ ev.progressText }}</p>

						<div v-if="ev.type === 'choice'" class="agent-conversation-inline-panel mt-3 rounded-xl border border-current/10 bg-white/65 p-2 text-xs text-slate-800">
							<QuestionDiscussion
								v-if="ev.choiceKind === 'question' && props.taskId"
								:task_id="props.taskId"
								:expanded="inlineQuestionPanelOpen && !questionConfirmed"
								:locked="questionConfirmed"
								:disabled="questionConfirmed"
								@toggle="inlineQuestionPanelOpen = !inlineQuestionPanelOpen"
								@confirm="handleInlineQuestionConfirm"
							/>
							<ModelingDiscussion
								v-else-if="ev.choiceKind === 'modeling'"
								:expanded="inlineModelingPanelOpen && !modelingConfirmed"
								:locked="modelingConfirmed"
								:disabled="modelingConfirmed"
								@toggle="inlineModelingPanelOpen = !inlineModelingPanelOpen"
								@confirm="handleInlineModelingConfirm"
							/>
						</div>

						<div v-if="ev.artifacts?.length" class="mt-3 grid gap-1.5">
							<div v-for="file in ev.artifacts" :key="file" class="flex items-center gap-2 rounded-xl border border-current/10 bg-white/55 px-2.5 py-1.5 text-xs"><FileText class="h-3.5 w-3.5 opacity-70" /><span class="truncate">{{ file }}</span></div>
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
}
</style>
