<script setup lang="ts">
import { confirmQuestions, getOriginalProblem, questionDiscussionChat, regenerateQuestions } from "@/apis/commonApi";
import { useTaskStore } from "@/stores/task";
import { Lightbulb, LoaderCircle, RefreshCw, Send, Sparkles } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import QuestionCardStack from "./QuestionCardStack.vue";

// ---- Types ----

interface QuestionCardItem {
	questionIndex: number;
	questionTitle: string;
	questionText: string;
	chatHistory: Array<{ role: "user" | "assistant"; content: string }>;
}

// ---- Props ----

const props = defineProps<{
	task_id: string;
	expanded: boolean;
	locked?: boolean;
	disabled?: boolean;
}>();

const emit = defineEmits<{
	toggle: [];
	confirm: [];
}>();

// ---- Store ----

const taskStore = useTaskStore();

// ---- State ----

const questions = ref<QuestionCardItem[]>([]);
const confirming = ref(false);
const confirmError = ref("");
const loadingProblem = ref(false);
const chatting = ref(false);
const chatInput = ref("");

// ---- Computed ----

const coordinatorData = computed(() => {
	const msgs = taskStore.coordinatorMessages.filter(
		(m: { stream_state?: string }) => m.stream_state !== "streaming",
	);
	if (msgs.length === 0) return null;
	const lastMsg = msgs[msgs.length - 1];
	try {
		const content = lastMsg.content ?? "";
		const clean = content.replace(/```json\s*|```/g, "").trim();
		return JSON.parse(clean) as Record<string, unknown>;
	} catch {
		return null;
	}
});

const questionsList = computed(() => {
	const data = coordinatorData.value;
	if (!data) return [];
	const count = (data.ques_count as number) || 0;
	const list: Array<{ index: number; text: string }> = [];
	for (let i = 1; i <= count; i++) {
		const text = (data[`ques${i}`] as string) || `第 ${i} 问`;
		list.push({ index: i, text });
	}
	return list;
});

// ---- Methods ----

function buildQuestionCards(): QuestionCardItem[] {
	return questionsList.value.map((q) => ({
		questionIndex: q.index,
		questionTitle: `第 ${q.index} 问`,
		questionText: q.text,
		chatHistory: [],
	}));
}

function handleUpdateQuestions(updated: QuestionCardItem[]) {
	questions.value = updated;
	taskStore.questionCards = [...updated];
}

async function loadOriginalProblem() {
	if (taskStore.originalProblemText) return;
	loadingProblem.value = true;
	try {
		const res = await getOriginalProblem(props.task_id);
		if (res.data?.ques_all) {
			taskStore.originalProblemText = res.data.ques_all;
		}
	} catch {
		// 静默失败，不影响主流程
	} finally {
		loadingProblem.value = false;
	}
}

async function handleConfirm() {
	if (confirming.value || props.disabled) return;
	confirming.value = true;
	confirmError.value = "";
	try {
		taskStore.addUserAction(
			"确认",
			"问题划分",
			"用户确认了最终的问题划分方案",
			{ from: "User", to: "CoordinatorAgent", label: "确认问题划分" },
		);
		await confirmQuestions(props.task_id, questions.value);
		emit("confirm");
	} catch (e: unknown) {
		confirmError.value =
			(e as { response?: { data?: { detail?: string } } })?.response?.data
				?.detail || "确认失败，请重试";
	} finally {
		confirming.value = false;
	}
}

