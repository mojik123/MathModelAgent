<script setup lang="ts">
import NotebookCell from "@/components/NotebookCell.vue";
import { useTaskStore } from "@/stores/task";
import type {
	CodeCell,
	DescriptionCell,
	NoteCell,
	ResultCell,
} from "@/utils/interface";
import { computed, ref, watch } from "vue";

// ---- Reactive State ----

const taskStore = useTaskStore();

/** 每个单元格的折叠状态（key 为单元格索引） */
const collapsedState = ref<Record<number, boolean>>({});

/** 当消息变化时，新单元格默认折叠 */
watch(
	() => taskStore.interpreterMessage.length,
	() => {
		// 新消息到来时不重置已有状态，新单元格索引在 computed 中处理
	},
);

// ---- Computed ----

/** 将代码执行消息转换为 Notebook 单元格列表 */
const cells = computed<NoteCell[]>(() => {
	const notebookCells: NoteCell[] = [];

	for (const toolMsg of taskStore.interpreterMessage) {
		// 代码介绍（description）→ 插入在代码单元格之前
		if (toolMsg.description && toolMsg.input?.code) {
			const descCell: DescriptionCell = {
				type: "description",
				content: toolMsg.description,
			};
			notebookCells.push(descCell);
		}

		// 处理代码输入消息
		if (toolMsg.input?.code) {
			const codeCell: CodeCell = {
				type: "code",
				content: toolMsg.input.code,
			};
			notebookCells.push(codeCell);
		}

		// 处理执行结果消息
		if (toolMsg.output && toolMsg.output.length > 0) {
			const resultCell: ResultCell = {
				type: "result",
				code_results: toolMsg.output,
			};
			notebookCells.push(resultCell);
		}
	}

	return notebookCells;
});

// ---- Methods ----

/** 获取单元格的折叠状态，新单元格默认折叠（除 description 外） */
function isCollapsed(index: number, cellType: string): boolean {
	if (cellType === "description") return false;
	if (collapsedState.value[index] !== undefined) {
		return collapsedState.value[index];
	}
	// 默认折叠
	collapsedState.value[index] = true;
	return true;
}

/** 切换折叠状态 */
function toggleCollapse(index: number) {
	collapsedState.value[index] = !collapsedState.value[index];
}
</script>

<template>
  <div class="notebook-scroll flex-1 px-1 pt-1 pb-4 h-full overflow-y-auto">
    <!-- 遍历所有单元格 -->
    <div
      v-for="(cell, index) in cells"
      :key="index"
      :class="[
        'transform transition-all duration-200 hover:shadow-lg',
        cell.type === 'code' ? 'pt-2' : 'pt-0',
      ]"
    >
      <NotebookCell
        :cell="cell"
        :collapsed="isCollapsed(index, cell.type)"
        @toggle="toggleCollapse(index)"
      />
    </div>

    <!-- 无内容时的提示 -->
    <div v-if="cells.length === 0" class="flex items-center justify-center h-full">
      <div class="text-gray-400 text-center p-8">
        <div class="text-4xl mb-2">📝</div>
        <div class="text-lg font-medium">暂无代码执行结果</div>
        <div class="text-sm">执行代码后将在此显示结果</div>
      </div>
    </div>
    <!-- 添加底部空间 -->
    <div class="h-4"></div>
  </div>
</template>

<style>
.notebook-scroll {
  mask-image: linear-gradient(
    to bottom,
    transparent 0,
    #000 1.25rem,
    #000 calc(100% - 1.25rem),
    transparent 100%
  );
  -webkit-mask-image: linear-gradient(
    to bottom,
    transparent 0,
    #000 1.25rem,
    #000 calc(100% - 1.25rem),
    transparent 100%
  );
}

/* 自定义滚动条 */
::-webkit-scrollbar {
  width: 0.375rem;
  height: 0.375rem;
}

::-webkit-scrollbar-track {
  background-color: rgb(243 244 246);
  border-radius: 9999px;
}

::-webkit-scrollbar-thumb {
  background-color: rgb(209 213 219);
  border-radius: 9999px;
}

::-webkit-scrollbar-thumb:hover {
  background-color: rgb(156 163 175);
  transition-property: background-color;
  transition-duration: 200ms;
}

/* 代码高亮样式 */
.hljs {
  background-color: rgb(249 250 251);
  padding: 1rem;
  border-radius: 0.5rem;
  margin-top: 0.5rem;
  margin-bottom: 0.5rem;
}

/* 数学公式样式 */
.katex-display {
  margin-top: 1rem;
  margin-bottom: 1rem;
  overflow-x: auto;
}

.katex {
  font-size: 1rem;
}
</style>
