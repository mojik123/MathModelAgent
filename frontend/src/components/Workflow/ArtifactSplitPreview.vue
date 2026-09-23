<script setup lang="ts">
import { getImageCode } from "@/apis/filesApi";
import type { WorkflowArtifact } from "@/apis/workflowApi";
import { useFilePreview } from "@/composables/useFilePreview";
import { computed, onBeforeUnmount, ref, watch } from "vue";

const props = defineProps<{
  artifact: WorkflowArtifact;
  taskId: string;
}>();

const { buildFileUrl } = useFilePreview();
const sourceCode = ref<string | null>(null);
const sourceLoading = ref(false);
const sourceError = ref("");
let loadSequence = 0;

const imageUrl = computed(() => buildFileUrl(props.artifact.path, props.taskId));
const sourcePath = computed(() => props.artifact.source_path ?? "");
const sourceUrl = computed(() =>
  sourcePath.value ? buildFileUrl(sourcePath.value, props.taskId) : "",
);
const sourceTitle = computed(() => {
  const displayPath = sourcePath.value || "对应绘图代码";
  return displayPath.split(/[\\/]/).pop() || displayPath;
});

async function loadSourceCode() {
  const sequence = ++loadSequence;
  sourceCode.value = null;
  sourceError.value = "";
  sourceLoading.value = true;

  try {
    let apiCode = "";
    try {
      const response = await getImageCode(props.taskId, props.artifact.path);
      if (sequence !== loadSequence) return;
      apiCode = response.data?.found ? response.data.code?.trim() ?? "" : "";
      if (apiCode) sourceCode.value = response.data.code ?? "";
    } catch (error) {
      if (!sourceUrl.value) throw error;
    }

    if (apiCode) {
      return;
    }

    if (!sourceUrl.value) return;
    const sourceResponse = await fetch(sourceUrl.value);
    if (!sourceResponse.ok) throw new Error(`HTTP ${sourceResponse.status}`);
    const text = await sourceResponse.text();
    if (sequence === loadSequence) sourceCode.value = text.trim() ? text : null;
  } catch {
    if (sequence === loadSequence) sourceError.value = "源代码暂时无法读取，请稍后重试。";
  } finally {
    if (sequence === loadSequence) sourceLoading.value = false;
  }
}

watch(
  () => [props.taskId, props.artifact.path, props.artifact.source_path],
  () => void loadSourceCode(),
  { immediate: true },
);

onBeforeUnmount(() => {
  loadSequence += 1;
});
</script>

<template>
  <section class="grid min-h-0 min-w-0 flex-1 gap-3 md:grid-cols-2" aria-label="图片与源代码">
    <div class="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white">
      <div class="border-b border-slate-100 px-3 py-2">
        <h4 class="truncate text-xs font-medium text-slate-700">{{ artifact.filename }}</h4>
      </div>
      <div class="flex min-h-48 flex-1 items-center justify-center overflow-hidden bg-slate-50 p-3">
        <img :src="imageUrl" :alt="artifact.filename" class="max-h-full max-w-full object-contain" />
      </div>
    </div>

    <div class="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white">
      <div class="flex items-center justify-between gap-3 border-b border-slate-100 px-3 py-2">
        <h4 class="text-xs font-medium text-slate-700">图片源代码</h4>
        <span class="truncate text-[11px] text-slate-400">{{ sourceTitle }}</span>
      </div>
      <div class="min-h-48 flex-1 overflow-auto bg-slate-950 p-3 text-xs leading-5 text-slate-100">
        <p v-if="sourceLoading" role="status" class="text-slate-400">正在查找对应代码…</p>
        <p v-else-if="sourceError" role="alert" class="text-amber-300">{{ sourceError }}</p>
        <pre v-else-if="sourceCode" class="whitespace-pre-wrap break-words"><code>{{ sourceCode }}</code></pre>
        <p v-else role="status" class="text-slate-400">未找到源代码。可检查同名代码文件或 Notebook。</p>
      </div>
    </div>
  </section>
</template>
