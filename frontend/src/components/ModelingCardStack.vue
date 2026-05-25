<script setup lang="ts">
import { modelingDiscussionChat } from "@/apis/commonApi";
import { useTaskStore } from "@/stores/task";
import { CheckCircle2, ChevronRight, Sparkles } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import ModelingCard from "./ModelingCard.vue";

// ---- Types ----

interface ModelOption {
	id: string;
	label: string;
	description: string;
	pros?: string;
	cons?: string;
	reason?: string;
	score?: number | null;
	isRecommended?: boolean;
	sources?: string[];
}

interface ChatMessage {
	role: "user" | "assistant";
	content: string;
}

interface QuestionCard {
	questionIndex: number;
	questionTitle: string;
	questionText: string;
	presetOptions: ModelOption[];
	researchSummary?: string;
	recommendedOptionId?: string;
	selectedOptionId: string;
	customInput: string;
	chatHistory: ChatMessage[];
	confirmed: boolean;
}

// ---- Props ----

const props = defineProps<{
	questions: QuestionCard[];
	genStatus?: Record<number, { status: string; text: string }>;
	regeneratingQuestionIndexes?: number[];
	disabled?: boolean;
	submitting?: boolean;
}>();

const emit = defineEmits<{
	"update:questions": [questions: QuestionCard[]];
	"regenerate-question": [questionIndex: number];
	confirm: [];
}>();

// ---- State ----

const activeIndex = ref(props.questions.length > 0 ? 0 : -1);
const taskStore = useTaskStore();
const route = useRoute();
const taskId = computed(() => route.params.task_id as string);
const sendingQuestionIndex = ref<number | null>(null);

// ---- Computed ----

const regeneratingQuestionSet = computed(
	() => new Set(props.regeneratingQuestionIndexes ?? []),
);

const anyQuestionRegenerating = computed(
	() => regeneratingQuestionSet.value.size > 0,
);

const allOptionsReady = computed(() =>
	props.questions.length > 0 && props.questions.every((q) => q.presetOptions.length > 0),
);

const allConfirmed = computed(() =>
	allOptionsReady.value &&
	!anyQuestionRegenerating.value &&
	props.questions.every(
		(q) =>
			Boolean(q.selectedOptionId) &&
			(q.selectedOptionId !== "__custom__" || Boolean(q.customInput.trim())),
	),
);

const hasRecommendedOptions = computed(() =>
	allOptionsReady.value && props.questions.some((q) => Boolean(getRecommendedOption(q))),
);

function isQuestionRegenerating(questionIndex: number) {
	return regeneratingQuestionSet.value.has(questionIndex);
}

// 同步展开的卡片到 store，供右侧面板使用
watch(
	activeIndex,
	(idx) => {
		taskStore.activeDiscussionIndex = idx;
		if (idx >= 0 && idx < props.questions.length) {
			taskStore.discussionQuestions = props.questions.map((q) => ({
				questionIndex: q.questionIndex,
				questionTitle: q.questionTitle,
				questionText: q.questionText,
				selectedOptionId: q.selectedOptionId,
				presetOptions: q.presetOptions,
				researchSummary: q.researchSummary,
			}));
		} else {
			taskStore.discussionQuestions = [];
		}
	},
	{ immediate: true },
);

// 问题列表异步加载后自动激活第一个问题，右侧面板随即显示模型对比
watch(
	() => props.questions.length,
	(len) => {
		if (len > 0 && activeIndex.value < 0) {
			activeIndex.value = 0;
		}
	},
);

watch(
	() => props.questions,
	() => {
		if (activeIndex.value >= 0 && activeIndex.value < props.questions.length) {
			taskStore.discussionQuestions = props.questions.map((q) => ({
				questionIndex: q.questionIndex,
				questionTitle: q.questionTitle,
				questionText: q.questionText,
				selectedOptionId: q.selectedOptionId,
				presetOptions: q.presetOptions,
				researchSummary: q.researchSummary,
			}));
		}
	},
	{ deep: true },
);

// ---- Methods ----

