<script setup lang="ts">
import { Button } from "@/components/ui/button";
import { useFilePreview } from "@/composables/useFilePreview";
import { Download, RotateCw, X, ZoomIn, ZoomOut } from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted } from "vue";
import CodeViewer from "./CodeViewer.vue";
import CsvViewer from "./CsvViewer.vue";
import ImageViewer from "./ImageViewer.vue";
import MarkdownViewer from "./MarkdownViewer.vue";
import PdfViewer from "./PdfViewer.vue";
import UnsupportedViewer from "./UnsupportedViewer.vue";

const {
	isOpen,
	fileUrl,
	fileName,
	format,
	scale,
	closePreview,
	zoomIn,
	zoomOut,
	resetZoom,
} = useFilePreview();

const scalePercent = computed(() => `${Math.round(scale.value * 100)}%`);

const isImage = computed(() => format.value === "image");

// ---- 键盘事件 ----

function onKeydown(e: KeyboardEvent) {
	if (!isOpen.value) return;
	if (e.key === "Escape") {
		closePreview();
		return;
	}
	if (e.ctrlKey || e.metaKey) {
		if (e.key === "=" || e.key === "+") {
			e.preventDefault();
			zoomIn();
		} else if (e.key === "-") {
			e.preventDefault();
			zoomOut();
		} else if (e.key === "0") {
			e.preventDefault();
			resetZoom();
		}
	}
}

onMounted(() => window.addEventListener("keydown", onKeydown));
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown));

// ---- 下载 ----

function handleDownload() {
	const a = document.createElement("a");
	a.href = fileUrl.value;
	a.download = fileName.value;
	a.click();
}
</script>

<template>
	<Teleport to="body">
		<Transition name="preview-fade">
			<div
				v-if="isOpen"
				class="fixed inset-0 z-[120] flex flex-col bg-black/80 backdrop-blur-sm"
				@click.self="closePreview"
				@wheel.prevent="
					($event.ctrlKey || $event.metaKey) && isImage
						? $event.deltaY < 0
							? zoomIn()
							: zoomOut()
						: undefined
				"
			>
				<!-- 工具栏 -->
				<div
					class="flex items-center justify-between px-4 py-2 bg-black/60 text-white shrink-0 select-none"
				>
					<div class="flex items-center gap-3 min-w-0">
						<span class="text-sm font-medium truncate max-w-[400px]">{{ fileName }}</span>
						<span class="text-xs text-white/50 hidden sm:inline">{{ format.toUpperCase() }}</span>
					</div>

					<div class="flex items-center gap-1">
						<Button
							variant="ghost"
							size="icon"
							class="h-8 w-8 text-white/80 hover:text-white hover:bg-white/10"
							title="缩小 (Ctrl+-)"
							@click="zoomOut"
						>
							<ZoomOut class="h-4 w-4" />
						</Button>
						<span
							class="text-xs text-white/60 w-12 text-center tabular-nums cursor-pointer hover:text-white"
							title="重置缩放 (Ctrl+0)"
							@click="resetZoom"
						>{{ scalePercent }}</span>
						<Button
							variant="ghost"
							size="icon"
							class="h-8 w-8 text-white/80 hover:text-white hover:bg-white/10"
							title="放大 (Ctrl++)"
							@click="zoomIn"
						>
							<ZoomIn class="h-4 w-4" />
						</Button>
						<Button
							variant="ghost"
							size="icon"
							class="h-8 w-8 text-white/80 hover:text-white hover:bg-white/10"
							title="重置 (Ctrl+0)"
							@click="resetZoom"
						>
							<RotateCw class="h-4 w-4" />
						</Button>
						<div class="w-px h-5 bg-white/20 mx-1" />
						<Button
							variant="ghost"
							size="icon"
							class="h-8 w-8 text-white/80 hover:text-white hover:bg-white/10"
							title="下载"
							@click="handleDownload"
						>
							<Download class="h-4 w-4" />
						</Button>
						<Button
							variant="ghost"
							size="icon"
							class="h-8 w-8 text-white/80 hover:text-white hover:bg-white/10"
							title="关闭 (Esc)"
							@click="closePreview"
						>
							<X class="h-5 w-5" />
						</Button>
					</div>
				</div>

				<!-- 内容区 -->
				<div class="flex-1 flex items-center justify-center overflow-hidden p-4">
					<ImageViewer
						v-if="format === 'image'"
						:url="fileUrl"
						:scale="scale"
					/>
					<CodeViewer
						v-else-if="format === 'code'"
						:url="fileUrl"
						:file-name="fileName"
						:scale="scale"
					/>
					<CsvViewer
						v-else-if="format === 'csv'"
						:url="fileUrl"
						:file-name="fileName"
						:scale="scale"
					/>
					<PdfViewer
						v-else-if="format === 'pdf'"
						:url="fileUrl"
						:scale="scale"
					/>
					<MarkdownViewer
						v-else-if="format === 'markdown'"
						:url="fileUrl"
						:scale="scale"
					/>
					<UnsupportedViewer
						v-else
						:file-name="fileName"
						:url="fileUrl"
						:size-bytes="sizeBytes"
					/>
				</div>

				<!-- 底部提示 -->
				<div class="text-center py-1.5 text-[11px] text-white/30 shrink-0 select-none">
					Esc 关闭 &middot; Ctrl+滚轮 缩放 &middot; Ctrl+0 重置
				</div>
			</div>
		</Transition>
	</Teleport>
</template>

<style scoped>
.preview-fade-enter-active {
	transition: opacity 0.25s ease;
}
.preview-fade-leave-active {
	transition: opacity 0.2s ease;
}
.preview-fade-enter-from,
.preview-fade-leave-to {
	opacity: 0;
}
</style>
