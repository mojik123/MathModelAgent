<script setup lang="ts">
import type { TaskRuntimeStatus } from "@/apis/commonApi";
import ModelingDiscussion from "@/components/ModelingDiscussion.vue";
import QuestionDiscussion from "@/components/QuestionDiscussion.vue";
import { AgentType } from "@/utils/enum";
import type {
	InterpreterMessage,
	Message,
	ProgressMessage,
	ToolMessage,
} from "@/utils/response";
import { ChevronRight, Terminal } from "lucide-vue-next";
import { computed, nextTick, ref, watch } from "vue";

// ---- Props ----

const props = withDefaults(
	defineProps<{
		messages: Message[];
		taskStatus?: TaskRuntimeStatus;
		taskId?: string;
	}>(),
	{ taskStatus: "ready" },
);

const emit = defineEmits<{
	questionConfirm: [];
	modelingConfirm: [];
}>();

// ---- Types ----

interface SimpleChatItem {
	id: string;
	kind: "status" | "agent" | "tool" | "progress" | "choice" | "user" | "error";
	actor: string;
	content: string;
	timestamp: string;
	isStreaming: boolean;
	isError: boolean;
	choiceKind?: "question" | "modeling";
	codeInput?: string;
	codeOutput?: string;
}

// ---- State ----

const scrollRef = ref<HTMLDivElement | null>(null);
const userScrolledUp = ref(false);
const collapsedTools = ref(new Set<string>());
const questionPanelOpen = ref(true);
const modelingPanelOpen = ref(true);

// ---- Helpers ----

const actorNames: Record<string, string> = {
	CoordinatorAgent: "Coordinator",
	SubCoordinatorAgent: "SubCoordinator",
	ModelerAgent: "Modeler",
	CoderAgent: "Coder",
	WriterAgent: "Writer",
	SystemMonitor: "System",
	User: "You",
};

const actorColors: Record<string, string> = {
	CoordinatorAgent: "text-violet-600",
	SubCoordinatorAgent: "text-violet-500",
	ModelerAgent: "text-amber-600",
	CoderAgent: "text-emerald-600",
	WriterAgent: "text-blue-600",
	SystemMonitor: "text-gray-400",
	User: "text-gray-800",
};

function timeLabel(input?: string | null) {
	if (!input) return "";
	const d = new Date(input);
	if (Number.isNaN(d.getTime())) return "";
	return d.toLocaleTimeString([], {
		hour: "2-digit",
		minute: "2-digit",
		second: "2-digit",
	});
}

