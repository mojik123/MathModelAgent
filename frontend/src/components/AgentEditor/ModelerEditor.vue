<script setup lang="ts">
import {
	ResizableHandle,
	ResizablePanel,
	ResizablePanelGroup,
} from "@/components/ui/resizable";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useTaskStore } from "@/stores/task";
import { renderMarkdown } from "@/utils/markdown";
import {
	BookOpen,
	FileQuestion,
	FlaskConical,
	Lightbulb,
	Sparkles,
} from "lucide-vue-next";
import { computed, ref, watch } from "vue";

const props = defineProps<{ task_id: string }>();
const taskStore = useTaskStore();
const renderedModelerBlocks = ref<Record<string, string>>({});

/** 建模方案是否已确认（确认后应显示建模手册而非模型对比） */
const modelingConfirmed = computed(() => {
	if (typeof window !== "undefined" &&
		window.localStorage.getItem(`modeling-confirmed:${props.task_id}`) === "true") {
		return true;
	}
	return taskStore.messages.some(
		(m) => m.msg_type === "system" &&
			((m.content ?? "").includes("建模方案已确认") ||
			 (m.content ?? "").includes("已复用建模方案选择")),
	);
});

/** 是否处于问题划分讨论阶段（显示原始题目而非建模方案） */
const isQuestionDiscussionPhase = computed(() =>
	taskStore.messages.some(
		(m) =>
			m.msg_type === "system" &&
			(m.content ?? "").includes("等待用户确认问题划分"),
	) &&
	!taskStore.messages.some(
		(m) =>
			m.msg_type === "system" &&
			(m.content ?? "").includes("问题划分已确认"),
	),
);

/** Coordinator 正在解析题目（尚未进入问题讨论阶段，含初始等待） */
const isCoordinatorParsing = computed(() => {
	const hasQuestionPhase = taskStore.messages.some(
		(m) =>
			m.msg_type === "system" &&
			((m.content ?? "").includes("等待用户确认问题划分") ||
				(m.content ?? "").includes("问题划分已确认")),
	);
	const hasModelingPhase = taskStore.messages.some(
		(m) =>
			m.msg_type === "system" &&
			((m.content ?? "").includes("等待用户确认各问建模方案") ||
				(m.content ?? "").includes("建模方案已确认")),
	);
	if (hasQuestionPhase || hasModelingPhase) return false;
	// 有 coordinator 输出但还没解析出 JSON → 正在解析中
	if (taskStore.coordinatorMessages.length > 0) return true;
	// 任务已启动但 coordinator 还没消息 → 初始等待
	if (taskStore.isRunning || taskStore.coordinatorMessages.length > 0) return true;
	// 有消息但没有任何阶段 → 也是初始状态
	if (taskStore.messages.length > 0 && !coordinatorData.value && modelerBlocks.value.length === 0) return true;
	return false;
});

/** 所有讨论问题的 presetOptions 是否都为空（方案还在生成中） */
const allOptionsEmpty = computed(() => {
	const questions = taskStore.discussionQuestions;
	if (questions.length === 0) return true;
	return questions.every((q) => q.presetOptions.length === 0);
});

/** ModelerAgent 生成方案过程中的最新进度反馈 */
const optionsProgressMessage = computed(() => {
	// 优先取最新的 ModelerAgent 系统消息
	for (let i = taskStore.messages.length - 1; i >= 0; i--) {
		const m = taskStore.messages[i];
		if (m.msg_type !== "system") continue;
		const content = m.content ?? "";
		if (content.includes("ModelerAgent") || content.includes("建模手") || content.includes("模型")) {
			return content;
		}
	}
	// 退而取最新的 modeler agent 消息
	const modelerMsgs = taskStore.modelerMessages;
	if (modelerMsgs.length > 0) {
		const last = modelerMsgs[modelerMsgs.length - 1];
		return last.content ?? "";
	}
	return "";
});

const latestCoordinatorMessage = computed(() => {
	const messages = taskStore.coordinatorMessages;
	// 跳过流式消息，只用最终完整消息
	const complete = messages.filter((m) => m.stream_state !== "streaming");
	return complete.length > 0 ? complete[complete.length - 1] : null;
});

