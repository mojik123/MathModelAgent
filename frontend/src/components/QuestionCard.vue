<script setup lang="ts">
import { nextTick, ref } from "vue";

// ---- Props ----

interface Props {
	questionIndex: number;
	questionText: string;
	disabled?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
	disabled: false,
});

const emit = defineEmits<{
	"update:text": [value: string];
}>();

// ---- Auto-resize ----

const textareaRef = ref<HTMLTextAreaElement | null>(null);

function autoResize() {
	nextTick(() => {
		const el = textareaRef.value;
		if (!el) return;
		el.style.height = "auto";
		el.style.height = `${el.scrollHeight}px`;
	});
}

function handleInput(e: Event) {
	if (props.disabled) return;
	emit("update:text", (e.target as HTMLTextAreaElement).value);
	autoResize();
}
</script>

<template>
	<div class="flex items-start gap-2.5 rounded-xl border border-white/20 bg-white/45 backdrop-blur-sm px-3 py-2.5 transition-all duration-200">
		<span
			class="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-[10px] font-semibold text-white shadow-sm mt-1"
		>
			Q{{ questionIndex }}
		</span>
		<textarea
			ref="textareaRef"
			:value="questionText"
			class="min-w-0 flex-1 resize-none overflow-hidden rounded-lg border border-slate-200 bg-white/70 px-2.5 py-1.5 text-xs text-slate-700 placeholder:text-slate-400 focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-200"
			rows="1"
			placeholder="输入问题描述..."
			:disabled="disabled"
			@input="handleInput"
		/>
	</div>
</template>
