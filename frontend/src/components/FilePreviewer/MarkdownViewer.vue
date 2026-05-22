<script setup lang="ts">
import { marked } from "marked";
import { computed, onBeforeUnmount, ref, watch } from "vue";

const props = defineProps<{
	url: string;
	scale: number;
}>();

interface LoadState {
	status: "loading" | "loaded" | "error";
	html: string;
	error?: string;
}

const state = ref<LoadState>({ status: "loading", html: "" });

const fontSize = computed(() => `${Math.max(0.5, props.scale) * 0.875}rem`);

let aborted = false;

async function load() {
	state.value = { status: "loading", html: "" };
	aborted = false;
	try {
		const res = await fetch(props.url);
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		const text = await res.text();
		if (aborted) return;
		const html = await marked.parse(text, { breaks: true, gfm: true });
		if (aborted) return;
		state.value = { status: "loaded", html };
	} catch (err) {
		if (aborted) return;
		state.value = {
			status: "error",
			html: "",
			error: err instanceof Error ? err.message : "加载失败",
		};
	}
}

watch(() => props.url, load, { immediate: true });

onBeforeUnmount(() => {
	aborted = true;
});
</script>

<template>
	<div
		class="w-full max-w-4xl max-h-full overflow-auto rounded-lg bg-[#1e1e2e] text-white/90 shadow-2xl p-8"
		:style="{ fontSize }"
	>
		<div v-if="state.status === 'loading'" class="flex items-center justify-center h-32 text-white/40 text-sm">
			加载中...
		</div>
		<div v-else-if="state.status === 'error'" class="flex items-center justify-center h-32 text-red-400 text-sm">
			{{ state.error }}
		</div>
		<div v-else class="prose prose-invert max-w-none" v-html="state.html" />
	</div>
</template>
