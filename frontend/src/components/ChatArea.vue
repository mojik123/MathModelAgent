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
			status: "waiting",
			actor: "CoordinatorAgent",
			role: roleMap.CoordinatorAgent,
			title: "问题划分已生成，请确认",
			detail: "可在这条对话消息内直接修改、增删问题卡片，确认后继续进入建模方案选择。",
			choiceKind: "question",
			badges: ["需要用户确认"],
		};
	}
	if (line.includes("问题划分已确认") || line.includes("已复用问题划分")) {
		return { ...base, side: "right", actor: "User", role: roleMap.User, type: "user", status: "done", title: "已确认问题划分", detail: "进入建模方案生成阶段。" };
	}
	if (line.includes("等待用户确认各问建模方案")) {
		return {
			...base,
			type: "choice",
			status: "waiting",
			actor: "ModelerAgent",
			role: roleMap.ModelerAgent,
			title: "候选建模方案已生成，请选择",
			detail: "可在这条对话消息内直接选择每一问的建模方案，也可以要求重新生成。",
			choiceKind: "modeling",
			badges: ["需要用户确认"],
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

const currentStage = computed(() => [...timelineEvents.value].reverse().find((e) => e.status === "running" || e.status === "warning")?.title ?? (props.taskStatus === "completed" ? "任务已完成" : "等待开始"));
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
							<QuestionDiscussion v-if="ev.choiceKind === 'question' && props.taskId" :task_id="props.taskId" :expanded="inlineQuestionPanelOpen" :locked="false" :disabled="false" @toggle="inlineQuestionPanelOpen = !inlineQuestionPanelOpen" />
							<ModelingDiscussion v-else-if="ev.choiceKind === 'modeling'" :expanded="inlineModelingPanelOpen" :locked="false" :disabled="false" @toggle="inlineModelingPanelOpen = !inlineModelingPanelOpen" />
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
/* 旧版底部固定确认面板在对话流重构后不再显示；嵌入气泡内的面板不受影响。 */
.glass-left-panel > .question-discussion,
.glass-left-panel > .modeling-discussion {
	display: none !important;
}

.agent-conversation-inline-panel .question-discussion,
.agent-conversation-inline-panel .modeling-discussion {
	display: flex !important;
	max-height: none !important;
	border-radius: 0.75rem;
	border: 1px solid rgba(226, 232, 240, 0.8);
}
</style>
