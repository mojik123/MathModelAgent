<script setup lang="ts">
import { useFilePreview } from "@/composables/useFilePreview";
import type {
	CodeCell,
	DescriptionCell,
	NoteCell,
	ResultCell,
} from "@/utils/interface";
import { renderMarkdown } from "@/utils/markdown";
import type { CodeExecutionResult } from "@/utils/response";
import { computed } from "vue";

const { openPreview, base64ToBlobUrl } = useFilePreview();

// ---- Props ----

const props = defineProps<{
	cell: NoteCell;
	collapsed: boolean;
}>();

const emit = defineEmits<{
	toggle: [];
}>();

// ---- Computed ----

/** 代码预览文本（折叠时显示前 3 行） */
const codePreview = computed(() => {
	if (!isCodeCell(props.cell)) return "";
	const lines = props.cell.content.split("\n");
	return lines.slice(0, 3).join("\n") + (lines.length > 3 ? "\n..." : "");
});

/** 结果预览文本（折叠时显示摘要） */
const resultPreview = computed(() => {
	if (!isResultCell(props.cell)) return "";
	const results = props.cell.code_results;
	if (results.length === 0) return "(空输出)";

	const lines: string[] = [];
	for (const r of results) {
		if (r.res_type === "stdout" || r.res_type === "stderr") {
			lines.push(...(r.msg || "").split("\n"));
		} else if (r.res_type === "error") {
			lines.push(`${r.name}: ${r.value}`);
		} else if (r.res_type === "result") {
			if (["png", "jpeg", "svg"].includes(r.format || "")) {
				lines.push("[图片输出]");
			} else {
				lines.push(...(r.msg || "").split("\n"));
			}
		}
		if (lines.length > 3) break;
	}
	const preview = lines.slice(0, 3).join("\n");
	const totalLines = lines.length;
	return preview + (totalLines > 3 ? "\n..." : "");
});

// ---- Methods ----

/** 获取结果格式对应的 CSS 类 */
const getResultClass = (result: CodeExecutionResult) => {
	switch (result.res_type) {
		case "stdout":
			return "text-gray-600";
		case "stderr":
			return "text-orange-600";
		case "error":
			return "text-red-600";
		default:
			return "text-gray-800";
	}
};

/** 判断结果是否为图片格式 */
const isImageResult = (result: CodeExecutionResult) => {
	return (
		result.res_type === "result" &&
		["png", "jpeg", "svg"].includes(result.format as string)
	);
};

/** 判断结果是否为 LaTeX 格式 */
const isLatexResult = (result: CodeExecutionResult) => {
	return result.res_type === "result" && result.format === "latex";
};

/** 判断结果是否为 JSON 格式 */
const isJsonResult = (result: CodeExecutionResult) => {
	return result.res_type === "result" && result.format === "json";
};

/** 格式化 JSON 显示 */
const formatJson = (jsonString: string) => {
	try {
		const parsed = JSON.parse(jsonString);
		return JSON.stringify(parsed, null, 2);
	} catch (e) {
		return jsonString;
	}
};

/** 渲染 Markdown 内容 */
const renderMarkdownContent = (content: string) => {
	return renderMarkdown(content);
};

/** 类型守卫：判断是否为介绍单元格 */
const isDescriptionCell = (cell: NoteCell): cell is DescriptionCell => {
	return cell.type === "description";
};

/** 类型守卫：判断是否为代码单元格 */
const isCodeCell = (cell: NoteCell): cell is CodeCell => {
	return cell.type === "code";
};

/** 类型守卫：判断是否为结果单元格 */
const isResultCell = (cell: NoteCell): cell is ResultCell => {
	return cell.type === "result";
};
</script>

