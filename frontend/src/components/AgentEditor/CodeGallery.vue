<script setup lang="ts">
import type { ArtifactCheckRecord } from "@/apis/commonApi";
import { Button } from "@/components/ui/button";
import { useFilePreview } from "@/composables/useFilePreview";
import { useTaskStore } from "@/stores/task";
import type { InterpreterMessage, OutputItem } from "@/utils/response";
import {
	ChevronDown,
	ChevronUp,
	Code2,
	FolderOpen,
	ListTree,
	PanelLeftClose,
	PanelLeftOpen,
} from "lucide-vue-next";
import { computed, nextTick, ref, watch } from "vue";
import { useRoute } from "vue-router";

// ---- Types ----

interface CodeBlock {
	id: string;
	description: string;
	code: string;
	output: OutputItem[] | null;
}

interface CodeFileItem {
	name: string;
	path: string;
	attempt: string;
	passed: boolean;
}

interface CodeFileSection {
	section: string;
	sectionLabel: string;
	files: CodeFileItem[];
}

// ---- State ----

const taskStore = useTaskStore();
const route = useRoute();
const { openPreview, buildFileUrl } = useFilePreview();
const showToc = ref(true);
const activeCodeId = ref<string>("");
const hoveredCodeId = ref<string>("");
/** 展开的代码块 ID 集合，数据刷新不会重置 */
const expandedIds = ref<Set<string>>(new Set());
const codeTocScrollHost = ref<HTMLElement | null>(null);
const codeScrollHost = ref<HTMLElement | null>(null);
const codePanelTab = ref<"blocks" | "files">("blocks");

const currentTaskId = computed(
	() =>
		taskStore.currentTaskId ||
		(typeof route.params.task_id === "string" ? route.params.task_id : "") ||
		window.localStorage.getItem("currentTaskId") ||
		"",
);

// ---- Computed ----

/** 从 interpreterMessage 中提取所有代码块（配对代码消息和结果消息） */
const codeBlocks = computed<CodeBlock[]>(() => {
	const blocks: CodeBlock[] = [];
	const msgs = taskStore.interpreterMessage as InterpreterMessage[];

	for (const im of msgs) {
		if (im.input?.code) {
			blocks.push({
				id: im.id,
				description: im.description || "代码块",
				code: im.input.code,
				output: im.output ?? null,
			});
			continue;
		}

		if (!im.output?.length) continue;
		const pendingBlock = [...blocks]
			.reverse()
			.find((block) => !block.output?.length);
		if (pendingBlock) {
			pendingBlock.output = im.output;
		}
	}

	return blocks;
});

// ---- 代码文件目录（来自 diagnostics） ----

const fileBaseName = (path: string) =>
	path.split(/[\\/]/).filter(Boolean).pop() || path;

const fileDirName = (path: string) => {
	const parts = path.split(/[\\/]/).filter(Boolean);
	return parts.length > 1 ? parts.slice(0, -1).join("/") : "根目录";
};

const cleanSectionLabel = (section: string) => {
	return section
		.replace(/^4\.1_/, "4.1 ")
		.replace(/^5\.(\d+)_/, "5.$1 ")
		.replace(/^6\.1_/, "6.1 ")
		.replace(/_/g, " ");
};