async function handleSendMessage(message: string) {
	if (chatting.value || props.disabled) return;
	chatting.value = true;

	// 先添加用户消息到对话历史
	taskStore.addUserAction(
		"讨论",
		"问题划分",
		`用户对问题划分提出意见：${message}`,
		{ from: "User", to: "CoordinatorAgent", label: "讨论问题划分" },
	);

	try {
		// 先尝试重新生成
		const regenRes = await regenerateQuestions(props.task_id, {
			message,
			questions: questions.value.map((q) => ({
				questionIndex: q.questionIndex,
				questionTitle: q.questionTitle,
				questionText: q.questionText,
				chatHistory: q.chatHistory,
			})),
			original_problem: taskStore.originalProblemText,
		});

		if (regenRes.data?.questions?.length) {
			questions.value = regenRes.data.questions.map((q) => ({
				questionIndex: q.questionIndex,
				questionTitle: q.questionTitle,
				questionText: q.questionText,
				chatHistory: [],
			}));
			taskStore.questionCards = [...questions.value];
		}

		// 同时获取对话回复
		try {
			const chatRes = await questionDiscussionChat(props.task_id, {
				message,
				questions: questions.value.map((q) => ({
					questionIndex: q.questionIndex,
					questionTitle: q.questionTitle,
					questionText: q.questionText,
					chatHistory: q.chatHistory,
				})),
				original_problem: taskStore.originalProblemText,
			});
			if (chatRes.data?.content) {
				// 附加到第一个问题的 chatHistory 作为上下文
				if (questions.value.length > 0) {
					questions.value[0].chatHistory = [
						...questions.value[0].chatHistory,
						{ role: "user", content: message },
						{ role: "assistant", content: chatRes.data.content },
					];
				}
			}
		} catch {
			// 对话失败不影响主流程
		}
	} catch (e: unknown) {
		const detail =
			(e as { response?: { data?: { detail?: string } } })?.response?.data
				?.detail || "讨论失败，请重试";
		// 仅在重新生成失败时也尝试纯对话
		try {
			const chatRes = await questionDiscussionChat(props.task_id, {
				message,
				questions: questions.value.map((q) => ({
					questionIndex: q.questionIndex,
					questionTitle: q.questionTitle,
					questionText: q.questionText,
					chatHistory: q.chatHistory,
				})),
				original_problem: taskStore.originalProblemText,
			});
			if (chatRes.data?.content && questions.value.length > 0) {
				questions.value[0].chatHistory = [
					...questions.value[0].chatHistory,
					{ role: "user", content: message },
					{
						role: "assistant",
						content: chatRes.data.content + `\n\n（重新生成失败：${detail}）`,
					},
				];
			}
		} catch {
			// 两项都失败，静默
		}
	} finally {
		chatting.value = false;
	}
}

function handleChatSend() {
	const msg = chatInput.value.trim();
	if (!msg || chatting.value || props.disabled) return;
	chatInput.value = "";
	handleSendMessage(msg);
}

// Coordinator 数据就绪后初始化问题卡片
watch(
	questionsList,
	(list) => {
		if (list.length > 0 && questions.value.length === 0) {
			questions.value = buildQuestionCards();
			taskStore.questionCards = [...questions.value];
			// 加载原始题目
			loadOriginalProblem();
		}
	},
	{ immediate: true },
);
</script>

