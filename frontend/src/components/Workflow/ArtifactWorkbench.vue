<script setup lang="ts">
import { getArtifacts } from "@/apis/workflowApi";
import type { WorkflowArtifact } from "@/apis/workflowApi";
import { compilePdf, getFileDownloadUrl, getPaper, savePaper } from "@/apis/filesApi";
import ArtifactSplitPreview from "@/components/Workflow/ArtifactSplitPreview.vue";
import { useFilePreview } from "@/composables/useFilePreview";
import { Download, FileImage, RefreshCw } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";

const props = defineProps<{
  taskId: string;
  stageId: string;
  refreshKey?: number;
}>();

const emit = defineEmits<{
  (event: "open-paper", payload: { view: "markdown" | "pdf"; artifact: WorkflowArtifact }): void;
}>();

const { openPreview, buildFileUrl } = useFilePreview();
const router = useRouter();
const artifacts = ref<WorkflowArtifact[]>([]);
const selectedImage = ref<WorkflowArtifact | null>(null);
const paperArtifact = ref<WorkflowArtifact | null>(null);
const pdfArtifact = ref<WorkflowArtifact | null>(null);
const pdfFreshness = ref<"not-applicable" | "checking" | "missing-paper" | "missing-pdf" | "current" | "stale" | "unknown">("not-applicable");
const loadState = ref<"loading" | "ready" | "error">("loading");
const loadError = ref("");
const compileError = ref("");
const downloadError = ref("");
const isCompilingPdf = ref(false);
const isDownloadingArtifact = ref("");
let loadSequence = 0;

const isPaperWorkflowStage = computed(() => ["06-paper", "07-compile"].includes(props.stageId));
const pdfFreshnessText = computed(() => {
  const labels = {
    checking: "正在核对 PDF 与论文…",
    "missing-paper": "尚未找到论文 Markdown",
    "missing-pdf": "PDF 尚未生成",
    current: "PDF 与论文同步",
    stale: "PDF 落后于论文",
    unknown: "无法确认 PDF 是否最新",
    "not-applicable": "",
  };
  return labels[pdfFreshness.value];
});
const shouldOfferPdfCompile = computed(
  () =>
    isPaperWorkflowStage.value &&
    Boolean(paperArtifact.value) &&
    ["missing-pdf", "stale", "unknown"].includes(pdfFreshness.value),
);

async function getLastModified(artifact: WorkflowArtifact): Promise<number | null> {
  try {
    const response = await fetch(artifact.preview_url, { method: "HEAD", cache: "no-store" });
    if (!response.ok) return null;
    const value = response.headers.get("last-modified");
    if (!value) return null;
    const timestamp = Date.parse(value);
    return Number.isNaN(timestamp) ? null : timestamp;
  } catch {
    return null;
  }
}

async function loadPaperFreshness(
  currentArtifacts: WorkflowArtifact[],
  sequence: number,
) {
  if (!isPaperWorkflowStage.value) {
    paperArtifact.value = null;
    pdfArtifact.value = null;
    pdfFreshness.value = "not-applicable";
    return;
  }

  pdfFreshness.value = "checking";
  try {
    const relatedStageId = props.stageId === "06-paper" ? "07-compile" : "06-paper";
    const relatedResponse = await getArtifacts(props.taskId, relatedStageId);
    if (sequence !== loadSequence) return;

    const paperFiles = props.stageId === "06-paper" ? currentArtifacts : relatedResponse.data;
    const pdfFiles = props.stageId === "07-compile" ? currentArtifacts : relatedResponse.data;
    paperArtifact.value = paperFiles.find((artifact) => artifact.path.toLowerCase() === "res.md") ?? null;
    pdfArtifact.value = pdfFiles.find((artifact) => artifact.kind === "pdf" && artifact.path.toLowerCase() === "res.pdf") ?? null;

    if (!paperArtifact.value) {
      pdfFreshness.value = "missing-paper";
      return;
    }
    if (!pdfArtifact.value) {
      pdfFreshness.value = "missing-pdf";
      return;
    }

    const [paperModified, pdfModified] = await Promise.all([
      getLastModified(paperArtifact.value),
      getLastModified(pdfArtifact.value),
    ]);
    if (sequence !== loadSequence) return;
    if (paperModified === null || pdfModified === null) {
      pdfFreshness.value = "unknown";
      return;
    }
    pdfFreshness.value = pdfModified > paperModified ? "current" : "stale";
  } catch {
    if (sequence === loadSequence) pdfFreshness.value = "unknown";
  }
}