const codeFileSections = computed<CodeFileSection[]>(() => {
	const diagnostics = taskStore.taskDiagnostics;
	const artifactChecks = diagnostics?.artifact_checks ?? {};

	const sectionMap = new Map<string, CodeFileSection>();

	for (const [_phaseKey, attempts] of Object.entries(artifactChecks)) {
		for (const [attemptKey, record] of Object.entries(attempts ?? {})) {
			const typedRecord = record as ArtifactCheckRecord;
			const codeFiles = typedRecord?.code_files ?? [];

			for (const filePath of codeFiles) {
				const section = fileDirName(filePath);
				const fileName = fileBaseName(filePath);

				if (!sectionMap.has(section)) {
					sectionMap.set(section, {
						section,
						sectionLabel: cleanSectionLabel(section),
						files: [],
					});
				}

				const sectionItem = sectionMap.get(section);
				if (!sectionItem) continue;

				// 去重：同一路径只显示一次
				if (sectionItem.files.some((item) => item.path === filePath)) continue;

				sectionItem.files.push({
					name: fileName,
					path: filePath,
					attempt: attemptKey,
					passed: Boolean(typedRecord?.passed),
				});
			}
		}
	}

	const orderWeight = (section: string) => {
		if (section.startsWith("4.1_")) return 10;
		if (section.startsWith("5.")) return 20;
		if (section.startsWith("6.1_")) return 30;
		return 99;
	};

	return Array.from(sectionMap.values())
		.map((section) => ({
			...section,
			files: section.files.sort((a, b) => a.name.localeCompare(b.name)),
		}))
		.sort((a, b) => {
			const w = orderWeight(a.section) - orderWeight(b.section);
			if (w !== 0) return w;
			return a.section.localeCompare(b.section);
		});
});

// ---- Methods ----