const coordinatorData = computed(() => {
	if (!latestCoordinatorMessage.value?.content) return null;
	try {
		const content = latestCoordinatorMessage.value.content;
		const cleanContent = content
			.replace(/```json\n?/, "")
			.replace(/```$/, "")
			.trim();
		return JSON.parse(cleanContent);
	} catch (error) {
		console.error("解析CoordinatorMessage失败:", error);
		return null;
	}
});

const latestModelerMessage = computed(() => {
	const messages = taskStore.modelerMessages;
	// 跳过流式消息，只用最终完整消息
	const complete = messages.filter((m) => m.stream_state !== "streaming");
	return complete.length > 0 ? complete[complete.length - 1] : null;
});

const modelerData = computed(() => {
	if (!latestModelerMessage.value?.content) return null;
	try {
		const content = latestModelerMessage.value.content;
		const cleanContent = content
			.replace(/```json\n?/, "")
			.replace(/```$/, "")
			.trim();
		return JSON.parse(cleanContent);
	} catch (error) {
		console.error("解析ModelerMessage失败:", error);
		return null;
	}
});

const questionsList = computed(() => {
	if (!coordinatorData.value) return [];
	const questions = [];
	for (let i = 1; i <= coordinatorData.value.ques_count; i++) {
		const quesKey = `ques${i}`;
		if (coordinatorData.value[quesKey])
			questions.push({
				number: i,
				content: coordinatorData.value[quesKey],
			});
	}
	return questions;
});

const modelerBlocks = computed(() => {
	if (!modelerData.value) return [];
	const blocks: {
		key: string;
		title: string;
		badge: string;
		content: string;
	}[] = [];
	if (modelerData.value.eda)
		blocks.push({
			key: "eda",
			title: "探索性数据分析",
			badge: "EDA",
			content: modelerData.value.eda,
		});
	for (const question of questionsList.value) {
		const key = `ques${question.number}`;
		if (modelerData.value[key]) {
			blocks.push({
				key,
				title: `问题 ${question.number} 解决方案`,
				badge: `问题${question.number}`,
				content: modelerData.value[key],
			});
		}
	}
	if (modelerData.value.sensitivity_analysis) {
		blocks.push({
			key: "sensitivity_analysis",
			title: "敏感性分析",
			badge: "敏感性分析",
			content: modelerData.value.sensitivity_analysis,
		});
	}
	return blocks;
});

watch(
	modelerBlocks,
	async (blocks) => {
		const rendered: Record<string, string> = {};
		for (const block of blocks)
			rendered[block.key] = await renderMarkdown(block.content);
		renderedModelerBlocks.value = rendered;
	},
	{ immediate: true },
);

// ---- 模型对比辅助函数 ----

type DiscussionOption = {
	id: string;
	label: string;
	description: string;
	pros?: string;
	cons?: string;
	reason?: string;
	score?: number | null;
	isRecommended?: boolean;
};

function getPros(option: DiscussionOption): string {
	return option.pros || "需结合数据规模、特征质量和验证集表现进一步确认。";
}

function getCons(option: DiscussionOption): string {
	return option.cons || "需要在正式建模阶段通过基线模型和交叉验证检验。";
}

function getAIRecommendation(idx: number): string {
	const q = taskStore.discussionQuestions[idx];
	if (!q?.presetOptions?.length) return "等待问题数据...";
	const opt =
		q.presetOptions.find((o) => o.isRecommended) ?? q.presetOptions[0];
	return opt ? opt.label : "自定义方案";
}