<template>
  <div
    :class="[
      'notebook-cell overflow-hidden',
      cell.type === 'description' ? 'description-cell' : '',
      cell.type === 'code' ? 'code-cell' : '',
      cell.type === 'result' ? 'result-cell' : '',
    ]"
  >
    <!-- 单元格头部 -->
    <div
      class="cell-header px-3 py-1.5 flex items-center justify-between border-b cursor-pointer"
      :class="cell.type === 'description' ? 'border-purple-100/50' : 'border-white/20'"
      @click="cell.type !== 'description' && emit('toggle')"
    >
      <div class="flex items-center space-x-2">
        <span
          :class="[
            'px-2 py-1 rounded text-xs font-medium',
            cell.type === 'description'
              ? 'bg-purple-50 text-purple-600'
              : cell.type === 'code'
                ? 'bg-blue-50 text-blue-600'
                : 'bg-green-50 text-green-600',
          ]"
        >
          {{ cell.type === 'description' ? '介绍' : cell.type === 'code' ? 'Code' : 'Result' }}
        </span>
        <!-- 折叠/展开指示器 -->
        <span
          v-if="cell.type !== 'description'"
          class="text-xs text-gray-400 transition-transform duration-200"
          :class="collapsed ? '' : 'rotate-90'"
        >
          &#9654;
        </span>
      </div>
      <!-- 折叠状态标签 -->
      <span
        v-if="cell.type !== 'description'"
        class="text-xs text-gray-400"
      >
        {{ collapsed ? '点击展开' : '点击折叠' }}
      </span>
    </div>

    <!-- 介绍单元格（始终展开） -->
    <template v-if="isDescriptionCell(cell)">
      <div class="p-4 bg-purple-50/30">
        <div
          class="prose prose-sm max-w-none text-gray-700"
          v-html="renderMarkdownContent(cell.content)"
        ></div>
      </div>
    </template>

    <!-- 代码单元格 -->
    <template v-else-if="isCodeCell(cell)">
      <div class="relative">
        <!-- 折叠状态 -->
        <div v-if="collapsed" class="p-4 font-mono relative group bg-gray-50">
          <pre class="text-sm overflow-x-auto line-clamp-3"><code>{{ codePreview }}</code></pre>
          <div
            class="absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-gray-50 to-transparent pointer-events-none"
          ></div>
        </div>
        <!-- 展开状态 -->
        <div v-else class="p-4 font-mono relative group">
          <pre class="text-sm overflow-x-auto"><code>{{ cell.content }}</code></pre>
        </div>
      </div>
    </template>

    <!-- 结果单元格 -->
    <template v-else-if="isResultCell(cell)">
      <!-- 折叠状态 -->
      <div v-if="collapsed" class="px-4 py-3 bg-gray-50">
        <div class="text-xs font-medium text-gray-500 mb-1">输出预览:</div>
        <div class="font-mono whitespace-pre-wrap text-sm text-gray-500 line-clamp-3">
          {{ resultPreview }}
        </div>
      </div>
      <!-- 展开状态 -->
      <div v-else class="px-4 py-3 bg-gray-50">
        <div class="text-xs font-medium text-gray-500 mb-2">输出:</div>

        <!-- 遍历所有执行结果 -->
        <div v-for="(result, index) in cell.code_results" :key="index" class="mb-2 last:mb-0">
          <!-- 标准输出/错误 -->
          <template v-if="result.res_type === 'stdout' || result.res_type === 'stderr'">
            <div :class="['font-mono whitespace-pre-wrap text-sm', getResultClass(result)]">
              {{ result.msg }}
            </div>
          </template>

          <!-- 执行错误 -->
          <template v-else-if="result.res_type === 'error'">
            <div class="text-sm text-red-600 font-mono whitespace-pre-wrap">
              <div class="font-bold">{{ result.name }}: {{ result.value }}</div>
              <div>{{ result.traceback }}</div>
            </div>
          </template>

          <!-- 执行结果 - 图片 (PNG, JPEG, SVG) -->
          <template v-else-if="isImageResult(result)">
            <img
              :src="`data:image/${result.format};base64,${result.msg}`"
              class="max-w-full rounded-lg shadow-sm cursor-pointer hover:opacity-80 transition-opacity"
              @click="openPreview(base64ToBlobUrl(result.msg!, `image/${result.format}`), `output.${result.format}`)"
            />
          </template>

          <!-- 执行结果 - HTML -->
          <template v-else-if="result.res_type === 'result' && result.format === 'html'">
            <div class="prose prose-sm max-w-none" v-html="result.msg || ''"></div>
          </template>

          <!-- 执行结果 - Markdown -->
          <template v-else-if="result.res_type === 'result' && result.format === 'markdown'">
            <div class="prose prose-sm max-w-none" v-html="renderMarkdownContent(result.msg || '')"></div>
          </template>

          <!-- 执行结果 - LaTeX -->
          <template v-else-if="isLatexResult(result)">
            <div class="katex-display" v-html="result.msg || ''"></div>
          </template>

          <!-- 执行结果 - JSON -->
          <template v-else-if="isJsonResult(result)">
            <pre class="text-sm bg-gray-50 p-2 rounded overflow-x-auto">{{ formatJson(result.msg || '') }}</pre>
          </template>

          <!-- 执行结果 - 默认文本 -->
          <template v-else>
            <div class="text-sm text-gray-600 font-mono whitespace-pre-wrap">
              {{ result.msg }}
            </div>
          </template>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* ====== 单元格卡片玻璃风格 ====== */
.notebook-cell {
  border-radius: 0.75rem;
  border: 1px solid rgba(255, 255, 255, 0.25);
  background: rgba(255, 255, 255, 0.4);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  box-shadow:
    0 4px 24px rgba(0, 0, 0, 0.04),
    0 0 0 1px rgba(255, 255, 255, 0.5) inset;
  transition: box-shadow 0.3s ease, border-color 0.3s ease;
}

.notebook-cell:hover {
  border-color: rgba(59, 130, 246, 0.45);
}

.cell-header {
  background: linear-gradient(to bottom, rgba(255, 255, 255, 0.7), rgba(255, 255, 255, 0.35));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

/* 代码样式 */
.code-cell pre {
  background-color: rgb(249 250 251);
  border-radius: 0.375rem;
  padding: 0.5rem;
}

.code-cell code {
  color: rgb(31 41 55);
}

/* 描述单元格 */
.description-cell {
  border-color: rgba(168, 85, 247, 0.2);
}

.description-cell:hover {
  border-color: rgba(168, 85, 247, 0.4);
}

/* 结果样式 */
.result-cell {
  margin-top: -0.25rem;
  border-top-left-radius: 0;
  border-top-right-radius: 0;
}

/* 3 行截断 */
.line-clamp-3 {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
