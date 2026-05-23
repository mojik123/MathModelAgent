<script setup lang="ts">
import type { ArtifactCheckRecord } from "@/apis/commonApi";
import { getFiles } from "@/apis/filesApi";
import { Button } from "@/components/ui/button";
import { useFilePreview } from "@/composables/useFilePreview";
import { useTaskStore } from "@/stores/task";
import {
	Code2,
	FolderOpen,
	ListTree,
	PanelLeftClose,
	PanelLeftOpen,
	RefreshCw,
} from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

// ---- Types ----

interface WorkspaceFile {
	filename: string;
	file_type?: string;
	name?: string;
	type?: string;
	size?: number;
	modified_time?: string | number | Date;
}

interface CodeFileItem {
	name: string;
	path: string;
	attempt: string;
	passed: boolean;
	description: string;
	size?: number;
	modifiedTime?: string | number | Date;
}

interface CodeFileSection {
	section: string;
	sectionLabel: string;
	files: CodeFileItem[];
}

// ---- State ----

	const props = defineProps<{
		task_id: string;
		refreshKey?: number;
	}>();

const taskStore = useTaskStore();
const route = useRoute();
const { openPreview, buildFileUrl } = useFilePreview();
const showToc = ref(true);
const selectedFilePath = ref("");
const workspaceFiles = ref<WorkspaceFile[]>([]);
const loadingFiles = ref(false);

const currentTaskId = computed(
	() =>
		props.task_id ||
		taskStore.currentTaskId ||
		(typeof route.params.task_id === "string" ? route.params.task_id : "") ||
		window.localStorage.getItem("currentTaskId") ||
		"",
);

// ---- Path helpers ----