function getRecommendationReason(idx: number): string {
	const q = taskStore.discussionQuestions[idx];
	if (!q?.presetOptions?.length) return "";
	const opt =
		q.presetOptions.find((o) => o.isRecommended) ?? q.presetOptions[0];
	return (
		opt?.reason ||
		q.researchSummary ||
		"该推荐来自 ModelerAgent 对题目目标、数据形态和候选模型可实现性的综合比选。"
	);
}
</script>
<template>
  <div class="h-full p-4">
    <ResizablePanelGroup
      direction="vertical"
      class="h-full rounded-xl border glass-panel overflow-hidden"
    >
      <!-- 上半部分：题目信息 -->
      <ResizablePanel :default-size="30" :min-size="18">
        <div class="flex h-full flex-col">
          <div class="glass-header px-4 py-3 flex items-center gap-2">
            <FileQuestion class="h-4 w-4 text-blue-600" />
            <h2 class="text-base font-semibold text-slate-800">题目信息</h2>
          </div>
          <ScrollArea class="modeler-scroll min-h-0 flex-1">
            <div class="p-5 space-y-5">
              <div v-if="coordinatorData">
                <!-- 标题 -->
                <div class="glass-card rounded-xl p-4">
                  <div class="flex items-center gap-2 mb-3">
                    <Lightbulb class="h-4 w-4 text-amber-500" />
                    <span class="text-xs font-medium text-slate-500 uppercase tracking-wide">题目标题</span>
                  </div>
                  <h3 class="text-lg font-bold text-slate-900 leading-relaxed">
                    {{ coordinatorData.title }}
                  </h3>
                </div>

                <!-- 背景 -->
                <div class="glass-card rounded-xl p-4">
                  <div class="flex items-center gap-2 mb-3">
                    <BookOpen class="h-4 w-4 text-indigo-500" />
                    <span class="text-xs font-medium text-slate-500 uppercase tracking-wide">题目背景</span>
                  </div>
                  <div class="text-sm leading-7 text-slate-700 whitespace-pre-wrap">
                    {{ coordinatorData.background }}
                  </div>
                </div>

                <!-- 问题列表 -->
                <div class="glass-card rounded-xl p-4">
                  <div class="flex items-center gap-2 mb-3">
                    <FlaskConical class="h-4 w-4 text-emerald-500" />
                    <span class="text-xs font-medium text-slate-500 uppercase tracking-wide">问题列表</span>
                    <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">
                      {{ coordinatorData.ques_count }} 问
                    </span>
                  </div>
                  <div class="space-y-3">
                    <div
                      v-for="question in questionsList"
                      :key="question.number"
                      class="question-card rounded-xl px-4 py-3 transition-all duration-200"
                    >
                      <div class="flex items-start gap-3">
                        <span class="question-number shrink-0 mt-0.5 inline-flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold">
                          {{ question.number }}
                        </span>
                        <div class="text-sm leading-7 text-slate-700">
                          {{ question.content }}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <div v-else class="flex h-32 items-center justify-center text-sm text-slate-400">
                等待协调者分析问题...
              </div>
            </div>
          </ScrollArea>
        </div>
      </ResizablePanel>

      <ResizableHandle with-handle />

	      <!-- 下半部分：建模确认前显示模型对比，确认后显示建模手册 -->
	      <ResizablePanel :default-size="70" :min-size="20">
	        <!-- 建模确认前：模型对比 -->
	        <!-- 问题讨论阶段：显示原始题目 -->
	        <template v-if="isQuestionDiscussionPhase">
	          <div class="flex h-full flex-col">
	            <div class="glass-header px-4 py-3 flex items-center gap-2">
	              <FileQuestion class="h-4 w-4 text-indigo-600" />
	              <h2 class="text-base font-semibold text-slate-800">原始题目</h2>
	              <span class="ml-auto rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] font-medium text-indigo-600">待确认问题划分</span>
	            </div>
	            <ScrollArea class="modeler-scroll min-h-0 flex-1">
	              <div class="p-5">
	                <pre class="whitespace-pre-wrap rounded-xl border border-slate-200 bg-white/80 p-5 text-sm leading-7 text-slate-700 font-sans">{{ taskStore.originalProblemText || "正在加载原始题目..." }}</pre>
	              </div>
	            </ScrollArea>
	          </div>
	        </template>
	        <!-- Coordinator 解析题目中：进度视图 -->
	        <template v-else-if="isCoordinatorParsing">
	          <div class="flex h-full flex-col">
	            <div class="glass-header px-4 py-3 flex items-center gap-2">
	              <FileQuestion class="h-4 w-4 text-blue-600" />
	              <h2 class="text-base font-semibold text-slate-800">题目解析</h2>
	            </div>
	            <div class="flex-1 flex items-center justify-center">
	              <div class="text-center space-y-5 max-w-md px-6">
	                <div class="inline-flex items-center justify-center">
	                  <span class="relative flex h-12 w-12">
	                    <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-300/60" />
	                    <span class="relative inline-flex h-12 w-12 items-center justify-center rounded-full bg-blue-100/80 border border-blue-200">
	                      <FileQuestion class="h-5 w-5 text-blue-500 animate-pulse" />
	                    </span>
	                  </span>
	                </div>
	                <div>
	                  <p class="text-sm font-semibold text-slate-700">CoordinatorAgent 正在解析题目结构</p>
	                  <p class="mt-1.5 text-xs text-slate-500 leading-relaxed">正在识别题目类型、拆解子问题、提取关键信息，完成后将进入问题划分讨论…</p>
	                </div>
	              </div>
	            </div>
	          </div>
	        </template>
	        <!-- 建模确认前：模型对比 -->
	        <template v-else-if="taskStore.activeDiscussionIndex >= 0 && !modelingConfirmed">
	          <!-- 方案生成中：进度视图 -->
	          <div v-if="allOptionsEmpty" class="flex h-full flex-col">
	            <div class="glass-header px-4 py-3 flex items-center gap-2">
	              <Sparkles class="h-4 w-4 text-purple-500" />
	              <h2 class="text-base font-semibold text-slate-800">模型对比</h2>
	            </div>
	            <div class="flex-1 flex items-center justify-center">
	              <div class="text-center space-y-5 max-w-md px-6">
	                <div class="inline-flex items-center justify-center">
	                  <span class="relative flex h-12 w-12">
	                    <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-purple-300/60" />
	                    <span class="relative inline-flex h-12 w-12 items-center justify-center rounded-full bg-purple-100/80 border border-purple-200">
	                      <Sparkles class="h-5 w-5 text-purple-500 animate-pulse" />
	                    </span>
	                  </span>
	                </div>
	                <div>
	                  <p class="text-sm font-semibold text-slate-700">ModelerAgent 正在检索与筛选候选模型</p>
	                  <p class="mt-1.5 text-xs text-slate-500 leading-relaxed">正在结合题目信息与联网检索结果，为每个子问题匹配最优建模方案，请稍候…</p>
	                </div>
	                <div v-if="optionsProgressMessage" class="rounded-xl border border-purple-200 bg-purple-50/60 px-4 py-3">
	                  <div class="text-xs font-medium text-purple-600 mb-1">最新进度</div>
	                  <div class="text-xs text-slate-600 leading-relaxed">{{ optionsProgressMessage }}</div>
	                </div>
	              </div>
	            </div>
	          </div>
	          <!-- 方案已生成：逐问对比视图 -->
	          <div v-else class="flex h-full flex-col">
	            <div class="glass-header px-4 py-3 flex items-center gap-2">
	              <Sparkles class="h-4 w-4 text-purple-500" />
	              <h2 class="text-base font-semibold text-slate-800">模型对比 · 第 {{ taskStore.activeDiscussionIndex + 1 }} 问</h2>
	            </div>
	            <ScrollArea class="modeler-scroll min-h-0 flex-1">
	              <div class="p-4 space-y-4">
	                <div class="rounded-xl border border-purple-200 bg-purple-50/50 px-4 py-3">
	                  <div class="text-xs font-medium text-purple-700 mb-1">当前讨论问题</div>
	                  <div class="text-sm text-slate-700 leading-relaxed">
	                    {{ taskStore.discussionQuestions[taskStore.activeDiscussionIndex]?.questionText }}
	                  </div>
	                </div>
	                <div class="rounded-xl border border-amber-200 bg-amber-50/60 px-4 py-3">
	                  <div class="flex items-center gap-2 mb-2">
	                    <span class="rounded-full bg-amber-500 px-2 py-0.5 text-[10px] font-semibold text-white">AI 推荐</span>
	                    <span class="text-xs text-amber-700">基于问题特征分析</span>
	                  </div>
	                  <div class="text-sm font-semibold text-slate-800">
	                    {{ getAIRecommendation(taskStore.activeDiscussionIndex) }}
	                  </div>
	                  <div class="mt-1.5 text-xs text-slate-500 leading-relaxed">
	                    {{ getRecommendationReason(taskStore.activeDiscussionIndex) }}
	                  </div>
	                </div>
	                <div
	                  v-for="option in (taskStore.discussionQuestions[taskStore.activeDiscussionIndex]?.presetOptions || [])"
	                  :key="option.id"
	                  class="rounded-xl border px-4 py-3 transition-all duration-200"
	                  :class="option.id === taskStore.discussionQuestions[taskStore.activeDiscussionIndex]?.selectedOptionId
	                    ? 'border-blue-400 bg-blue-50/60 shadow-[0_0_0_1px_rgba(59,130,246,0.2)]'
	                    : 'border-slate-200 bg-white/50'"
	                >
	                  <div class="flex items-center gap-2 mb-1.5">
	                    <span
	                      v-if="option.id === taskStore.discussionQuestions[taskStore.activeDiscussionIndex]?.selectedOptionId"
	                      class="rounded-full bg-blue-600 px-2 py-0.5 text-[9px] font-semibold text-white"
	                    >已选</span>
	                    <span
	                      v-if="option.isRecommended"
	                      class="rounded-full bg-amber-500 px-2 py-0.5 text-[9px] font-semibold text-white"
	                    >推荐</span>
	                    <span class="text-sm font-semibold text-slate-800">{{ option.label }}</span>
	                    <span v-if="option.score != null" class="text-[10px] text-slate-400">{{ option.score }}分</span>
	                  </div>
	                  <div class="text-xs text-slate-500 leading-relaxed mb-2">
	                    {{ option.description }}
	                  </div>
	                  <div v-if="option.reason" class="mb-2 text-[11px] leading-relaxed text-slate-600">
	                    {{ option.reason }}
	                  </div>
	                  <div class="grid grid-cols-2 gap-2 text-[10px]">
	                    <div class="rounded-lg bg-green-50 px-2 py-1.5">
	                      <span class="font-medium text-green-700">优势</span>
	                      <div class="text-green-600 mt-0.5">{{ getPros(option) }}</div>
	                    </div>
	                    <div class="rounded-lg bg-red-50 px-2 py-1.5">
	                      <span class="font-medium text-red-700">局限</span>
	                      <div class="text-red-600 mt-0.5">{{ getCons(option) }}</div>
	                    </div>
	                  </div>
	                </div>
	              </div>
	            </ScrollArea>
	          </div>
	        </template>
	        <!-- 建模确认后或无活跃讨论：建模手册 -->
	        <template v-else>
	          <div class="flex h-full flex-col">
	            <div class="glass-header px-4 py-3 flex items-center gap-2">
	              <Lightbulb class="h-4 w-4 text-amber-500" />
	              <h2 class="text-base font-semibold text-slate-800">建模手册</h2>
	            </div>
	            <ScrollArea class="modeler-scroll min-h-0 flex-1">
	              <div class="p-5">
	                <div v-if="modelerBlocks.length" class="space-y-4">
                  <section
                    v-for="block in modelerBlocks"
                    :key="block.key"
                    class="model-card rounded-xl p-4 transition-all duration-200"
                  >
                    <div class="flex items-center gap-2 mb-3">
                      <span class="rounded-full bg-gradient-to-r from-blue-500 to-blue-600 px-2.5 py-1 text-[10px] font-semibold text-white shadow-sm">
                        {{ block.badge }}
                      </span>
                      <h3 class="text-sm font-semibold text-slate-800">
                        {{ block.title }}
                      </h3>
                    </div>
                    <div
                      class="markdown-preview prose prose-slate max-w-none text-sm"
                      v-html="renderedModelerBlocks[block.key] || ''"
                    />
                  </section>
                </div>
                <div v-else class="flex items-center justify-center py-12">
                  <div class="text-center space-y-5 max-w-md px-6 w-full">
                    <div class="inline-flex items-center justify-center">
                      <span class="relative flex h-12 w-12">
                        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-300/60" />
                        <span class="relative inline-flex h-12 w-12 items-center justify-center rounded-full bg-amber-100/80 border border-amber-200">
                          <Lightbulb class="h-5 w-5 text-amber-500 animate-pulse" />
                        </span>
                      </span>
                    </div>
                    <div>
                      <p class="text-sm font-semibold text-slate-700">ModelerAgent 正在生成建模方案</p>
                      <p class="mt-1.5 text-xs text-slate-500 leading-relaxed">各问建模方案已确认，建模手正在结合选定模型生成完整方案，请稍候…</p>
                    </div>
                  </div>
                </div>
              </div>
            </ScrollArea>
          </div>
        </template>
      </ResizablePanel>
    </ResizablePanelGroup>
  </div>
