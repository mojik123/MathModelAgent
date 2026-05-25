<script setup lang="ts">
import { confirmModeling, generateModelingOptions } from "@/apis/commonApi";
import { useTaskStore } from "@/stores/task";
import { AgentType } from "@/utils/enum";
import { Lightbulb, LoaderCircle, RefreshCw, Wand2 } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import ModelingCardStack from "./ModelingCardStack.vue";

const emit = defineEmits<{
	confirm: [];
	toggle: [];
}>();

const props = defineProps<{
	disabled?: boolean;
	expanded?: boolean;
	locked?: boolean;
}>();

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
	sourceDetails?: Array<Record<string, unknown>>;
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

const taskStore = useTaskStore();
const route = useRoute();
const taskId = route.params.task_id as string;

const questions = ref<QuestionCard[]>([]);
const showDiscussion = ref(false);
const confirming = ref(false);
const confirmError = ref("");
const optionsLoading = ref(false);
const optionsError = ref("");
const referenceSearchEnabled = ref(true);
let optionsRequestSeq = 0;
let optionsAttemptedSignature = "";
let progressStartIndex = 0;
const progressKey = ref(0);

function startProgressAnimation() {
	progressKey.value += 1;
}

function stopProgressAnimation() {}

const activeReferenceTools = computed(() => referenceSearchEnabled.value ? ["openalex"] : []);
const referenceStatusText = computed(() => referenceSearchEnabled.value ? "参考文献检索：OpenAlex" : "参考文献检索：关闭");

function getReferenceStorageKey() {
	return `modeling-reference-tools:${taskId}`;
}

function persistReferencePreference() {
	if (typeof window === "undefined") return;
	window.localStorage.setItem(getReferenceStorageKey(), JSON.stringify({
		enabled: referenceSearchEnabled.value,
		tools: ["openalex"],
	}));
}

function restoreReferencePreference() {
	if (typeof window === "undefined") return;
	try {
		const raw = window.localStorage.getItem(getReferenceStorageKey());
		if (!raw) return;
		const parsed = JSON.parse(raw);
		referenceSearchEnabled.value = parsed.enabled !== false;
	} catch {
		// ignore broken local storage
	}
}
restoreReferencePreference();

function toggleReferenceSearch() {
	if (optionsLoading.value || props.locked) return;
	referenceSearchEnabled.value = !referenceSearchEnabled.value;
	persistReferencePreference();
	optionsAttemptedSignature = "";
}

const modelOptionsProgressText = computed(() => {
	const msgs = taskStore.messages;
	for (let i = msgs.length - 1; i >= progressStartIndex; i--) {
		const c = msgs[i].content ?? "";
		if (
			c.includes("正在检索文献") ||
			c.includes("生成模型方案") ||
			c.includes("已完成") ||
			c.includes("模型候选方案生成完成") ||
			c.includes("并行检索与生成") ||
			c.includes("参考文献检索") ||
			c.includes("OpenAlex")
		) return c;
	}
	return `ModelerAgent 正在筛选候选模型 · ${referenceStatusText.value}`;
});

const optionsEstimatedSec = computed(() => Math.max(questionsList.value.length * (referenceSearchEnabled.value ? 55 : 35), 30));

type GenStatus = "waiting" | "searching" | "generating" | "retrying" | "done";
const questionGenStatus = computed<Record<number, { status: GenStatus; text: string }>>(() => {
	const result: Record<number, { status: GenStatus; text: string }> = {};
	for (const q of questions.value) result[q.questionIndex] = { status: "waiting", text: "等待生成..." };
	const msgs = taskStore.messages;
	for (let i = progressStartIndex; i < msgs.length; i++) {
		const c = msgs[i].content ?? "";
		const match = c.match(/第\s*(\d+)\s*问/);
		if (!match) continue;
		const idx = parseInt(match[1]);
		if (!result[idx]) continue;
		if (c.includes("检索")) result[idx] = { status: "searching", text: "正在检索 OpenAlex..." };
		if (c.includes("生成")) result[idx] = { status: "generating", text: "正在生成候选模型..." };
		if (c.includes("质量未达标") || c.includes("重新生成")) result[idx] = { status: "retrying", text: "质量检查未通过，重新生成中..." };
		if (c.includes("候选方案生成完成")) result[idx] = { status: "done", text: "生成完毕" };
	}
	for (const q of questions.value) {
		if (q.presetOptions.length > 0 && result[q.questionIndex]?.status !== "done") {
			result[q.questionIndex] = { status: "done", text: "生成完毕" };
		}
	}
	return result;
});

