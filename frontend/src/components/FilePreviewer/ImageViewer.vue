<script setup lang="ts">
import { Button } from "@/components/ui/button";
import { useFilePreview } from "@/composables/useFilePreview";
import { ZoomIn } from "lucide-vue-next";
import { onBeforeUnmount, ref, watch } from "vue";

const props = defineProps<{
	url: string;
	scale: number;
}>();

const { zoomIn, resetZoom } = useFilePreview();

// ---- 拖拽平移 ----

const imgRef = ref<HTMLImageElement | null>(null);
const translateX = ref(0);
const translateY = ref(0);
const isDragging = ref(false);
const dragStart = ref({ x: 0, y: 0 });
const posStart = ref({ x: 0, y: 0 });
const hasMoved = ref(false);

function onMouseDown(e: MouseEvent) {
	if (props.scale <= 1) return;
	isDragging.value = true;
	hasMoved.value = false;
	dragStart.value = { x: e.clientX, y: e.clientY };
	posStart.value = { x: translateX.value, y: translateY.value };
	e.preventDefault();
}

function onMouseMove(e: MouseEvent) {
	if (!isDragging.value) return;
	const dx = e.clientX - dragStart.value.x;
	const dy = e.clientY - dragStart.value.y;
	if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
		hasMoved.value = true;
	}
	translateX.value = posStart.value.x + dx;
	translateY.value = posStart.value.y + dy;
}

function onMouseUp() {
	isDragging.value = false;
}

/** 点击图片切换缩放：fit ↔ 放大 */
function onClick() {
	if (hasMoved.value) return;
	if (props.scale <= 1) {
		zoomIn();
		zoomIn();
	} else {
		resetZoom();
	}
}

// 缩放变化时重置平移
watch(
	() => props.scale,
	() => {
		if (props.scale <= 1) {
			translateX.value = 0;
			translateY.value = 0;
		}
	},
);

onBeforeUnmount(() => {
	document.removeEventListener("mousemove", onMouseMove);
	document.removeEventListener("mouseup", onMouseUp);
});

document.addEventListener("mousemove", onMouseMove);
document.addEventListener("mouseup", onMouseUp);
</script>

<template>
	<div class="relative flex items-center justify-center max-w-full max-h-full overflow-hidden group">
		<button
			type="button"
			class="absolute left-3 bottom-3 z-10 inline-flex items-center gap-1 rounded-full bg-black/55 px-3 py-1.5 text-xs font-medium text-white opacity-0 shadow-lg backdrop-blur transition hover:bg-black/70 group-hover:opacity-100 focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-white/50"
			title="放大预览"
			aria-label="放大预览"
			@click.stop="zoomIn"
		>
			<ZoomIn class="h-3.5 w-3.5" />
			放大
		</button>

		<img
			ref="imgRef"
			:src="url"
			:alt="'preview'"
			:style="{
				transform: `scale(${scale}) translate(${translateX / scale}px, ${translateY / scale}px)`,
				cursor: scale > 1 ? (isDragging ? 'grabbing' : 'grab') : 'zoom-in',
			}"
			class="max-w-[85vw] max-h-[85vh] object-contain rounded-lg shadow-2xl transition-transform duration-150 select-none"
			draggable="false"
			@click="onClick"
			@mousedown="onMouseDown"
		/>
	</div>
</template>