</template>

<style scoped>
/* ====== 面板玻璃风格 ====== */
.glass-panel {
  border: 1px solid rgba(255, 255, 255, 0.25);
  background: rgba(255, 255, 255, 0.45);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  box-shadow:
    0 4px 24px rgba(0, 0, 0, 0.04),
    0 0 0 1px rgba(255, 255, 255, 0.5) inset;
}

.glass-header {
  background: linear-gradient(
    to bottom,
    rgba(255, 255, 255, 0.75),
    rgba(255, 255, 255, 0.4)
  );
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.3);
}

/* ====== 信息卡片 ====== */
.glass-card {
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(255, 255, 255, 0.55);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow:
    0 2px 12px rgba(0, 0, 0, 0.03),
    inset 0 1px 0 rgba(255, 255, 255, 0.5);
  transition: box-shadow 0.3s ease, border-color 0.3s ease;
}

.glass-card:hover {
  border-color: rgba(59, 130, 246, 0.3);
}

/* ====== 问题卡片 ====== */
.question-card {
  border: 1px solid rgba(59, 130, 246, 0.15);
  background: linear-gradient(
    135deg,
    rgba(239, 246, 255, 0.7),
    rgba(255, 255, 255, 0.5)
  );
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}

.question-card:hover {
  border-color: rgba(59, 130, 246, 0.35);
  background: linear-gradient(
    135deg,
    rgba(239, 246, 255, 0.95),
    rgba(255, 255, 255, 0.8)
  );
  box-shadow: 0 0 12px rgba(59, 130, 246, 0.08);
}

