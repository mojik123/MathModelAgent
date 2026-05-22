<script setup lang="ts">
import * as pdfjsLib from "pdfjs-dist";
import { computed, onBeforeUnmount, ref, watch } from "vue";

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
	"pdfjs-dist/build/pdf.worker.mjs",
	import.meta.url,
).toString();

const props = defineProps<{
	url: string;
	scale: number;
}>();

interface LoadState {
	status: "loading" | "loaded" | "error";
	pageCount: number;
	currentPage: number;
	error?: string;
}

const state = ref<LoadState>({
	status: "loading",
	pageCount: 0,
	currentPage: 1,
});
const canvasRef = ref<HTMLCanvasElement | null>(null);
let pdfDoc: pdfjsLib.PDFDocumentProxy | null = null;
let renderTask: pdfjsLib.RenderTask | null = null;
let aborted = false;

const renderScale = computed(() => props.scale * 1.5);

async function loadPdf() {
	aborted = false;
	state.value = { status: "loading", pageCount: 0, currentPage: 1 };
	try {
		const pdf = await pdfjsLib.getDocument(props.url).promise;
		if (aborted) return;
		pdfDoc = pdf;
		state.value = { status: "loaded", pageCount: pdf.numPages, currentPage: 1 };
		await renderPage(1);
	} catch (err) {
		if (aborted) return;
		state.value = {
			status: "error",
			pageCount: 0,
			currentPage: 1,
			error: err instanceof Error ? err.message : "PDF 加载失败",
		};
	}
}

async function renderPage(pageNum: number) {
	if (!pdfDoc || !canvasRef.value) return;
	if (renderTask) {
		renderTask.cancel();
		renderTask = null;
	}
	const page = await pdfDoc.getPage(pageNum);
	const viewport = page.getViewport({ scale: renderScale.value });
	const canvas = canvasRef.value;
	canvas.width = viewport.width;
	canvas.height = viewport.height;
	const ctx = canvas.getContext("2d");
	if (!ctx) return;

	renderTask = page.render({ canvasContext: ctx, viewport });
	await renderTask.promise;
	renderTask = null;
}

function goToPage(page: number) {
	if (!pdfDoc || page < 1 || page > state.value.pageCount) return;
	state.value.currentPage = page;
	renderPage(page);
}

watch(() => props.url, loadPdf, { immediate: true });

watch(renderScale, () => {
	if (pdfDoc) renderPage(state.value.currentPage);
});

onBeforeUnmount(() => {
	aborted = true;
	if (renderTask) {
		renderTask.cancel();
		renderTask = null;
	}
	if (pdfDoc) {
		pdfDoc.destroy();
		pdfDoc = null;
	}
});
</script>

<template>
	<div class="flex flex-col items-center max-h-full gap-3">
		<div
			v-if="state.status === 'loading'"
			class="flex items-center justify-center h-32 text-white/40 text-sm"
		>
			加载 PDF...
		</div>
		<div
			v-else-if="state.status === 'error'"
			class="flex items-center justify-center h-32 text-red-400 text-sm"
		>
			{{ state.error }}
		</div>
		<template v-else>
			<div class="flex items-center gap-2 text-white text-sm shrink-0">
				<button
					class="px-2 py-1 rounded hover:bg-white/10 disabled:opacity-30 transition-colors"
					:disabled="state.currentPage <= 1"
					@click="goToPage(state.currentPage - 1)"
				>&larr;</button>
				<span class="tabular-nums">
					{{ state.currentPage }} / {{ state.pageCount }}
				</span>
				<button
					class="px-2 py-1 rounded hover:bg-white/10 disabled:opacity-30 transition-colors"
					:disabled="state.currentPage >= state.pageCount"
					@click="goToPage(state.currentPage + 1)"
				>&rarr;</button>
			</div>
			<div class="overflow-auto max-h-[78vh] max-w-full rounded-lg shadow-2xl">
				<canvas ref="canvasRef" class="max-w-full" />
			</div>
		</template>
	</div>
</template>