<template>
	<div class="question-discussion flex flex-col glass-root max-h-[55%]">
		<!-- 标题栏（始终可见，折叠/展开共用同一背景） -->
		<button
			class="glass-header border-b border-white/20 px-4 py-2 flex items-center gap-2 w-full text-left cursor-pointer hover:bg-white/40 transition-colors"
			@click="emit('toggle')"
		>
			<Lightbulb class="h-4 w-4 text-indigo-600 flex-shrink-0" />
			<span class="text-sm font-semibold text-slate-950 flex-1">题目问题讨论</span>
			<span v-if="locked" class="text-[10px] text-slate-400">（已确认）</span>
			<span v-else class="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] font-medium text-indigo-600">
				待确认
			</span>
			<span class="text-xs text-slate-400 transition-transform" :class="expanded ? 'rotate-180' : ''">▼</span>
		</button>

		<!-- 内容区（仅展开时显示） -->
		<template v-if="expanded">
		<div class="flex-1 overflow-y-auto px-4 pt-0 pb-3">
			<div v-if="questions.length === 0 && !locked" class="flex items-center justify-center py-8">
				<LoaderCircle class="h-5 w-5 animate-spin text-indigo-500" />
				<span class="ml-2 text-sm text-slate-500">等待 Coordinator 拆解问题...</span>
			</div>

			<div v-if="loadingProblem" class="mb-3 flex items-center gap-1.5 text-[10px] text-slate-400">
				<LoaderCircle class="h-3 w-3 animate-spin" />
				加载原始题目...
			</div>

			<QuestionCardStack
				v-if="questions.length > 0"
				:questions="questions"
				:disabled="disabled"
				@update:questions="handleUpdateQuestions"
			/>

			<div v-if="!disabled && questions.length > 0" class="rounded-xl border border-white/20 bg-white/40 backdrop-blur mt-3">
				<div class="flex items-center gap-1.5 border-b border-white/10 px-3 py-2">
					<Sparkles class="h-3.5 w-3.5 text-indigo-600" />
					<span class="text-[11px] font-medium text-slate-600">与 Agent 讨论问题划分</span>
				</div>
				<div class="flex items-center gap-2 px-3 py-2">
					<input
						v-model="chatInput"
						type="text"
						class="flex-1 rounded-lg border border-slate-200 bg-white/80 px-2.5 py-1.5 text-xs text-slate-700 placeholder:text-slate-400 focus:border-indigo-400 focus:outline-none"
						placeholder="例如：请把问题拆成预测、优化、评价三个方向..."
						:disabled="disabled || chatting"
						@keydown.enter="handleChatSend"
					/>
					<button
						class="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-indigo-600 text-white transition-colors hover:bg-indigo-700 disabled:opacity-40"
						:disabled="!chatInput.trim() || disabled || chatting"
						@click="handleChatSend"
					>
						<Send class="h-3.5 w-3.5" />
					</button>
				</div>
			</div>

			<div v-if="!disabled && questions.length > 0 && questions.every(q => q.questionText.trim())" class="flex justify-end pt-3">
				<button
					class="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 px-5 py-2.5 text-sm font-semibold text-white shadow-[0_4px_20px_rgba(99,102,241,0.35)] transition-all duration-300 hover:shadow-[0_6px_28px_rgba(99,102,241,0.5)] hover:scale-105 active:scale-100 disabled:opacity-50"
					:disabled="confirming"
					@click="handleConfirm"
				>
					<Sparkles class="h-4 w-4" />
					{{ confirming ? "提交中..." : "确认问题划分" }}
				</button>
			</div>

			<div v-if="confirmError" class="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
				{{ confirmError }}
			</div>

			<div v-if="confirming" class="mt-3 flex items-center justify-center gap-2 text-sm text-indigo-600">
				<RefreshCw class="h-4 w-4 animate-spin" />
				正在提交问题划分...
			</div>

			<div v-if="chatting" class="mt-3 flex items-center justify-center gap-2 text-xs text-slate-400">
				<LoaderCircle class="h-3.5 w-3.5 animate-spin" />
				Agent 正在分析题目并调整问题划分...
			</div>
		</div>
		</template>
	</div>
</template>

<style scoped>
.glass-root {
	background: linear-gradient(
		135deg,
		rgba(248, 250, 252, 0.95) 0%,
		rgba(241, 245, 249, 0.9) 30%,
		rgba(226, 232, 240, 0.85) 60%,
		rgba(241, 245, 249, 0.9) 100%
	);
	backdrop-filter: blur(20px);
	-webkit-backdrop-filter: blur(20px);
	border-top: 1px solid rgba(255, 255, 255, 0.2);
}

.glass-header {
	background: rgba(255, 255, 255, 0.55);
	backdrop-filter: blur(16px);
	-webkit-backdrop-filter: blur(16px);
}

.question-discussion {
	overflow: hidden;
}
</style>