async function loadArtifacts() {
  const sequence = ++loadSequence;
  artifacts.value = [];
  selectedImage.value = null;
  loadError.value = "";
  loadState.value = "loading";

  try {
    const response = await getArtifacts(props.taskId, props.stageId);
    if (sequence !== loadSequence) return;
    if (!Array.isArray(response.data)) throw new Error("成果列表格式无效");
    artifacts.value = response.data;
    loadState.value = "ready";
    await loadPaperFreshness(response.data, sequence);
  } catch {
    if (sequence !== loadSequence) return;
    loadError.value = "成果列表加载失败，请重试。";
    loadState.value = "error";
  }
}

function kindLabel(kind: WorkflowArtifact["kind"]) {
  const labels: Record<WorkflowArtifact["kind"], string> = {
    image: "图片",
    code: "代码",
    notebook: "Notebook",
    markdown: "Markdown",
    pdf: "PDF",
    data: "数据",
    file: "文件",
  };
  return labels[kind];
}

function openArtifact(artifact: WorkflowArtifact) {
  selectedImage.value = null;

  if (artifact.kind === "image") {
    selectedImage.value = artifact;
    return;
  }

  if (props.stageId === "06-paper" && artifact.path.toLowerCase() === "res.md") {
    emit("open-paper", { view: "markdown", artifact });
    return;
  }

  if (props.stageId === "07-compile" && artifact.kind === "pdf") {
    emit("open-paper", { view: "pdf", artifact });
    return;
  }

  openPreview(buildFileUrl(artifact.path, props.taskId), artifact.filename);
}