function handleSelectOption(questionIndex: number, optionId: string) {
	if (!allOptionsReady.value) return;
	if (isQuestionRegenerating(questionIndex)) return;
	const question = props.questions.find(
		(q) => q.questionIndex === questionIndex,
	);
	const selectedOption = question?.presetOptions.find(
		(option) => option.id === optionId,
	);
	const updated = props.questions.map((q) =>
		q.questionIndex === questionIndex
			? {
					...q,
					selectedOptionId: optionId,
					confirmed:
						optionId === "__custom__" ? Boolean(q.customInput.trim()) : true,
				}
			: q,
	);
	emit("update:questions", updated);
	if (question) {
		taskStore.addUserAction(
			"选择",
			`第 ${questionIndex} 问模型方案`,
			`用户选择第 ${questionIndex} 问模型方案：${
				optionId === "__custom__"
					? "自定义方案"
					: (selectedOption?.label ?? optionId)
			}`,
			{
				from: "User",
				to: "ModelerAgent",
				label: "提交单问选择",
			},
		);
	}
}

function handleCustomInput(questionIndex: number, value: string) {
	if (!allOptionsReady.value) return;
	if (isQuestionRegenerating(questionIndex)) return;
	const updated = props.questions.map((q) =>
		q.questionIndex === questionIndex
			? {
					...q,
					customInput: value,
					selectedOptionId: value ? "__custom__" : q.selectedOptionId,
					confirmed: !!value,
				}
			: q,
	);
	emit("update:questions", updated);
}

function getRecommendedOption(question: QuestionCard) {
	if (!question.presetOptions.length) return null;
	const explicit = question.recommendedOptionId
		? question.presetOptions.find(
				(option) => option.id === question.recommendedOptionId,
			)
		: null;
	if (explicit) return explicit;
	const marked = question.presetOptions.find((option) => option.isRecommended);
	if (marked) return marked;
	return [...question.presetOptions].sort(
		(left, right) => (right.score ?? -1) - (left.score ?? -1),
	)[0];
}

function handleApplyRecommended() {
	if (
		props.disabled ||
		anyQuestionRegenerating.value ||
		!hasRecommendedOptions.value ||
		!allOptionsReady.value
	)
		return;
	const applied = props.questions
		.map((q) => {
			const recommended = getRecommendedOption(q);
			return recommended
				? `第 ${q.questionIndex} 问：${recommended.label}`
				: "";
		})
		.filter(Boolean);
	const updated = props.questions.map((q) => {
		const recommended = getRecommendedOption(q);
		if (!recommended) return q;
		return {
			...q,
			selectedOptionId: recommended.id,
			confirmed: true,
		};
	});
	emit("update:questions", updated);
	taskStore.addUserAction(
		"应用",
		"最优模型方案",
		`用户一键应用 AI 推荐的最优模型方案：${applied.join("；")}`,
		{
			from: "User",
			to: "ModelerAgent",
			label: "采纳AI推荐",
		},
	);
}

function questionPayload(items: QuestionCard[]) {
	return items.map((q) => ({
		questionIndex: q.questionIndex,
		questionTitle: q.questionTitle,
		questionText: q.questionText,
		selectedOptionId: q.selectedOptionId,
		selectedModel:
			q.selectedOptionId === "__custom__"
				? q.customInput
				: (q.presetOptions.find((option) => option.id === q.selectedOptionId)
						?.label ?? q.selectedOptionId),
		customInput: q.customInput,
		chatHistory: q.chatHistory,
		presetOptions: q.presetOptions,
		researchSummary: q.researchSummary,
	}));
}

async function handleSendMessage(questionIndex: number, message: string) {
	if (
		sendingQuestionIndex.value != null ||
		props.disabled ||
		!allOptionsReady.value ||
		isQuestionRegenerating(questionIndex)
	)
		return;
	const withUser = props.questions.map((q) =>
		q.questionIndex === questionIndex
			? {
					...q,
					chatHistory: [
						...q.chatHistory,
						{ role: "user" as const, content: message },
					],
				}
			: q,
	);
	emit("update:questions", withUser);
	taskStore.addUserAction(
		"询问",
		`第 ${questionIndex} 问建模方案`,
		`用户在第 ${questionIndex} 问讨论区追问：${message}`,
		{
			from: "User",
			to: "ModelerAgent",
			label: "补充建模偏好",
		},
	);
	sendingQuestionIndex.value = questionIndex;
	try {
		const res = await modelingDiscussionChat(taskId.value, {
			question_index: questionIndex,
			message,
			questions: questionPayload(withUser),
		});
		// 如果在等待回复期间用户已确认锁定，丢弃迟到的 AI 回复
		if (props.disabled) return;
		const withAssistant = withUser.map((q) =>
			q.questionIndex === questionIndex
				? {
						...q,
						chatHistory: [
							...q.chatHistory,
							{
								role: "assistant" as const,
								content: res.data.content || res.data.message,
							},
						],
					}
				: q,
		);
		emit("update:questions", withAssistant);
	} catch (error) {
		const detail =
			typeof error === "object" &&
			error &&
			"response" in error &&
			(error as { response?: { data?: { detail?: string } } }).response?.data
				?.detail;
		const withError = withUser.map((q) =>
			q.questionIndex === questionIndex
				? {
						...q,
						chatHistory: [
							...q.chatHistory,
							{
								role: "assistant" as const,
								content: detail || "建模讨论暂时失败，请稍后重试。",
							},
						],
					}
				: q,
		);
	emit("update:questions", withError);
	} finally {
		sendingQuestionIndex.value = null;
	}
}
</script>