.question-number {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: #fff;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.25);
}

/* ====== 建模卡片 ====== */
.model-card {
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(255, 255, 255, 0.5);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow:
    0 2px 12px rgba(0, 0, 0, 0.03),
    inset 0 1px 0 rgba(255, 255, 255, 0.5);
  transition: box-shadow 0.3s ease, border-color 0.3s ease;
}

.model-card:hover {
  border-color: rgba(168, 85, 247, 0.3);
  box-shadow:
    0 4px 20px rgba(0, 0, 0, 0.06),
    inset 0 1px 0 rgba(255, 255, 255, 0.6);
}

/* ====== Markdown 排版 ====== */
.markdown-preview :deep(p) {
  margin: 0.5rem 0;
  line-height: 1.8;
}

.markdown-preview :deep(ul),
.markdown-preview :deep(ol) {
  margin: 0.5rem 0;
  padding-left: 1.25rem;
}

.markdown-preview :deep(ul) {
  list-style: disc;
}

.markdown-preview :deep(ol) {
  list-style: decimal;
}

.markdown-preview :deep(pre) {
  overflow: auto;
  border-radius: 0.5rem;
  background: #f1f5f9;
  padding: 0.75rem 1rem;
  border: 1px solid rgba(226, 232, 240, 0.6);
  font-size: 0.8rem;
  mask-image: linear-gradient(to bottom, #000 80%, transparent 100%);
  -webkit-mask-image: linear-gradient(to bottom, #000 80%, transparent 100%);
}

.markdown-preview :deep(code) {
  font-size: 0.82rem;
}

.markdown-preview :deep(h4) {
  font-size: 0.95rem;
  font-weight: 600;
  margin-top: 1rem;
  color: #334155;
}

.markdown-preview :deep(table) {
  font-size: 0.8rem;
  border-radius: 0.5rem;
  overflow: hidden;
}

.modeler-scroll :deep(.scroll-area-viewport) {
  mask-image: linear-gradient(
    to bottom,
    transparent 0,
    #000 1.25rem,
    #000 calc(100% - 1.25rem),
    transparent 100%
  );
  -webkit-mask-image: linear-gradient(
    to bottom,
    transparent 0,
    #000 1.25rem,
    #000 calc(100% - 1.25rem),
    transparent 100%
  );
}
</style>