const normalizePath = (path: string) =>
	(path || "").replace(/\\/g, "/").replace(/^\.?\//, "").trim();

const fileBaseName = (path: string) =>
	normalizePath(path).split("/").filter(Boolean).pop() || path;

const fileDirName = (path: string) => {
	const parts = normalizePath(path).split("/").filter(Boolean);
	return parts.length > 1 ? parts.slice(0, -1).join("/") : "根目录";
};

const isPythonFile = (path: string) => /\.py$/i.test(path);

const cleanSectionLabel = (section: string) => {
	if (section === "根目录") return "根目录";
	return section
		.replace(/^4\.1_/, "4.1 ")
		.replace(/^4\.2_/, "4.2 ")
		.replace(/^5\.(\d+)_/, "5.$1 ")
		.replace(/^6\.1_/, "6.1 ")
		.replace(/_/g, " ");
};

// ---- Fixed description (not AI) ----

function getCodeFileDescription(filePath: string): string {
	const name = fileBaseName(filePath).toLowerCase();
	const dir = fileDirName(filePath);

	if (name === "code.py" || /^code_(?:b\d+|r\d+)\.py$/i.test(name)) {
		return "本章节完整 Python 汇总代码，包含该部分主要数据处理、建模、求解和绘图流程。";
	}
	if (/_step_\d+\.py$/i.test(name)) {
		return "该步骤保存的完整 Python 文件，可用于查看对应步骤的执行逻辑。";
	}
	if (name.includes("prediction") || name.includes("predict")) {
		return "预测结果相关 Python 文件，包含模型预测、结果整理或预测图生成代码。";
	}
	if (name.includes("sensitivity")) {
		return "灵敏度分析相关 Python 文件，包含参数扰动、指标对比或稳健性检验代码。";
	}
	if (name.includes("diagnostic") || name.includes("residual")) {
		return "模型诊断相关 Python 文件，包含误差分析、残差分析或模型检验图生成代码。";
	}
	if (name.includes("distribution") || name.includes("eda")) {
		return "描述性统计或数据探索相关 Python 文件，包含数据分布、统计特征或可视化代码。";
	}

	if (dir.startsWith("5.")) {
		return "该子问题模型建立与求解阶段保存的完整 Python 文件。";
	}
	if (dir.startsWith("6.1")) {
		return "模型分析与检验阶段保存的完整 Python 文件。";
	}

	return "任务生成的完整 Python 文件，可打开查看源码。";
}

// ---- Workspace file loading ----

async function loadWorkspaceFiles() {
	if (!currentTaskId.value) return;
	loadingFiles.value = true;
	try {
		const res = await getFiles(currentTaskId.value);
		workspaceFiles.value = (res.data ?? []).map(
			(f: Record<string, unknown>) => ({
				filename: (f.filename ?? f.name ?? "") as string,
				file_type: (f.file_type ?? f.type ?? "") as string,
				size: f.size as number | undefined,
				modified_time: f.modified_time as string | number | Date | undefined,
			}),
		);
	} finally {
		loadingFiles.value = false;
	}
}

// ---- Computed code file sections ----

const diagnosticMetaByPath = computed(() => {
	const map = new Map<string, { attempt: string; passed: boolean }>();
	const artifactChecks = taskStore.taskDiagnostics?.artifact_checks ?? {};

	for (const [_phaseKey, attempts] of Object.entries(artifactChecks)) {
		for (const [attemptKey, record] of Object.entries(attempts ?? {})) {
			const typedRecord = record as ArtifactCheckRecord;
			for (const filePath of typedRecord?.code_files ?? []) {
				map.set(normalizePath(filePath), {
					attempt: attemptKey,
					passed: Boolean(typedRecord?.passed),
				});
			}
		}
	}

	return map;
});

const codeFileSections = computed<CodeFileSection[]>(() => {
	const sectionMap = new Map<string, CodeFileSection>();
	const fileMap = new Map<string, CodeFileItem>();

	// 1. diagnostics 里的 code_files
	for (const [filePath, meta] of diagnosticMetaByPath.value.entries()) {
		if (!isPythonFile(filePath)) continue;
		fileMap.set(filePath, {
			name: fileBaseName(filePath),
			path: filePath,
			attempt: meta.attempt,
			passed: meta.passed,
			description: getCodeFileDescription(filePath),
		});
	}

	// 2. /files 接口补齐所有 .py
	for (const f of workspaceFiles.value) {
		const filePath = normalizePath(f.filename || f.name || "");
		if (!filePath || !isPythonFile(filePath)) continue;
		if (fileMap.has(filePath)) continue;

		const meta = diagnosticMetaByPath.value.get(filePath);
		fileMap.set(filePath, {
			name: fileBaseName(filePath),
			path: filePath,
			attempt: meta?.attempt ?? "workspace",
			passed: meta?.passed ?? true,
			description: getCodeFileDescription(filePath),
			size: f.size,
			modifiedTime: f.modified_time,
		});
	}

	for (const file of fileMap.values()) {
		const section = fileDirName(file.path);
		if (!sectionMap.has(section)) {
			sectionMap.set(section, {
				section,
				sectionLabel: cleanSectionLabel(section),
				files: [],
			});
		}
		sectionMap.get(section)?.files.push(file);
	}

	const orderWeight = (section: string) => {
		if (section === "根目录") return 0;
		if (section.startsWith("4.")) return 10;
		if (section.startsWith("5.")) return 20;
		if (section.startsWith("6.1")) return 30;
		return 99;
	};

	return Array.from(sectionMap.values())
		.map((section) => ({
			...section,
			files: section.files.sort((a, b) =>
				a.name.localeCompare(b.name, undefined, { numeric: true }),
			),
		}))
		.sort((a, b) => {
			const w = orderWeight(a.section) - orderWeight(b.section);
			if (w !== 0) return w;
			return a.section.localeCompare(b.section, undefined, { numeric: true });
		});
});

// ---- Selection ----

const selectedFile = computed(() => {
	for (const section of codeFileSections.value) {
		const found = section.files.find(
			(file) => file.path === selectedFilePath.value,
		);
		if (found) return found;
	}
	return codeFileSections.value[0]?.files[0] ?? null;
});

function selectFile(file: CodeFileItem) {
	selectedFilePath.value = file.path;
}

function openFilePreview(file: string) {
	const url = buildFileUrl(file, currentTaskId.value);
	const cleanName = file.split(/[?#]/)[0].split(/[\\/]/).pop() || file;
	openPreview(url, cleanName);
}

watch(codeFileSections, (sections) => {
	if (
		!selectedFilePath.value ||
		!sections.some((section) =>
			section.files.some((file) => file.path === selectedFilePath.value),
		)
	) {
		selectedFilePath.value = sections[0]?.files[0]?.path ?? "";
	}
});

// ---- Lifecycle ----

watch(
	() => [currentTaskId.value, props.refreshKey],
	() => {
		void loadWorkspaceFiles();
	},
	{ immediate: true },
);

onMounted(() => {
	void loadWorkspaceFiles();
});
</script>

<template>
	<div class="relative flex h-full min-h-0 bg-white/70 backdrop-blur-sm">
		<!-- 左侧 Python 文件树 -->
		<aside
			v-if="showToc"
			class="w-64 shrink-0 bg-slate-50/90 backdrop-blur-xl"
		>
			<div class="bg-gradient-to-b from-white/70 to-white/35 px-3 py-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.85)] backdrop-blur-md">
				<div class="flex items-center justify-between">
					<div class="flex min-w-0 items-center gap-2 text-sm font-semibold text-slate-800">
						<ListTree class="h-4 w-4 shrink-0" />
						<span class="truncate">Python 文件目录</span>
						<span class="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] text-slate-500 shrink-0">
							{{ codeFileSections.reduce((n, s) => n + s.files.length, 0) }}
						</span>
					</div>
					<Button variant="ghost" size="icon" @click="showToc = false">
						<PanelLeftClose class="h-4 w-4" />
					</Button>
				</div>
			</div>

			<div class="h-[calc(100%-44px)] overflow-y-auto overflow-x-hidden">
				<div v-if="loadingFiles" class="p-3 text-xs text-slate-400">
					<RefreshCw class="mr-1 inline h-3.5 w-3.5 animate-spin" />
					加载 Python 文件...
				</div>

				<div v-else class="p-2 space-y-3">
					<div
						v-for="section in codeFileSections"
						:key="section.section"
						class="rounded-xl border border-slate-200 bg-white/70 p-2"
					>
						<div class="mb-1 flex items-center gap-1 text-xs font-semibold text-slate-700">
							<FolderOpen class="h-3.5 w-3.5 shrink-0 text-blue-600" />
							<span class="truncate">{{ section.sectionLabel }}</span>
							<span class="ml-auto shrink-0 text-[10px] text-slate-400">
								{{ section.files.length }}
							</span>
						</div>

						<button
							v-for="file in section.files"
							:key="file.path"
							type="button"
							class="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-xs hover:bg-blue-50"
							:class="selectedFilePath === file.path ? 'bg-blue-50 ring-1 ring-blue-200' : ''"
							@click="selectFile(file)"
						>
							<Code2 class="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" />
							<div class="min-w-0 flex-1">
								<div class="truncate font-medium text-slate-700">
									{{ file.name }}
								</div>
								<div class="line-clamp-2 text-[10px] leading-4 text-slate-400">
									{{ file.description }}
								</div>
							</div>
						</button>
					</div>

					<div
						v-if="codeFileSections.length === 0 && !loadingFiles"
						class="rounded-lg border border-dashed border-slate-200 p-3 text-xs text-slate-400"
					>
						暂无 Python 文件。任务执行后会从工作区文件列表和 diagnostics 中读取真实保存的 .py 文件。
					</div>
				</div>
			</div>
		</aside>

		<!-- 右侧文件说明 + 预览入口 -->
		<div class="flex min-w-0 flex-1 flex-col bg-white/80 backdrop-blur-sm">
			<div class="flex items-center justify-between bg-gradient-to-b from-white/72 to-white/42 px-4 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.85)] backdrop-blur-md">
				<div class="flex items-center gap-2">
					<Button
						v-if="!showToc"
						variant="ghost"
						size="icon"
						@click="showToc = true"
					>
						<PanelLeftOpen class="h-4 w-4" />
					</Button>
					<Code2 class="h-4 w-4 text-slate-600" />
					<h2 class="text-base font-semibold text-gray-900">
						Python 文件
					</h2>
				</div>
			</div>

			<div class="flex-1 overflow-y-auto p-6">
				<div
					v-if="selectedFile"
					class="mx-auto max-w-2xl rounded-2xl bg-white p-6 shadow-sm border border-slate-100"
				>
					<div class="mb-4 flex items-start gap-3">
						<div class="rounded-xl bg-blue-50 p-2">
							<Code2 class="h-5 w-5 text-blue-600" />
						</div>
						<div class="min-w-0 flex-1">
							<div class="truncate text-lg font-semibold text-slate-900">
								{{ selectedFile.name }}
							</div>
							<div class="mt-1 break-all text-xs text-slate-400">
								{{ selectedFile.path }}
							</div>
						</div>
					</div>

					<div class="rounded-xl border border-slate-100 bg-slate-50 p-4 text-sm leading-6 text-slate-600">
						{{ selectedFile.description }}
					</div>

					<div class="mt-4 flex items-center gap-2 text-xs text-slate-500">
						<span class="rounded-full bg-slate-100 px-2 py-1">
							来源：{{
								selectedFile.attempt === "workspace"
									? "工作区文件"
									: selectedFile.attempt === "main"
										? "主力"
										: selectedFile.attempt
							}}
						</span>
						<span
							class="rounded-full px-2 py-1"
							:class="
								selectedFile.passed
									? 'bg-green-50 text-green-700'
									: 'bg-amber-50 text-amber-700'
							"
						>
							{{
								selectedFile.passed
									? "已通过产物检查"
									: "未通过或未检查"
							}}
						</span>
					</div>

					<div class="mt-5">
						<Button @click="openFilePreview(selectedFile.path)">
							打开完整 Python 文件
						</Button>
					</div>
				</div>

				<div
					v-else
					class="flex h-56 items-center justify-center text-sm text-slate-500"
				>
					暂无 Python 文件
				</div>
			</div>
		</div>
	</div>
</template>
