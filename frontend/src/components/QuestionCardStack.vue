<script setup lang="ts">
import { Plus, Trash2 } from "lucide-vue-next";
import { nextTick, watch } from "vue";

interface QuestionCardItem {
	questionIndex: number;
	questionTitle: string;
	questionText: string;
	chatHistory: Array<{ role: "user" | "assistant"; content: string }>;
}

const props = defineProps<{
	questions: QuestionCardItem[];
	disabled?: boolean;
}>();

const emit = defineEmits<{
	"update:questions": [questions: QuestionCardItem[]];
}>();

function autoResize(el: HTMLTextAreaElement) {
	el.style.height = "auto";
	el.style.height = `${el.scrollHeight}px`;
}

function handleUpdateText(idx: number, value: string, textarea: HTMLTextAreaElement) {
	const updated = props.questions.map((q, i) =>
		i === idx ? { ...q, questionText: value } : q,
	);
	emit("update:questions", updated);
	nextTick(() => autoResize(textarea));
}

// 初始渲染后自适应高度
watch(
	() => props.questions.length,
	() => nextTick(() => {
		document.querySelectorAll<HTMLTextAreaElement>(".qa-textarea").forEach(autoResize);
	}),
	{ immediate: true },
);

function handleAdd() {
	const nextIndex = props.questions.length + 1;
	emit("update:questions", [
		...props.questions,
		{
			questionIndex: nextIndex,
			questionTitle: `第 ${nextIndex} 问`,
			questionText: "",
			chatHistory: [],
		},
	]);
}

function handleDelete() {
	if (props.questions.length <= 1) return;
	emit("update:questions", props.questions.slice(0, -1));
}
</script>

<template>
	<!-- 无缝衔接的卡片组：外层统一圆角+磨砂玻璃 -->
	<div class="rounded-b-xl border-b border-x border-white/20 bg-white/45 backdrop-blur-sm overflow-hidden">
		<div
			v-for="(q, idx) in questions"
			:key="idx"
			class="flex items-start gap-2.5 px-3 py-2.5"
			:class="{ 'border-t border-white/15': idx > 0 }"
		>
			<span class="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-[10px] font-semibold text-white shadow-sm mt-1">
				Q{{ q.questionIndex }}
			</span>
			<textarea
				:value="q.questionText"
				:class="disabled
								? 'qa-textarea min-w-0 flex-1 resize-none overflow-hidden rounded-lg border border-slate-200/50 bg-slate-50/80 px-2.5 py-1.5 text-xs text-slate-400 cursor-not-allowed placeholder:text-slate-300'
								: 'qa-textarea min-w-0 flex-1 resize-none overflow-hidden rounded-lg border border-slate-200 bg-white/70 px-2.5 py-1.5 text-xs text-slate-700 placeholder:text-slate-400 focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-200'"
				rows="1"
				placeholder="输入问题描述..."
				:disabled="disabled"
				@input="handleUpdateText(idx, ($event.target as HTMLTextAreaElement).value, $event.target as HTMLTextAreaElement)"
			/>
		</div>
	</div>

	<!-- 增删按钮 -->
	<div v-if="!disabled" class="flex items-center gap-2 pt-1.5">
		<button
			class="inline-flex items-center gap-1 rounded-lg border border-dashed border-indigo-300 bg-indigo-50/50 px-3 py-1.5 text-[11px] font-medium text-indigo-600 transition-colors hover:bg-indigo-100"
			@click="handleAdd"
		>
			<Plus class="h-3.5 w-3.5" />
			添加
		</button>
		<button
			class="inline-flex items-center gap-1 rounded-lg border border-dashed border-red-300 bg-red-50/50 px-3 py-1.5 text-[11px] font-medium text-red-600 transition-colors hover:bg-red-100 disabled:opacity-30 disabled:cursor-not-allowed"
			:disabled="questions.length <= 1"
			@click="handleDelete"
		>
			<Trash2 class="h-3.5 w-3.5" />
			删除
		</button>
	</div>
</template>
