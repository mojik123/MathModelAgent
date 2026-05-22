<script setup lang="ts">
import { Button } from "@/components/ui/button";
import { Download, File } from "lucide-vue-next";

defineProps<{
	fileName: string;
	url: string;
	sizeBytes?: number;
}>();

function formatSize(bytes?: number): string {
	if (!bytes) return "";
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
</script>

<template>
	<div class="flex flex-col items-center gap-4 select-none">
		<div
			class="flex items-center justify-center w-24 h-24 rounded-2xl bg-white/10"
		>
			<File class="h-12 w-12 text-white/40" />
		</div>
		<div class="text-center">
			<p class="text-white text-lg font-medium">{{ fileName }}</p>
			<p class="text-white/40 text-sm mt-1">
				{{ formatSize(sizeBytes) || "未知大小" }}
			</p>
			<p class="text-white/30 text-xs mt-2">此文件格式暂不支持预览</p>
		</div>
		<a :href="url" :download="fileName">
			<Button variant="secondary" class="gap-2">
				<Download class="h-4 w-4" />
				下载文件
			</Button>
		</a>
	</div>
</template>
