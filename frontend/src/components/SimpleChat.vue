<script setup lang="ts">
import type { TaskRuntimeStatus } from "@/apis/commonApi";
import ModelingDiscussion from "@/components/ModelingDiscussion.vue";
import QuestionDiscussion from "@/components/QuestionDiscussion.vue";
import type {
	InterpreterMessage,
	Message,
	ProgressMessage,
} from "@/utils/response";
import { ChevronRight } from "lucide-vue-next";
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

interface StepItem {
	id: string;
	kind: "step" | "action" | "choice" | "error";
	content: string;
	verb?: string;
	isStreaming: boolean;
	isError: boolean;
	choiceKind?: "question" | "modeling";
	codeInput?: string;
	codeOutput?: string;
}

// ---- State ----

const scrollRef = ref<HTMLDivElement | null>(null);
const userScrolledUp = ref(false);
const expandedActions = ref(new Set<string>());
const questionPanelOpen = ref(true);
const modelingPanelOpen = ref(true);

// ---- Helpers ----

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

const displayItems = computed<StepItem[]>(() => {
	const items: StepItem[] = [];

	for (const msg of props.messages) {
		const content = msg.content ?? "";

		// Choice events
		if (msg.msg_type === "system" && content.includes("等待用户确认问题划分")) {
			items.push({
				id: msg.id,
				kind: "choice",
				content: questionConfirmed.value
					? "问题划分已确认"
					: "请确认问题划分方案",
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
				content: modelingConfirmed.value
					? "建模方案已确认"
					: "请选择各问建模方案",
				isStreaming: false,
				isError: false,
				choiceKind: "modeling",
			});
			continue;
		}

		// System / progress → step
		if (msg.msg_type === "system" || msg.msg_type === "progress") {
			if (msg.msg_type === "system" && isLowValue(content)) continue;
			const text =
				msg.msg_type === "progress"
					? (msg as ProgressMessage).description || ""
					: content;
			if (!text.trim()) continue;
			const sysType = (msg as { type?: string }).type;
			items.push({
				id: msg.id,
				kind: sysType === "error" ? "error" : "step",
				content: text.split("\n")[0]?.trim() ?? text,
				isStreaming: false,
				isError: sysType === "error",
			});
			continue;
		}

		// User → step (highlight)
		if (msg.msg_type === "user") {
			if (!content.trim()) continue;
			items.push({
				id: msg.id,
				kind: "step",
				content,
				isStreaming: false,
				isError: false,
			});
			continue;
		}

		// Agent → step (just text, no identity)
		if (msg.msg_type === "agent") {
			if (!content.trim()) continue;
			const streaming =
				(msg as { stream_state?: string }).stream_state === "streaming";
			items.push({
				id: msg.id,
				kind: "step",
				content,
				isStreaming: streaming,
				isError: false,
			});
			continue;
		}

		// Tool → action (collapsible, verb-labeled)
		if (msg.msg_type === "tool") {
			const toolMsg = msg as InterpreterMessage;
			if (toolMsg.tool_name === "execute_code") {
				const codeInput = (toolMsg.input as { code?: string })?.code ?? "";
				const codeOutput = formatCodeOutput(toolMsg.output);
				const hasError = (toolMsg.output ?? []).some(
					(o: { res_type: string }) => o?.res_type === "error",
				);
				items.push({
					id: msg.id,
					kind: "action",
					verb: "Ran",
					content: toolMsg.description || "Python code",
					isStreaming: false,
					isError: hasError,
					codeInput,
					codeOutput,
				});
			} else if (toolMsg.tool_name === "search_papers") {
				const query = (toolMsg.input as { query?: string })?.query ?? "";
				const output = formatCodeOutput(toolMsg.output);
				items.push({
					id: msg.id,
					kind: "action",
					verb: "Searched",
					content: query || "学术文献",
					isStreaming: false,
					isError: false,
					codeOutput: output,
				});
			} else if (toolMsg.tool_name !== "task_complete") {
				items.push({
					id: msg.id,
					kind: "action",
					verb: "Used",
					content: toolMsg.tool_name || toolMsg.description || "tool",
					isStreaming: false,
					isError: false,
					codeOutput: formatCodeOutput(toolMsg.output),
				});
			}
		}
	}

	return items;
});

// ---- Action expand/collapse ----

function toggleAction(id: string) {
	if (expandedActions.value.has(id)) {
		expandedActions.value.delete(id);
	} else {
		expandedActions.value.add(id);
	}
}

function isExpanded(id: string) {
	return expandedActions.value.has(id);
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
		if (!userScrolledUp.value) nextTick(scrollToBottom);
	},
);