function openFilePreview(file: string) {
	const url = buildFileUrl(file, currentTaskId.value);
	const cleanName = file.split(/[?#]/)[0].split(/[\\/]/).pop() || file;
	openPreview(url, cleanName);
}

function blockTitle(block: CodeBlock, index: number): string {
	const phaseMatch = block.description.match(/所属阶段[：:]\s*(.+)/);
	if (phaseMatch) return phaseMatch[1].trim();
	return `Code #${index + 1}`;
}

function blockSummary(block: CodeBlock): string {
	const lines = block.description.split("\n");
	for (const line of lines) {
		const match = line.match(/功能说明[：:]\s*(.+)/);
		if (match) return match[1].trim();
	}
	for (const line of lines) {
		const trimmed = line.trim();
		if (
			trimmed &&
			!trimmed.startsWith("#") &&
			!trimmed.startsWith("- **所属阶段")
		) {
			return trimmed.length > 40 ? `${trimmed.slice(0, 40)}...` : trimmed;
		}
	}
	return "代码块";
}

function renderSimpleMarkdown(text: string): string {
	return text
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
		.replace(/^- (.+)$/gm, "<span class='text-slate-500'>• $1</span>")
		.replace(/\n/g, "<br>");
}

function outputSummary(output: OutputItem[] | null): string {
	if (!output || output.length === 0) return "暂无输出";
	const lines: string[] = [];
	for (const item of output) {
		if (item.res_type === "error") {
			lines.push(`错误: ${item.name}: ${item.value}`);
		} else if (
			item.res_type === "result" &&
			["png", "jpeg", "svg"].includes(item.format || "")
		) {
			lines.push("[图片输出]");
		} else if (item.msg) {
			lines.push(...item.msg.split("\n").slice(0, 5));
		}
		if (lines.length > 8) break;
	}
	return lines.slice(0, 8).join("\n") || "暂无输出";
}

function hasImageOutput(output: OutputItem[] | null): boolean {
	if (!output) return false;
	return output.some(
		(item) =>
			item.res_type === "result" &&
			["png", "jpeg", "svg"].includes(item.format || ""),
	);
}

function isExpanded(id: string): boolean {
	return expandedIds.value.has(id);
}

function toggleExpand(id: string) {
	const next = new Set(expandedIds.value);
	if (next.has(id)) {
		next.delete(id);
	} else {
		next.add(id);
	}
	expandedIds.value = next;
}

/** 代码预览（折叠时显示前 3 行） */
function codePreview(code: string): string {
	const lines = code.split("\n");
	return lines.slice(0, 3).join("\n") + (lines.length > 3 ? "\n..." : "");
}

function scrollToCode(id: string) {
	activeCodeId.value = id;
	keepActiveTocVisible();
	nextTick(() => {
		document
			.getElementById(`code-${id}`)
			?.scrollIntoView({ behavior: "smooth", block: "start" });
	});
}

function keepActiveTocVisible() {
	if (!activeCodeId.value) return;
	nextTick(() => {
		const toc = codeTocScrollHost.value;
		const activeBtn = toc?.querySelector<HTMLElement>(
			`[data-code-id="${CSS.escape(activeCodeId.value)}"]`,
		);
		activeBtn?.scrollIntoView({ behavior: "smooth", block: "nearest" });
	});
}

function updateActiveCode() {
	const container = codeScrollHost.value;
	if (!container) return;
	const cards = Array.from(
		container.querySelectorAll<HTMLElement>("section[id]"),
	);
	if (!cards.length) {
		activeCodeId.value = codeBlocks.value[0]?.id ?? "";
		return;
	}
	const top = container.scrollTop + container.clientHeight * 0.35;
	let current = cards[0]?.id.replace("code-", "") ?? "";
	for (const card of cards) {
		if (card.offsetTop <= top) current = card.id.replace("code-", "");
	}
	activeCodeId.value = current;
}

function bindCodeScroll() {
	requestAnimationFrame(() => {
		const el = codeScrollHost.value;
		if (!el) return;
		el.removeEventListener("scroll", updateActiveCode);
		el.addEventListener("scroll", updateActiveCode, { passive: true });
		updateActiveCode();
	});
}

// ---- Watchers ----

watch(codeBlocks, () => {
	if (
		!activeCodeId.value ||
		!codeBlocks.value.find((b) => b.id === activeCodeId.value)
	) {
		activeCodeId.value = codeBlocks.value[0]?.id ?? "";
	}
	bindCodeScroll();
});
</script>

<template>
  <div class="relative flex h-full min-h-0 bg-white/70 backdrop-blur-sm">
    <!-- 左侧目录 -->
    <aside v-if="showToc" class="w-56 shrink-0 bg-slate-50/90 backdrop-blur-xl">
      <div class="bg-gradient-to-b from-white/70 to-white/35 px-3 py-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.85)] backdrop-blur-md">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2 text-sm font-semibold text-slate-800 min-w-0">
            <ListTree class="h-4 w-4 shrink-0" />
            <span class="bg-gradient-to-b from-slate-900 to-slate-500 bg-clip-text text-transparent truncate">
              {{ codePanelTab === "blocks" ? "代码块目录" : "代码文件目录" }}
            </span>
            <span class="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] text-slate-500 shrink-0">
              {{ codePanelTab === "blocks" ? codeBlocks.length : codeFileSections.reduce((n, s) => n + s.files.length, 0) }}
            </span>
          </div>
          <Button variant="ghost" size="icon" @click="showToc = false">
            <PanelLeftClose class="h-4 w-4" />
          </Button>
        </div>

        <!-- Tab 切换 -->
        <div class="flex rounded-lg bg-slate-100 p-1 text-xs mt-2">
          <button
            class="flex-1 rounded px-2 py-1"
            :class="codePanelTab === 'blocks' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-500'"
            @click="codePanelTab = 'blocks'"
          >
            代码块
          </button>
          <button
            class="flex-1 rounded px-2 py-1"
            :class="codePanelTab === 'files' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-500'"
            @click="codePanelTab = 'files'"
          >
            代码文件
          </button>
        </div>
      </div>

      <!-- 代码块列表 -->
      <div v-if="codePanelTab === 'blocks'" ref="codeTocScrollHost" class="code-toc-scroll h-[calc(100%-85px)] overflow-y-auto overflow-x-hidden">
        <div class="p-2">
          <button
            v-for="(block, idx) in codeBlocks"
            :key="`toc-${block.id}`"
            type="button"
            :data-code-id="block.id"
            class="code-toc-item block w-full rounded px-2 py-1.5 text-left text-xs leading-5 transition-colors"
            :class="activeCodeId === block.id
              ? 'code-toc-item-active bg-blue-100 text-blue-700 ring-1 ring-blue-200'
              : hoveredCodeId === block.id
                ? 'bg-blue-50/80 text-blue-600 ring-1 ring-blue-300/50'
                : 'text-slate-600 hover:bg-white hover:text-blue-600'"
            @click="scrollToCode(block.id)"
          >
            <div class="truncate font-medium">{{ blockTitle(block, idx) }}</div>
            <div class="truncate text-[10px] text-slate-400 mt-0.5">{{ blockSummary(block) }}</div>
          </button>
        </div>
      </div>

      <!-- 代码文件列表 -->
      <div v-else class="h-[calc(100%-85px)] overflow-y-auto overflow-x-hidden">
        <div class="p-2 space-y-3">
          <div
            v-for="section in codeFileSections"
            :key="section.section"
            class="rounded-xl border border-slate-200 bg-white/70 p-2"
          >
            <div class="mb-1 flex items-center gap-1 text-xs font-semibold text-slate-700">
              <FolderOpen class="h-3.5 w-3.5 text-blue-600 shrink-0" />
              <span class="truncate">{{ section.sectionLabel }}</span>
              <span class="ml-auto text-[10px] text-slate-400 shrink-0">
                {{ section.files.length }}
              </span>
            </div>

            <button
              v-for="file in section.files"
              :key="file.path"
              type="button"
              class="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs hover:bg-blue-50"
              @click="openFilePreview(file.path)"
            >
              <Code2 class="h-3.5 w-3.5 shrink-0 text-slate-500" />
              <span class="min-w-0 flex-1 truncate">{{ file.name }}</span>

              <span
                class="rounded px-1.5 py-0.5 text-[10px] shrink-0"
                :class="file.passed ? 'bg-green-50 text-green-700' : 'bg-amber-50 text-amber-700'"
              >
                {{ file.attempt === "main" ? "主力" : file.attempt }}
              </span>
            </button>
          </div>

          <div
            v-if="codeFileSections.length === 0"
            class="rounded-lg border border-dashed border-slate-200 p-3 text-xs text-slate-400"
          >
            暂无代码文件。任务完成后会从 diagnostics 中读取真实保存的 .py 文件。
          </div>
        </div>
      </div>
    </aside>

    <!-- 右侧内容区 -->
    <div class="flex min-w-0 flex-1 flex-col bg-white/80 backdrop-blur-sm">
      <div class="flex items-center justify-between bg-gradient-to-b from-white/72 to-white/42 px-4 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.85)] backdrop-blur-md">
        <div class="flex items-center gap-2">
          <Button v-if="!showToc" variant="ghost" size="icon" @click="showToc = true">
            <PanelLeftOpen class="h-4 w-4" />
          </Button>
          <Code2 class="h-4 w-4 text-slate-600" />
          <h2 class="text-base font-semibold text-gray-900">
            {{ codePanelTab === "blocks" ? "代码结果" : "代码文件目录" }}
          </h2>
          <span v-if="codePanelTab === 'blocks'" class="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">{{ codeBlocks.length }} 段</span>
        </div>
      </div>

      <!-- 代码块详情 -->
      <div v-if="codePanelTab === 'blocks'" ref="codeScrollHost" class="code-content-scroll min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
        <div v-if="codeBlocks.length" class="flex flex-col gap-3 p-4">
          <section
            v-for="(block, idx) in codeBlocks"
            :id="`code-${block.id}`"
            :key="block.id"
            class="code-card flex flex-col rounded-md border bg-white shadow-sm p-4 transition-all duration-300"
            :class="{ 'code-card-hover': hoveredCodeId === block.id }"
            @mouseenter="hoveredCodeId = block.id"
            @mouseleave="hoveredCodeId = ''"
          >
            <!-- 卡片头部：描述 -->
            <div class="mb-3">
              <div class="flex items-center justify-between mb-1">
                <span class="text-xs font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded">
                  {{ blockTitle(block, idx) }}
                </span>
                <span class="text-[10px] text-slate-400">#{{ idx + 1 }}</span>
              </div>
              <div
                class="text-xs leading-5 text-slate-600"
                v-html="renderSimpleMarkdown(block.description)"
              ></div>
            </div>

            <!-- 代码区 -->
            <div class="rounded-lg bg-slate-50 border border-slate-100 overflow-hidden mb-3">
              <div
                class="flex items-center justify-between px-3 py-1.5 bg-slate-100/50 border-b border-slate-100 cursor-pointer select-none"
                @click="toggleExpand(block.id)"
              >
                <span class="text-[10px] font-medium text-slate-500 uppercase tracking-wide">Python</span>
                <span class="inline-flex items-center gap-1 text-[10px] text-slate-400">
                  {{ isExpanded(block.id) ? '折叠' : '展开' }}
                  <ChevronUp v-if="isExpanded(block.id)" class="h-3 w-3" />
                  <ChevronDown v-else class="h-3 w-3" />
                </span>
              </div>
              <!-- 折叠状态：前 3 行 + 渐变遮罩 -->
              <div v-if="!isExpanded(block.id)" class="relative">
                <pre class="p-3 text-xs font-mono text-slate-600 overflow-x-auto whitespace-pre line-clamp-3"><code>{{ codePreview(block.code) }}</code></pre>
                <div class="absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-slate-50 to-transparent pointer-events-none"></div>
              </div>
              <!-- 展开状态：完整代码 -->
              <pre v-else class="p-3 text-xs font-mono text-slate-700 overflow-x-auto whitespace-pre"><code>{{ block.code }}</code></pre>
            </div>

            <!-- 输出结果区 -->
            <div
              v-if="block.output && block.output.length > 0"
              class="rounded-lg border border-slate-100 overflow-hidden"
              :class="hasImageOutput(block.output) ? 'bg-white' : 'bg-gray-50/50'"
            >
              <div class="flex items-center gap-1.5 px-3 py-1.5 bg-slate-50 border-b border-slate-100">
                <span class="text-[10px] font-medium text-slate-500 uppercase tracking-wide">Output</span>
              </div>
              <div v-if="hasImageOutput(block.output)" class="p-3">
                <img
                  v-for="(item, oIdx) in block.output!.filter(
                    (o) => o.res_type === 'result' && ['png', 'jpeg', 'svg'].includes(o.format || '')
                  )"
                  :key="oIdx"
                  :src="`data:image/${item.format};base64,${item.msg}`"
                  class="max-w-full max-h-64 rounded shadow-sm"
                />
              </div>
              <pre
                class="p-3 text-xs font-mono text-slate-600 overflow-x-auto whitespace-pre-wrap max-h-48 overflow-y-auto"
              >{{ outputSummary(block.output) }}</pre>
            </div>

            <div
              v-else
              class="rounded-lg border border-dashed border-slate-200 px-3 py-2 text-[10px] text-slate-400 text-center"
            >
              等待执行结果...
            </div>
          </section>
        </div>
        <div v-else class="glass-card m-4 flex h-56 items-center justify-center text-sm text-slate-500">
          暂无代码执行结果
        </div>
      </div>

      <!-- 代码文件说明 -->
      <div v-else class="flex-1 flex items-center justify-center p-6">
        <div class="rounded-2xl bg-white p-6 text-sm text-slate-600 max-w-md text-center">
          <FolderOpen class="h-10 w-10 mx-auto mb-3 text-blue-400" />
          <div class="mb-2 text-base font-semibold text-slate-900">代码文件目录</div>
          <p>
            这里显示后端实际保存到任务目录中的 Python 文件。点击左侧文件可预览完整内容。
          </p>
          <p class="mt-2 text-xs text-slate-400">
            文件来源：diagnostics.artifact_checks[*].code_files
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
