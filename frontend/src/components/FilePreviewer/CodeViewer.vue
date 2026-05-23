<script setup lang="ts">
import hljs from "highlight.js";
import { computed, onBeforeUnmount, ref, watch } from "vue";

const props = defineProps<{
	url: string;
	fileName: string;
	scale: number;
}>();

interface LoadState {
	status: "loading" | "loaded" | "error";
	content: string;
	language: string;
	error?: string;
}

const state = ref<LoadState>({ status: "loading", content: "", language: "" });

const fontSize = computed(() => `${Math.max(0.5, props.scale) * 0.8125}rem`);

// ---- 根据扩展名推断语言 ID ----

const extToLang: Record<string, string> = {
	py: "python",
	ts: "typescript",
	tsx: "typescript",
	js: "javascript",
	jsx: "javascript",
	vue: "xml",
	json: "json",
	tex: "latex",
	yaml: "yaml",
	yml: "yaml",
	toml: "ini",
	cfg: "ini",
	ini: "ini",
	sh: "bash",
	r: "r",
	R: "r",
	java: "java",
	cpp: "cpp",
	c: "c",
	h: "c",
	css: "css",
	scss: "scss",
	html: "xml",
	xml: "xml",
	sql: "sql",
	bib: "tex",
	ipynb: "json",
};

const fileMode = computed(() => {
	if (props.fileName.endsWith(".ipynb")) return "notebook";
	const ext = props.fileName.split(".").pop()?.toLowerCase() ?? "";
	return extToLang[ext] || "plaintext";
});

let controller: AbortController | null = null;

async function load() {
	controller?.abort();
	controller = new AbortController();
	const { signal } = controller;

	state.value = { status: "loading", content: "", language: "" };
	try {
		const res = await fetch(props.url, { signal });
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		let text = await res.text();

		if (fileMode.value === "notebook") {
			try {
				const nb = JSON.parse(text);
				const cells: string[] = [];
				for (const cell of nb.cells || []) {
					if (cell.source) {
						const src = Array.isArray(cell.source)
							? cell.source.join("")
							: cell.source;
						if (cell.cell_type === "code") {
							cells.push(src.trimEnd());
						} else if (cell.cell_type === "markdown") {
							for (const line of src.split("\n")) {
								cells.push(line.startsWith("#") ? line : `# ${line}`);
							}
						}
					}
				}
				text = cells.join("\n\n");
			} catch {
				// 解析失败就原样显示
			}
		}

		if (signal.aborted) return;
		const lang =
			fileMode.value === "notebook"
				? "python"
				: extToLang[props.fileName.split(".").pop()?.toLowerCase() ?? ""] ||
					"plaintext";
		const highlighted =
			lang !== "plaintext" && hljs.getLanguage(lang)
				? hljs.highlight(text, { language: lang }).value
				: text
						.replace(/&/g, "&amp;")
						.replace(/</g, "&lt;")
						.replace(/>/g, "&gt;");

		if (signal.aborted) return;
		state.value = { status: "loaded", content: highlighted, language: lang };
	} catch (err) {
		if (signal.aborted) return;
		state.value = {
			status: "error",
			content: "",
			language: "",
			error: err instanceof Error ? err.message : "加载失败",
		};
	}
}

watch(() => props.url, load, { immediate: true });

onBeforeUnmount(() => {
	controller?.abort();
});
</script>

<template>
	<div class="w-full max-w-5xl max-h-full overflow-auto rounded-lg bg-[#1e1e2e] shadow-2xl">
		<div v-if="state.status === 'loading'" class="flex items-center justify-center h-32 text-white/40 text-sm">
			加载中...
		</div>
		<div v-else-if="state.status === 'error'" class="flex items-center justify-center h-32 text-red-400 text-sm">
			{{ state.error }}
		</div>
		<pre v-else class="p-6 overflow-auto max-h-[85vh] leading-relaxed" :style="{ fontSize }"><code class="hljs" v-html="state.content" /></pre>
	</div>
</template>

<style scoped>
pre {
	margin: 0;
	tab-size: 4;
	white-space: pre;
	font-family: "Cascadia Code", "Fira Code", "JetBrains Mono", ui-monospace, monospace;
}
</style>
