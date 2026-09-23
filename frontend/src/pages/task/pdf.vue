<script setup lang="ts">
import { compilePdf, getPaper, savePaper } from "@/apis/filesApi";
import { getArtifacts } from "@/apis/workflowApi";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Download, RefreshCw } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();
const taskId = computed(() => route.params.task_id as string);
const loading = ref(false);
const errorMessage = ref("");
const pdfUrl = ref("");
const hasCompiled = ref(false);

async function compileAndPreview() {
	loading.value = true;
	errorMessage.value = "";
	try {
		const paper = await getPaper(taskId.value);
		const content = paper.data?.content ?? "";
		if (!content.trim()) throw new Error("论文内容为空，无法编译 PDF。");
		const saved = await savePaper(taskId.value, content);
		if (!saved.data?.success) throw new Error("论文保存失败，PDF 尚未编译。");
		const res = await compilePdf(taskId.value);
		pdfUrl.value = addCacheBuster(res.data.pdf_url);
		hasCompiled.value = true;
	} catch (error) {
		console.error("PDF 编译失败:", error);
		const detail =
			(error as { response?: { data?: { detail?: string } } })?.response?.data
				?.detail ?? "";
		errorMessage.value = detail
			? `PDF 编译失败:
${detail}`
			: "PDF 编译失败。请确认后端已安装 xelatex 和 pandoc，或检查论文中的 LaTeX 语法。";
	} finally {
		loading.value = false;
	}
}

function addCacheBuster(url: string) {
	const separator = url.includes("?") ? "&" : "?";
	return `${url}${separator}t=${Date.now()}`;
}

async function loadCompiledPdf() {
	loading.value = true;
	errorMessage.value = "";
	try {
		const response = await getArtifacts(taskId.value, "07-compile");
		const artifact = response.data.find(
			(item) => item.kind === "pdf" && item.path.toLowerCase() === "res.pdf",
		);
		if (!artifact) throw new Error("编译接口已返回，但任务目录中没有找到 res.pdf。");
		pdfUrl.value = addCacheBuster(artifact.preview_url);
		hasCompiled.value = true;
	} catch (error) {
		const detail =
			(error as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail ??
			(error as { message?: string })?.message;
		errorMessage.value = detail || "无法读取刚编译的 PDF，请返回工作区重试。";
	} finally {
		loading.value = false;
	}
}

function downloadPdf() {
	if (!pdfUrl.value) return;
	const link = document.createElement("a");
	link.href = pdfUrl.value;
	link.download = "res.pdf";
	link.target = "_blank";
	document.body.appendChild(link);
	link.click();
	link.remove();
}

onMounted(() => {
	if (route.query.compiled === "true") {
		void loadCompiledPdf();
		return;
	}
	void compileAndPreview();
});
</script>

<template>
  <div class="flex h-screen flex-col bg-slate-100">
    <header class="flex items-center justify-between border-b bg-white/75 px-4 py-3 backdrop-blur-md">
      <div class="flex items-center gap-3">
        <Button variant="ghost" size="icon" @click="router.push(`/task/${taskId}`)">
          <ArrowLeft class="h-4 w-4" />
        </Button>
        <div>
          <div class="text-base font-semibold text-slate-900">PDF 编译预览</div>
          <div class="text-xs text-slate-500">只有进入这个页面才会编译 PDF，修改 Markdown 不会自动编译</div>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <Button variant="outline" :disabled="loading" @click="compileAndPreview">
          <RefreshCw class="mr-1 h-4 w-4" :class="{ 'animate-spin': loading }" />
          重新编译
        </Button>
        <Button :disabled="!pdfUrl || loading" @click="downloadPdf">
          <Download class="mr-1 h-4 w-4" />
          下载 PDF
        </Button>
      </div>
    </header>
    <main class="pdf-preview-shell min-h-0 flex-1 p-4">
      <div v-if="loading" class="flex h-full items-center justify-center rounded-md bg-white/72 text-slate-500 backdrop-blur-md">
        <RefreshCw class="mr-2 h-5 w-5 animate-spin" />正在编译 PDF...
      </div>
      <div v-else-if="errorMessage" class="flex h-full items-center justify-center rounded-md bg-white/72 text-red-600 backdrop-blur-md">{{ errorMessage }}</div>
      <iframe v-else-if="pdfUrl" :src="pdfUrl" class="h-full w-full rounded-md border bg-white/72 backdrop-blur-md" title="PDF 预览" />
      <div v-else class="flex h-full items-center justify-center rounded-md bg-white/72 text-slate-500 backdrop-blur-md">暂无 PDF</div>
    </main>
  </div>
</template>

<style scoped>
.pdf-preview-shell {
  background: rgba(241, 245, 249, 0.68);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}
</style>