const coordinatorData = computed(() => {
	const msgs = taskStore.coordinatorMessages.filter((m: any) => m.stream_state !== "streaming");
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

const problemTitle = computed(() => {
	const data = coordinatorData.value;
	if (!data) return "";
	return (data.title as string) || "建模问题";
});

const problemBackground = computed(() => {
	const data = coordinatorData.value;
	if (!data) return "";
	return (data.background as string) || "";
});

const questionsList = computed(() => {
	if (taskStore.questionCards.length > 0) {
		return taskStore.questionCards.map((q) => ({ index: q.questionIndex, text: q.questionText }));
	}
	const data = coordinatorData.value;
	if (!data) return [];
	const count = (data.ques_count as number) || 0;
	const list: Array<{ index: number; text: string }> = [];
	for (let i = 1; i <= count; i++) list.push({ index: i, text: (data[`ques${i}`] as string) || `第 ${i} 问` });
	return list;
});

const optionsSignature = computed(() => JSON.stringify({
	title: problemTitle.value,
	background: problemBackground.value,
	questions: questionsList.value,
	referenceSearchEnabled: referenceSearchEnabled.value,
	referenceTools: activeReferenceTools.value,
}));

const coordinatorSignature = computed(() => {
	if (!coordinatorData.value || questionsList.value.length === 0) return "";
	return JSON.stringify({ title: problemTitle.value, background: problemBackground.value, questions: questionsList.value });
});

function getDiscussionStorageKey() {
	return `modeling-discussion:${taskId}`;
}

function persistDiscussionState(items = questions.value) {
	if (typeof window === "undefined") return;
	window.localStorage.setItem(getDiscussionStorageKey(), JSON.stringify(items));
}

function restoreDiscussionState() {
	if (typeof window === "undefined") return [];
	try {
		const raw = window.localStorage.getItem(getDiscussionStorageKey());
		if (!raw) return [];
		const parsed = JSON.parse(raw);
		return Array.isArray(parsed) ? (parsed as QuestionCard[]) : [];
	} catch {
		return [];
	}
}

function buildQuestionCards(): QuestionCard[] {
	const restored = restoreDiscussionState();
	return questionsList.value.map((q) => {
		const existing = questions.value.find((c) => c.questionIndex === q.index) ?? restored.find((c) => c.questionIndex === q.index && c.questionText === q.text);
		if (existing) return existing;
		return {
			questionIndex: q.index,
			questionTitle: `第 ${q.index} 问`,
			questionText: q.text,
			presetOptions: [],
			recommendedOptionId: "",
			selectedOptionId: "",
			customInput: "",
			chatHistory: [],
			confirmed: false,
		};
	});
}

function needsDynamicModelOptions() {
	return Boolean(coordinatorData.value) && questionsList.value.length > 0 && questions.value.length > 0 && !props.locked && questions.value.some((q) => q.presetOptions.length === 0);
}

function normalizeModelOptions(rawOptions: Array<Record<string, unknown>>): ModelOption[] {
	const mapped: Array<ModelOption | null> = rawOptions.map((raw, idx) => {
		const label = String(raw.label ?? raw.model ?? "").trim();
		if (!label) return null;
		const id = String(raw.id ?? `llm_model_${idx + 1}`).trim();
		const score = typeof raw.score === "number" ? raw.score : Number.isFinite(Number(raw.score)) ? Number(raw.score) : null;
		return {
			id,
			label,
			description: String(raw.description ?? "").trim(),
			pros: String(raw.pros ?? "").trim(),
			cons: String(raw.cons ?? "").trim(),
			reason: String(raw.reason ?? "").trim(),
			score,
			isRecommended: Boolean(raw.isRecommended),
			sources: Array.isArray(raw.sources) ? raw.sources.map((item) => String(item)).filter(Boolean) : [],
			sourceDetails: Array.isArray(raw.sourceDetails) ? raw.sourceDetails as Array<Record<string, unknown>> : [],
		};
	});
	return mapped.filter((item): item is ModelOption => item !== null);
}

async function loadDynamicModelOptions(forceRefresh = false) {
	const signature = optionsSignature.value;
	if (!forceRefresh) {
		if (!needsDynamicModelOptions()) return;
		if (optionsAttemptedSignature === signature) return;
	}
	if (optionsLoading.value) return;
	progressStartIndex = taskStore.messages.length;
	if (!coordinatorData.value || questionsList.value.length === 0) return;
	optionsAttemptedSignature = signature;
	const seq = ++optionsRequestSeq;
	optionsLoading.value = true;
	startProgressAnimation();
	optionsError.value = "";
	taskStore.addUserAction("提交", "模型比选请求", `用户请求 ModelerAgent 筛选候选模型。${referenceStatusText.value}`, { from: "User", to: "ModelerAgent", label: "请求模型比选" });
	taskStore.addAgentAction(AgentType.MODELER, "比选", "模型候选方案", `ModelerAgent 正在结合题目目标、数据形态、验证方式和可解释性筛选候选模型。${referenceStatusText.value}`, { from: "User", to: "ModelerAgent", label: "接收比选任务" });
	try {
		const res = await generateModelingOptions(taskId, {
			title: problemTitle.value,
			background: problemBackground.value,
			questions: questionsList.value,
			force_refresh: forceRefresh,
			reference_search_enabled: referenceSearchEnabled.value,
			reference_tools: activeReferenceTools.value,
		});
		if (seq !== optionsRequestSeq) return;
		const generated = new Map(res.data.questions.map((q) => [q.questionIndex, {
			researchSummary: q.researchSummary,
			recommendedOptionId: q.recommendedOptionId,
			options: normalizeModelOptions(q.options),
		}]));
		const updated = questions.value.map((q) => {
			const matched = generated.get(q.questionIndex);
			if (!matched?.options.length) return q;
			const selectedStillExists = matched.options.some((option) => option.id === q.selectedOptionId);
			return { ...q, presetOptions: matched.options, researchSummary: matched.researchSummary, recommendedOptionId: matched.recommendedOptionId, selectedOptionId: selectedStillExists ? q.selectedOptionId : "", confirmed: selectedStillExists ? q.confirmed : false };
		});
		handleQuestionsUpdate(updated);
		const optionSummary = updated.map((q) => {
			const recommended = q.presetOptions.find((option) => option.id === q.recommendedOptionId);
			return recommended ? `第 ${q.questionIndex} 问：${recommended.label}` : `第 ${q.questionIndex} 问：${q.presetOptions.length} 个候选`;
		}).join("；");
		taskStore.addAgentAction(AgentType.MODELER, "传递", "候选模型方案", `ModelerAgent 已完成模型比选并传递给 User：${optionSummary}`, { from: "ModelerAgent", to: "User", label: "提交候选方案" });
	} catch (error) {
		const detail = typeof error === "object" && error && "response" in error && (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
		optionsError.value = detail || "动态模型候选生成失败，可先使用自定义方案。";
	} finally {
		if (seq === optionsRequestSeq) { optionsLoading.value = false; stopProgressAnimation(); }
	}
}

function handleRetryOptions() { void loadDynamicModelOptions(true); }

function handleQuestionsUpdate(updated: QuestionCard[]) {
	questions.value = updated;
	persistDiscussionState(updated);
}

async function handleConfirm() {
	if (confirming.value) return;
	confirmError.value = "";
	const incomplete = questions.value.find((q) => !q.selectedOptionId || (q.selectedOptionId === "__custom__" && !q.customInput.trim()));
	if (incomplete) {
		confirmError.value = `请先选择第 ${incomplete.questionIndex} 问的建模方案。`;
		return;
	}
	const selections = questions.value.map((q) => {
		const selectedOption = q.presetOptions.find((option) => option.id === q.selectedOptionId);
		return {
			index: q.questionIndex,
			question: q.questionText,
			model: q.selectedOptionId === "__custom__" ? q.customInput.trim() : (selectedOption?.label ?? q.selectedOptionId),
			model_id: q.selectedOptionId,
			model_description: selectedOption?.description ?? "",
			model_reason: selectedOption?.reason ?? "",
			model_pros: selectedOption?.pros ?? "",
			model_cons: selectedOption?.cons ?? "",
			model_score: selectedOption?.score ?? null,
			model_sources: selectedOption?.sources ?? [],
			customInput: q.customInput,
			chatHistory: q.chatHistory,
		};
	});
	const selectionSummary = selections.map((item) => `第 ${item.index} 问：${item.model}`).join("；");
	taskStore.addUserAction("确认", "建模方案选择", `用户确认全部问题的建模方案：${selectionSummary}`, { from: "User", to: "ModelerAgent", label: "返回确认选择" });
	confirming.value = true;
	try {
		await confirmModeling(taskId, selections);
		taskStore.addAgentAction(AgentType.MODELER, "接收", "确认建模方案", "ModelerAgent 已接收用户确认的建模方案，后续正式建模以该选择为优先约束。", { from: "User", to: "ModelerAgent", label: "开始正式建模" });
		persistDiscussionState();
		emit("confirm");
	} catch (error) {
		const detail = typeof error === "object" && error && "response" in error && (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
		confirmError.value = detail || "提交建模思路失败，请稍后重试。";
	} finally {
		confirming.value = false;
	}
}

watch(coordinatorSignature, (signature) => {
	if (signature) {
		questions.value = buildQuestionCards();
		persistDiscussionState();
		showDiscussion.value = true;
		if (props.expanded) void loadDynamicModelOptions();
	}
}, { immediate: true });

watch(() => props.expanded, (expanded) => {
	if (expanded) void loadDynamicModelOptions();
});
</script>

<template>
	<div v-if="showDiscussion" class="modeling-discussion flex flex-col glass-root max-h-[80%]">
		<button class="glass-header border-b border-white/20 px-4 py-2 flex items-center gap-2 w-full text-left cursor-pointer hover:bg-white/40 transition-colors" @click="emit('toggle')">
			<Lightbulb class="h-4 w-4 text-amber-500 flex-shrink-0" />
			<span class="text-sm font-semibold text-slate-950 flex-1">建模思路讨论</span>
			<span v-if="props.locked" class="text-[10px] text-slate-400">（已确认）</span>
			<span class="text-xs text-slate-400 transition-transform" :class="props.expanded ? 'rotate-180' : ''">▼</span>
		</button>
		<template v-if="props.expanded">
			<div class="mt-1.5 text-xs text-slate-600 px-4">{{ problemTitle }}</div>

			<div v-if="!props.locked" class="mx-4 mt-2 rounded-xl border border-blue-100 bg-white/55 p-2.5 text-xs text-slate-700">
				<div class="flex flex-wrap items-center justify-between gap-2">
					<button type="button" class="rounded-lg border px-2.5 py-1 font-semibold transition-colors" :class="referenceSearchEnabled ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-slate-200 bg-slate-50 text-slate-500'" :disabled="optionsLoading" @click.stop="toggleReferenceSearch">
						{{ referenceSearchEnabled ? '使用 OpenAlex 检索' : '不使用参考文献检索' }}
					</button>
					<span class="text-[11px] text-slate-500">{{ referenceStatusText }}</span>
				</div>
				<div v-if="referenceSearchEnabled" class="mt-2 flex items-center justify-between gap-2 text-[11px] text-slate-500">
					<span>当前只使用 OpenAlex 一个数据源检索论文题名、年份、DOI、摘要和概念标签。</span>
					<button type="button" class="rounded-full border border-blue-200 bg-white/70 px-2.5 py-1 font-medium text-blue-700 disabled:opacity-50" :disabled="optionsLoading" @click.stop="handleRetryOptions">
						用 OpenAlex 重新生成
					</button>
				</div>
				<div v-else class="mt-2 flex items-center justify-between gap-2 text-[11px] text-slate-500">
					<span>关闭后候选模型只根据题面、数据结构和建模经验生成。</span>
					<button type="button" class="rounded-full border border-slate-200 bg-white/70 px-2.5 py-1 font-medium text-slate-700 disabled:opacity-50" :disabled="optionsLoading" @click.stop="handleRetryOptions">不检索，重新生成</button>
				</div>
			</div>

			<div v-if="optionsLoading || optionsError" class="px-4 pt-2">
				<div v-if="optionsLoading" class="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 space-y-2">
					<div class="flex items-center gap-2">
						<LoaderCircle class="h-3.5 w-3.5 animate-spin text-blue-600 shrink-0" />
						<span class="text-xs text-blue-700 shimmer-text">{{ modelOptionsProgressText }}</span>
					</div>
					<div class="relative h-1.5 rounded-full bg-blue-200 overflow-hidden">
						<div class="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-blue-500 via-indigo-500 to-blue-500 progress-bar-shimmer" :style="{ animation: `progress-grow ${optionsEstimatedSec}s ease-out forwards` }" />
					</div>
					<div class="text-[10px] text-blue-500">{{ questionsList.length }} 个问题 · {{ referenceStatusText }}</div>
				</div>
				<div v-else-if="optionsError" class="flex items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
					<span>{{ optionsError }}</span>
					<div class="inline-flex shrink-0 items-center gap-1 rounded-md border border-amber-300 bg-white/70 px-2 py-1 text-[11px] font-medium text-amber-700 hover:bg-white" :disabled="optionsLoading" @click.stop="handleRetryOptions">
						<RefreshCw class="h-3 w-3" />重新筛选
					</div>
				</div>
			</div>

			<div class="flex-1 min-h-0 overflow-y-auto px-4 py-4">
				<ModelingCardStack
					v-if="questions.length > 0"
					:questions="questions"
					:gen-status="questionGenStatus"
					:submitting="confirming"
					:reference-search-enabled="referenceSearchEnabled"
					:reference-tools="activeReferenceTools"
					@update:questions="handleQuestionsUpdate"
					@confirm="handleConfirm"
					:disabled="props.disabled || props.locked"
				/>
				<div v-if="confirmError" class="mt-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">{{ confirmError }}</div>
				<div v-else class="hidden"></div>
				<div v-if="questions.length === 0" class="flex flex-col items-center justify-center pt-16 text-slate-400">
					<Wand2 class="h-10 w-10 animate-pulse text-blue-400" />
					<div class="mt-3 text-sm">等待 Coordinator 完成问题分析...</div>
				</div>
			</div>

			<div class="border-t border-white/10 px-4 py-2 text-center text-[10px] text-slate-400">
				候选模型由 ModelerAgent 结合题目与 OpenAlex 检索动态筛选 · 也可输入自定义思路
			</div>
		</template>
	</div>
</template>

<style scoped>
.shimmer-text {
	background: linear-gradient(90deg, #1d4ed8 0%, #6366f1 40%, #818cf8 60%, #1d4ed8 100%);
	background-size: 200% 100%;
	-webkit-background-clip: text;
	-webkit-text-fill-color: transparent;
	background-clip: text;
	animation: shimmer 2.5s ease-in-out infinite;
	font-weight: 600;
}

@keyframes shimmer {
	0%, 100% { background-position: 0% 50%; }
	50% { background-position: 100% 50%; }
}

.progress-bar-shimmer {
	background-size: 200% 100%;
	animation: progress-flow 1.8s ease-in-out infinite;
}

@keyframes progress-flow {
	0%, 100% { background-position: 0% 50%; }
	50% { background-position: 100% 50%; }
}

@keyframes progress-grow {
	from { width: 0%; }
	to { width: 92%; }
}

.glass-root {
	background: linear-gradient(135deg, rgba(248, 250, 252, 0.95) 0%, rgba(241, 245, 249, 0.9) 30%, rgba(226, 232, 240, 0.85) 60%, rgba(241, 245, 249, 0.9) 100%);
	backdrop-filter: blur(20px);
	-webkit-backdrop-filter: blur(20px);
}

.glass-header {
	background: rgba(255, 255, 255, 0.55);
	backdrop-filter: blur(16px);
	-webkit-backdrop-filter: blur(16px);
}
</style>