function getActor(msg: Message): string {
	if (msg.msg_type === "user") return "User";
	if (msg.msg_type === "progress") return "SystemMonitor";
	if (msg.msg_type === "agent") {
		const agentMsg = msg as { agent_type?: string };
		switch (agentMsg.agent_type) {
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
	return "SystemMonitor";
}

const lowValuePatterns = [
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
	"消息已发布",
	"保存",
	"传递：工作指令",
	"代码手自行反思纠错",
	"代码手根据协调者建议反思纠错",
	"协调者后台判别不阻塞当前尝试",
];

function isLowValue(text: string) {
	return lowValuePatterns.some((p) => text.includes(p));
}

function formatCodeOutput(output: InterpreterMessage["output"]): string {
	if (!output || !Array.isArray(output)) return "";
	const lines: string[] = [];
	for (const item of output) {
		if (!item) continue;
		const o = item as {
			res_type: string;
			msg?: string;
			name?: string;
			value?: string;
			traceback?: string;
		};
		if (o.res_type === "stdout" && o.msg) lines.push(o.msg);
		if (o.res_type === "stderr" && o.msg) lines.push(`[stderr] ${o.msg}`);
		if (o.res_type === "result" && o.msg) lines.push(o.msg);
		if (o.res_type === "error") {
			lines.push(`[Error] ${o.name ?? "Error"}: ${o.value ?? ""}`);
			if (o.traceback) lines.push(o.traceback);
		}
	}
	return lines.join("\n").trim();
}

function truncate(text: string, max: number) {
	if (text.length <= max) return text;
	return `${text.slice(0, max)}...`;
}

// ---- Computed ----

const questionConfirmed = computed(() =>
	props.messages.some((m) => {
		const c = m.content ?? "";
		return c.includes("问题划分已确认") || c.includes("已复用问题划分");
	}),
);

const modelingConfirmed = computed(() =>
	props.messages.some((m) => {
		const c = m.content ?? "";
		return c.includes("建模方案已确认") || c.includes("已复用建模方案选择");
	}),
);

const hasQuestionWait = computed(() =>
	props.messages.some((m) =>
		(m.content ?? "").includes("等待用户确认问题划分"),
	),
);

const hasModelingWait = computed(() =>
	props.messages.some((m) =>
		(m.content ?? "").includes("等待用户确认各问建模方案"),
	),
);

const displayItems = computed<SimpleChatItem[]>(() => {
	const items: SimpleChatItem[] = [];

	for (const msg of props.messages) {
		const content = msg.content ?? "";
		const ts = timeLabel(msg.created_at);

		// Choice events
		if (msg.msg_type === "system" && content.includes("等待用户确认问题划分")) {
			items.push({
				id: msg.id,
				kind: "choice",
				actor: "CoordinatorAgent",
				content: questionConfirmed.value
					? "问题划分已确认"
					: "请确认问题划分方案",
				timestamp: ts,
				isStreaming: false,
				isError: false,
				choiceKind: "question",
			});
			continue;
		}
		if (
			msg.msg_type === "system" &&
			content.includes("等待用户确认各问建模方案")
		) {
			items.push({
				id: msg.id,
				kind: "choice",
				actor: "ModelerAgent",
				content: modelingConfirmed.value
					? "建模方案已确认"
					: "请选择各问建模方案",
				timestamp: ts,
				isStreaming: false,
				isError: false,
				choiceKind: "modeling",
			});
			continue;
		}

		// System messages
		if (msg.msg_type === "system") {
			if (isLowValue(content)) continue;
			if (!content.trim()) continue;
			const sysType = (msg as { type?: string }).type;
			items.push({
				id: msg.id,
				kind: sysType === "error" ? "error" : "status",
				actor: "SystemMonitor",
				content: content.split("\n")[0]?.trim() ?? content,
				timestamp: ts,
				isStreaming: false,
				isError: sysType === "error",
			});
			continue;
		}

		// User messages
		if (msg.msg_type === "user") {
			if (!content.trim()) continue;
			items.push({
				id: msg.id,
				kind: "user",
				actor: "User",
				content,
				timestamp: ts,
				isStreaming: false,
				isError: false,
			});
			continue;
		}

		// Agent messages
		if (msg.msg_type === "agent") {
			if (!content.trim()) continue;
			const streaming =
				(msg as { stream_state?: string }).stream_state === "streaming";
			items.push({
				id: msg.id,
				kind: "agent",
				actor: getActor(msg),
				content,
				timestamp: ts,
				isStreaming: streaming,
				isError: false,
			});
			continue;
		}

		// Tool messages (execute_code)
		if (msg.msg_type === "tool") {
			const toolMsg = msg as InterpreterMessage;
			if (toolMsg.tool_name !== "execute_code") continue;
			const codeInput = (toolMsg.input as { code?: string })?.code ?? "";
			const codeOutput = formatCodeOutput(toolMsg.output);
			const hasError = (toolMsg.output ?? []).some(
				(o: { res_type: string }) => o?.res_type === "error",
			);
			items.push({
				id: msg.id,
				kind: "tool",
				actor: "CoderAgent",
				content: toolMsg.description || "执行 Python 代码",
				timestamp: ts,
				isStreaming: false,
				isError: hasError,
				codeInput,
				codeOutput,
			});
			continue;
		}

		// Progress messages
		if (msg.msg_type === "progress") {
			const prog = msg as ProgressMessage;
			if (!prog.description && prog.percentage == null) continue;
			items.push({
				id: msg.id,
				kind: "progress",
				actor: "SystemMonitor",
				content: prog.description || "进度更新",
				timestamp: ts,
				isStreaming: false,
				isError: false,
			});
		}
	}

	return items;
});

// ---- Tool collapse ----

function toggleToolCollapse(id: string) {
	if (collapsedTools.value.has(id)) {
		collapsedTools.value.delete(id);
	} else {
		collapsedTools.value.add(id);
	}
}

function isToolCollapsed(id: string) {
	return !collapsedTools.value.has(id);
}

// ---- Scroll ----

function onScroll() {
	const el = scrollRef.value;
	if (!el) return;
	const gap = el.scrollHeight - el.scrollTop - el.clientHeight;
	userScrolledUp.value = gap > 80;
}

function scrollToBottom() {
	const el = scrollRef.value;
	if (el) el.scrollTop = el.scrollHeight;
}

watch(
	() => displayItems.value.length,
	() => {
		if (!userScrolledUp.value) {
			nextTick(scrollToBottom);
		}
	},
);

watch(
	() => {
		const streaming = displayItems.value.filter((i) => i.isStreaming);
		return streaming.map((i) => `${i.id}:${i.content.length}`).join("|");
	},
	() => {
		if (!userScrolledUp.value) {
			nextTick(scrollToBottom);
		}
	},
);

// ---- HIL ----

function handleQuestionConfirm() {
	questionPanelOpen.value = false;
	emit("questionConfirm");
}

function handleModelingConfirm() {
	modelingPanelOpen.value = false;
	emit("modelingConfirm");
}
</script>

<template>
	<div class="flex h-full min-h-0 flex-col bg-gray-50">
		<!-- Header -->
		<div class="flex items-center gap-2 border-b border-gray-200 bg-white px-4 py-2">
			<Terminal class="h-4 w-4 text-gray-500" />
			<span class="text-sm font-medium text-gray-700">Agent Log</span>
			<span class="ml-auto text-xs text-gray-400">{{ displayItems.length }} messages</span>
		</div>

		<!-- Messages -->
		<div
			ref="scrollRef"
			class="min-h-0 flex-1 overflow-y-auto font-mono text-[13px] leading-relaxed"
			@scroll="onScroll"
		>
			<div v-if="displayItems.length === 0" class="flex h-full items-center justify-center text-sm text-gray-400">
				等待任务消息...
			</div>

			<div class="space-y-0">
				<template v-for="item in displayItems" :key="item.id">
					<!-- Status (system message) -->
					<div v-if="item.kind === 'status'" class="px-4 py-1">
						<span class="text-gray-400">{{ item.timestamp }}</span>
						<span class="ml-2 text-gray-500">{{ item.content }}</span>
					</div>

					<!-- Error -->
					<div v-else-if="item.kind === 'error'" class="border-l-2 border-red-400 bg-red-50 px-4 py-1.5">
						<span class="text-gray-400">{{ item.timestamp }}</span>
						<span class="ml-2 font-semibold text-red-600">ERROR</span>
						<span class="ml-2 text-red-700">{{ item.content }}</span>
					</div>

					<!-- Progress -->
					<div v-else-if="item.kind === 'progress'" class="px-4 py-1">
						<span class="text-gray-400">{{ item.timestamp }}</span>
						<span class="ml-2 text-blue-500">[progress]</span>
						<span class="ml-1 text-gray-600">{{ item.content }}</span>
					</div>

					<!-- User -->
					<div v-else-if="item.kind === 'user'" class="border-l-2 border-gray-700 bg-gray-100 px-4 py-2">
						<div class="flex items-center gap-2">
							<span class="text-gray-400">{{ item.timestamp }}</span>
							<span class="font-semibold text-gray-800">You</span>
						</div>
						<div class="mt-1 whitespace-pre-wrap pl-[70px] text-gray-700">{{ item.content }}</div>
					</div>

					<!-- Agent -->
					<div v-else-if="item.kind === 'agent'" class="px-4 py-2" :class="item.isStreaming ? 'bg-blue-50/50' : ''">
						<div class="flex items-center gap-2">
							<span class="text-gray-400">{{ item.timestamp }}</span>
							<span class="font-semibold" :class="actorColors[item.actor] ?? 'text-gray-600'">
								{{ actorNames[item.actor] ?? item.actor }}
							</span>
							<span v-if="item.isStreaming" class="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" />
						</div>
						<div
							class="mt-1 whitespace-pre-wrap pl-[70px] text-gray-700"
							:class="item.isStreaming ? 'streaming-text' : ''"
						>{{ item.content }}<span v-if="item.isStreaming" class="animate-blink text-blue-500">▌</span></div>
					</div>

					<!-- Tool (execute_code) -->
					<div v-else-if="item.kind === 'tool'" class="px-4 py-1.5">
						<div class="flex items-center gap-2">
							<span class="text-gray-400">{{ item.timestamp }}</span>
							<button
								class="flex items-center gap-1 text-emerald-600 hover:text-emerald-700"
								@click="toggleToolCollapse(item.id)"
							>
								<ChevronRight
									class="h-3 w-3 transition-transform"
									:class="isToolCollapsed(item.id) ? '' : 'rotate-90'"
								/>
								<span class="font-semibold">execute_code</span>
							</button>
							<span class="text-gray-500">{{ truncate(item.content, 60) }}</span>
							<span v-if="item.isError" class="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold text-red-600">ERROR</span>
						</div>
						<div v-if="!isToolCollapsed(item.id)" class="ml-[70px] mt-1 space-y-1">
							<div v-if="item.codeInput" class="overflow-x-auto rounded border border-gray-200 bg-gray-900 p-2">
								<pre class="text-xs text-gray-100">{{ item.codeInput }}</pre>
							</div>
							<div v-if="item.codeOutput" class="overflow-x-auto rounded border p-2" :class="item.isError ? 'border-red-200 bg-red-50' : 'border-gray-200 bg-white'">
								<pre class="text-xs" :class="item.isError ? 'text-red-700' : 'text-gray-600'">{{ truncate(item.codeOutput, 2000) }}</pre>
							</div>
						</div>
					</div>

					<!-- Choice (HIL) -->
					<div v-else-if="item.kind === 'choice'" class="mx-4 my-2">
						<div class="rounded-lg border border-amber-200 bg-amber-50 p-3">
							<div class="flex items-center gap-2">
								<span class="text-gray-400">{{ item.timestamp }}</span>
								<span class="font-semibold text-amber-700">
									{{ item.choiceKind === "question" ? "问题划分确认" : "建模方案选择" }}
								</span>
								<span
									class="rounded-full px-2 py-0.5 text-[10px] font-semibold"
									:class="(item.choiceKind === 'question' ? questionConfirmed : modelingConfirmed)
										? 'bg-green-100 text-green-700'
										: 'bg-amber-100 text-amber-700'"
								>
									{{ (item.choiceKind === 'question' ? questionConfirmed : modelingConfirmed) ? '已确认' : '待确认' }}
								</span>
							</div>

							<!-- Question Discussion Panel -->
							<div v-if="item.choiceKind === 'question' && !questionConfirmed && questionPanelOpen && props.taskId" class="mt-2">
								<QuestionDiscussion
									:task_id="props.taskId"
									:expanded="true"
									:locked="false"
									@confirm="handleQuestionConfirm"
									@toggle="questionPanelOpen = !questionPanelOpen"
								/>
							</div>

							<!-- Modeling Discussion Panel -->
							<div v-if="item.choiceKind === 'modeling' && !modelingConfirmed && modelingPanelOpen" class="mt-2">
								<ModelingDiscussion
									:expanded="true"
									:locked="false"
									@confirm="handleModelingConfirm"
									@toggle="modelingPanelOpen = !modelingPanelOpen"
								/>
							</div>
						</div>
					</div>
				</template>
			</div>

			<!-- Scroll to bottom button -->
			<div v-if="userScrolledUp" class="sticky bottom-2 flex justify-center">
				<button
					class="rounded-full border border-gray-300 bg-white px-3 py-1 text-xs text-gray-600 shadow-sm hover:bg-gray-50"
					@click="scrollToBottom"
				>
					↓ 回到底部
				</button>
			</div>
		</div>
	</div>
</template>

<style scoped>
@keyframes blink {
	0%, 50% { opacity: 1; }
	51%, 100% { opacity: 0; }
}
.animate-blink {
	animation: blink 1s step-end infinite;
}
</style>