watch(
	() => {
		const streaming = displayItems.value.filter((i) => i.isStreaming);
		return streaming.map((i) => `${i.id}:${i.content.length}`).join("|");
	},
	() => {
		if (!userScrolledUp.value) nextTick(scrollToBottom);
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
	<div
		ref="scrollRef"
		class="h-full min-h-0 overflow-y-auto bg-gray-50 px-4 py-3 text-sm leading-relaxed"
		@scroll="onScroll"
	>
		<div
			v-if="displayItems.length === 0"
			class="flex h-full items-center justify-center text-gray-400"
		>
			等待任务消息...
		</div>

		<div class="space-y-1">
			<template v-for="item in displayItems" :key="item.id">
				<!-- Step (plain text) -->
				<div
					v-if="item.kind === 'step'"
					class="py-0.5 text-gray-600"
					:class="item.isStreaming ? 'text-gray-800' : ''"
				>
					<span class="whitespace-pre-wrap">{{ item.content }}</span>
					<span
						v-if="item.isStreaming"
						class="animate-blink text-blue-500"
						>▌</span
					>
				</div>

				<!-- Error -->
				<div
					v-else-if="item.kind === 'error'"
					class="rounded border-l-2 border-red-400 bg-red-50 px-3 py-1.5 text-red-700"
				>
					{{ item.content }}
				</div>

				<!-- Action (collapsible code) -->
				<div v-else-if="item.kind === 'action'" class="py-0.5">
					<button
						class="flex items-center gap-1.5 text-gray-500 hover:text-gray-700"
						@click="toggleAction(item.id)"
					>
						<ChevronRight
							class="h-3.5 w-3.5 shrink-0 transition-transform"
							:class="isExpanded(item.id) ? 'rotate-90' : ''"
						/>
						<span class="font-semibold">{{ item.verb || "Ran" }}</span>
						<span>{{ item.content }}</span>
						<span
							v-if="item.isError"
							class="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-600"
							>失败</span
						>
					</button>
					<div v-if="isExpanded(item.id)" class="mt-1 ml-5 space-y-1">
						<div
							v-if="item.codeInput"
							class="overflow-x-auto rounded bg-gray-900 p-2"
						>
							<pre class="text-xs text-gray-100">{{
								item.codeInput
							}}</pre>
						</div>
						<div
							v-if="item.codeOutput"
							class="overflow-x-auto rounded border p-2"
							:class="
								item.isError
									? 'border-red-200 bg-red-50'
									: 'border-gray-200 bg-white'
							"
						>
							<pre
								class="text-xs"
								:class="
									item.isError
										? 'text-red-700'
										: 'text-gray-600'
								"
								>{{ truncate(item.codeOutput, 2000) }}</pre
							>
						</div>
					</div>
				</div>

				<!-- Choice (HIL) -->
				<div v-else-if="item.kind === 'choice'" class="my-2">
					<div
						class="rounded-lg border border-amber-200 bg-amber-50 p-3"
					>
						<div class="flex items-center gap-2 text-sm">
							<span class="font-medium text-amber-700">
								{{
									item.choiceKind === "question"
										? "问题划分确认"
										: "建模方案选择"
								}}
							</span>
							<span
								class="rounded-full px-2 py-0.5 text-[10px] font-medium"
								:class="
									(
										item.choiceKind === 'question'
											? questionConfirmed
											: modelingConfirmed
									)
										? 'bg-green-100 text-green-700'
										: 'bg-amber-100 text-amber-700'
								"
							>
								{{
									(
										item.choiceKind === "question"
											? questionConfirmed
											: modelingConfirmed
									)
										? "已确认"
										: "待确认"
								}}
							</span>
						</div>

						<div
							v-if="
								item.choiceKind === 'question' &&
								!questionConfirmed &&
								questionPanelOpen &&
								props.taskId
							"
							class="mt-2"
						>
							<QuestionDiscussion
								:task_id="props.taskId"
								:expanded="true"
								:locked="false"
								@confirm="handleQuestionConfirm"
								@toggle="questionPanelOpen = !questionPanelOpen"
							/>
						</div>

						<div
							v-if="
								item.choiceKind === 'modeling' &&
								!modelingConfirmed &&
								modelingPanelOpen
							"
							class="mt-2"
						>
							<ModelingDiscussion
								:expanded="true"
								:locked="false"
								@confirm="handleModelingConfirm"
								@toggle="
									modelingPanelOpen = !modelingPanelOpen
								"
							/>
						</div>
					</div>
				</div>
			</template>
		</div>

		<!-- Scroll to bottom -->
		<div v-if="userScrolledUp" class="sticky bottom-2 flex justify-center">
			<button
				class="rounded-full border border-gray-300 bg-white px-3 py-1 text-xs text-gray-600 shadow-sm hover:bg-gray-50"
				@click="scrollToBottom"
			>
				↓ 回到底部
			</button>
		</div>
	</div>
</template>

<style scoped>
@keyframes blink {
	0%,
	50% {
		opacity: 1;
	}
	51%,
	100% {
		opacity: 0;
	}
}
.animate-blink {
	animation: blink 1s step-end infinite;
}
</style>