<template>
	<div class="card-stack-container space-y-2">
		<div
			v-for="(question, idx) in questions"
			:key="question.questionIndex"
			class="stack-item"
			:style="{
				zIndex:
					idx === activeIndex
						? 10
						: questions.length - Math.abs(idx - activeIndex),
			}"
		>
			<ModelingCard
				:question-index="question.questionIndex"
				:question-title="question.questionTitle"
				:question-text="question.questionText"
				:preset-options="question.presetOptions"
				:gen-status="props.genStatus?.[question.questionIndex]"
				:is-expanded="true"
				:selected-option-id="question.selectedOptionId"
				:custom-input="question.customInput"
				:chat-history="question.chatHistory"
				:regenerating="isQuestionRegenerating(question.questionIndex)"
				:disabled="props.disabled || sendingQuestionIndex === question.questionIndex || isQuestionRegenerating(question.questionIndex) || !allOptionsReady"
				@select-option="(optId: string) => handleSelectOption(question.questionIndex, optId)"
				@update:custom-input="(val: string) => handleCustomInput(question.questionIndex, val)"
				@send-message="(msg: string) => handleSendMessage(question.questionIndex, msg)"
				@regenerate="emit('regenerate-question', question.questionIndex)"
				@toggle-expand="activeIndex = idx"
			/>
		</div>

		<div v-if="anyQuestionRegenerating && !props.disabled" class="rounded-xl border border-amber-200 bg-amber-50/80 px-3 py-2 text-xs text-amber-700">
			单问建模思路正在重新生成。生成完成并重新选择后，才能确定建模思路。
		</div>

		<div v-if="!allOptionsReady && !props.disabled" class="rounded-xl border border-blue-200 bg-blue-50/80 px-3 py-2 text-xs text-blue-700">
			建模候选方案仍在生成中。生成完成前不能应用推荐方案或确认建模思路。
		</div>

		<!-- 确认按钮：仅在未禁用且全部确认时显示 -->
		<div v-if="!props.disabled" class="flex justify-end pt-3">
			<button
				class="inline-flex items-center gap-2 rounded-xl border border-amber-300 bg-amber-50 px-4 py-2 text-sm font-semibold text-amber-700 transition-colors hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
				:disabled="!hasRecommendedOptions || !allOptionsReady || anyQuestionRegenerating || sendingQuestionIndex !== null"
				@click="handleApplyRecommended"
			>
				<Sparkles class="h-4 w-4" />
				{{ allOptionsReady ? "应用最优模型" : "等待方案生成" }}
			</button>
		</div>

		<Transition name="confirm-btn">
			<div v-if="(allConfirmed || anyQuestionRegenerating) && allOptionsReady && !props.disabled" class="flex justify-end pt-3">
				<button
					class="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-[0_4px_20px_rgba(59,130,246,0.35)] transition-all duration-300 hover:shadow-[0_6px_28px_rgba(59,130,246,0.5)] hover:scale-105 active:scale-100 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:scale-100"
					:disabled="props.submitting || !allConfirmed || !allOptionsReady || anyQuestionRegenerating"
					@click="emit('confirm')"
				>
					<CheckCircle2 class="h-4 w-4" />
					{{ anyQuestionRegenerating ? "重新生成中..." : props.submitting ? "提交中..." : "确定建模思路" }}
					<ChevronRight class="h-4 w-4" />
				</button>
			</div>
		</Transition>
	</div>
</template>

<style scoped>
.stack-item {
	position: relative;
	transition:
		transform 0.35s cubic-bezier(0.4, 0, 0.2, 1),
		margin 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}

.confirm-btn-enter-active {
	transition: all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.confirm-btn-leave-active {
	transition: all 0.2s ease;
}

.confirm-btn-enter-from {
	opacity: 0;
	transform: translateY(10px) scale(0.9);
}

.confirm-btn-leave-to {
	opacity: 0;
	transform: translateY(6px) scale(0.95);
}
</style>