async function compilePaperPdf() {
  if (!paperArtifact.value || isCompilingPdf.value) return;
  isCompilingPdf.value = true;
  compileError.value = "";
  try {
    const paperResponse = await getPaper(props.taskId);
    const content = paperResponse.data?.content ?? "";
    if (!content.trim()) throw new Error("论文内容为空，无法编译 PDF。");
    const saveResponse = await savePaper(props.taskId, content);
    if (!saveResponse.data?.success) throw new Error("论文保存失败，PDF 尚未编译。");
    const compileResponse = await compilePdf(props.taskId);
    if (!compileResponse.data?.pdf_url) throw new Error("编译完成，但后端没有返回 PDF 地址。");
    await router.push({
      path: `/task/${props.taskId}/pdf`,
      query: { compiled: "true" },
    });
  } catch (error) {
    const detail = (error as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail
      ?? (error as { message?: string })?.message;
    compileError.value = detail || "PDF 编译失败，请检查论文内容和 LaTeX 工具配置后重试。";
  } finally {
    isCompilingPdf.value = false;
  }
}

async function downloadArtifact(artifact: WorkflowArtifact) {
  if (isDownloadingArtifact.value) return;
  isDownloadingArtifact.value = artifact.path;
  downloadError.value = "";
  try {
    const response = await getFileDownloadUrl(props.taskId, artifact.path);
    const url = response.data?.download_url;
    if (!url) throw new Error("下载接口没有返回文件地址。");
    const link = document.createElement("a");
    link.href = url;
    link.download = artifact.filename;
    link.target = "_blank";
    document.body.appendChild(link);
    link.click();
    link.remove();
  } catch {
    downloadError.value = `无法生成“${artifact.filename}”的下载链接，请重试。`;
  } finally {
    isDownloadingArtifact.value = "";
  }
}

watch(
  () => [props.taskId, props.stageId, props.refreshKey],
  () => void loadArtifacts(),
  { immediate: true },
);
</script>

<template>
  <section aria-labelledby="artifact-workbench-title" class="flex min-h-0 flex-1 flex-col bg-slate-50/70">
    <header class="flex shrink-0 items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3">
      <div class="min-w-0">
        <h3 id="artifact-workbench-title" class="text-sm font-semibold text-slate-900">阶段成果</h3>
        <p class="mt-0.5 text-xs text-slate-500">点击图片查看绘图代码，其他文件使用现有预览器</p>
      </div>
      <span class="shrink-0 text-xs tabular-nums text-slate-400">
        {{ loadState === "ready" ? `${artifacts.length} 项` : "" }}
      </span>
    </header>

    <section
      v-if="isPaperWorkflowStage"
      aria-label="论文与 PDF 状态"
      class="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white px-4 py-2"
    >
      <span role="status" class="text-xs text-slate-600">{{ pdfFreshnessText }}</span>
      <button
        v-if="shouldOfferPdfCompile"
        type="button"
        data-testid="compile-pdf"
        class="inline-flex min-h-8 items-center gap-1.5 rounded-md bg-blue-700 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-700 focus-visible:ring-offset-2 disabled:cursor-wait disabled:opacity-60"
        :disabled="isCompilingPdf"
        @click="compilePaperPdf"
      >
        <RefreshCw v-if="isCompilingPdf" class="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        {{ isCompilingPdf ? "正在编译…" : pdfFreshness === "missing-pdf" ? "编译 PDF" : "重新编译 PDF" }}
      </button>
      <p v-if="compileError" role="alert" class="basis-full text-xs leading-5 text-red-700">
        {{ compileError }}
      </p>
    </section>

    <div class="grid min-h-0 flex-1 gap-3 p-3 md:grid-cols-[minmax(13rem,0.38fr)_minmax(0,1fr)]">
      <div class="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div v-if="loadState === 'loading'" role="status" class="flex flex-1 items-center justify-center gap-2 px-3 text-sm text-slate-500">
          <RefreshCw class="h-4 w-4 animate-spin" aria-hidden="true" />
          正在加载成果…
        </div>
        <div v-else-if="loadState === 'error'" class="flex flex-1 flex-col items-center justify-center gap-2 px-4 text-center">
          <p role="alert" class="text-sm text-red-700">{{ loadError }}</p>
          <button
            type="button"
            class="rounded-md px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
            @click="loadArtifacts"
          >
            重试
          </button>
        </div>
        <div v-else-if="artifacts.length === 0" class="flex flex-1 flex-col items-center justify-center px-5 text-center">
          <FileImage class="mb-3 h-6 w-6 text-slate-300" aria-hidden="true" />
          <p class="text-sm font-medium text-slate-700">此阶段还没有成果文件</p>
          <p class="mt-1 text-xs leading-5 text-slate-500">完成阶段任务后，生成的文件会显示在这里。</p>
        </div>
        <ul v-else class="min-h-0 flex-1 divide-y divide-slate-100 overflow-y-auto">
          <li v-for="artifact in artifacts" :key="artifact.path">
            <div class="flex items-stretch">
              <button
                type="button"
                :data-artifact-path="artifact.path"
                :aria-current="selectedImage?.path === artifact.path ? 'true' : undefined"
                class="min-w-0 flex-1 px-3 py-2.5 text-left transition-colors focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-600"
                :class="selectedImage?.path === artifact.path ? 'bg-blue-50' : 'hover:bg-slate-50'"
                @click="openArtifact(artifact)"
              >
                <span class="flex items-center justify-between gap-3">
                  <span class="truncate text-sm font-medium text-slate-800">{{ artifact.filename }}</span>
                  <span class="shrink-0 text-[10px] text-slate-400">{{ kindLabel(artifact.kind) }}</span>
                </span>
                <span class="mt-1 block truncate text-[11px] text-slate-500">{{ artifact.path }}</span>
              </button>
              <button
                v-if="stageId === '08-final-audit'"
                type="button"
                :aria-label="`下载 ${artifact.filename}`"
                :title="`下载 ${artifact.filename}`"
                :disabled="isDownloadingArtifact === artifact.path"
                class="shrink-0 self-center rounded-md p-2 text-slate-500 hover:bg-slate-100 hover:text-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 disabled:opacity-50"
                @click="downloadArtifact(artifact)"
              >
                <RefreshCw v-if="isDownloadingArtifact === artifact.path" class="h-4 w-4 animate-spin" aria-hidden="true" />
                <Download v-else class="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          </li>
        </ul>
        <p v-if="downloadError" role="alert" class="border-t border-red-100 bg-red-50 px-3 py-2 text-xs text-red-700">
          {{ downloadError }}
        </p>
      </div>

      <div class="flex min-h-0 min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-white">
        <ArtifactSplitPreview
          v-if="selectedImage"
          :key="`${taskId}:${selectedImage.path}`"
          class="p-3"
          :artifact="selectedImage"
          :task-id="taskId"
        />
        <div v-else class="flex flex-1 flex-col items-center justify-center px-6 text-center">
          <p class="text-sm font-medium text-slate-700">选择一项成果</p>
          <p class="mt-1 text-xs leading-5 text-slate-500">图片会在此处与对应源代码并排显示。</p>
        </div>
      </div>
    </div>
  </section>
</template>
