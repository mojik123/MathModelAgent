<script setup lang="ts">
import type { ArtifactCheckRecord } from "@/apis/commonApi";
import { getFiles } from "@/apis/filesApi";
import { Button } from "@/components/ui/button";
import { useFilePreview } from "@/composables/useFilePreview";
import { useTaskStore } from "@/stores/task";
import {
	ChevronsDown,
	ChevronsUp,
	Code2,
	ExternalLink,
	FolderOpen,
	ListTree,
	PanelLeftClose,
	PanelLeftOpen,
	RefreshCw,
} from "lucide-vue-next";
import {
	computed,
	nextTick,
	onBeforeUnmount,
	onMounted,
	ref,
	watch,
} from "vue";
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
const fileContentCache = ref<Record<string, string>>({});
const loadingCodeFiles = ref<Set<string>>(new Set());
const codeFileErrors = ref<Record<string, string>>({});
const expandedCodeFiles = ref<Set<string>>(new Set());
const highlightedFilePath = ref("");
const codeScrollHost = ref<HTMLElement | null>(null);
let workspaceSyncTimer: ReturnType<typeof setTimeout> | null = null;
let workspaceSyncInFlight = false;
let codeScrollFrame: number | null = null;

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
	(path || "")
		.replace(/\\/g, "/")
		.replace(/^\.?\//, "")
		.trim();

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

function workspaceFilesSignature(files: WorkspaceFile[]) {
	return files
		.map((file) => {
			const modifiedTime =
				file.modified_time instanceof Date
					? file.modified_time.toISOString()
					: String(file.modified_time ?? "");
			return [
				normalizePath(file.filename || file.name || ""),
				String(file.size ?? ""),
				modifiedTime,
			].join(":");
		})
		.sort()
		.join("|");
}

async function loadWorkspaceFiles(options: { background?: boolean } = {}) {
	if (!currentTaskId.value) return;
	if (workspaceSyncInFlight) return;

	workspaceSyncInFlight = true;
	if (!options.background) loadingFiles.value = true;
	try {
		const res = await getFiles(currentTaskId.value);
		const nextFiles = (res.data ?? []).map((f) => ({
			filename: f.filename ?? f.name ?? "",
			file_type: f.file_type ?? f.type ?? "",
			size: f.size,
			modified_time: f.modified_time,
		}));
		if (
			workspaceFilesSignature(nextFiles) !==
			workspaceFilesSignature(workspaceFiles.value)
		) {
			workspaceFiles.value = nextFiles;
		}
	} finally {
		workspaceSyncInFlight = false;
		if (!options.background) loadingFiles.value = false;
	}
}

function scheduleWorkspaceSync() {
	if (workspaceSyncTimer) return;
	workspaceSyncTimer = setTimeout(() => {
		workspaceSyncTimer = null;
		void loadWorkspaceFiles({ background: true });
	}, 1000);
}

async function refreshCodeFiles() {
	fileContentCache.value = {};
	loadingCodeFiles.value = new Set();
	codeFileErrors.value = {};
	await loadWorkspaceFiles();
	for (const section of codeFileSections.value) {
		for (const file of section.files) void loadCodeFileContent(file.path);
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

function selectFile(file: CodeFileItem) {
	selectedFilePath.value = file.path;
	void loadCodeFileContent(file.path);
	nextTick(() => {
		const card = codeScrollHost.value?.querySelector<HTMLElement>(
			`[data-code-card-path="${CSS.escape(file.path)}"]`,
		);
		card?.scrollIntoView({ behavior: "smooth", block: "start" });
	});
}

function openFilePreview(file: string) {
	const url = buildFileUrl(file, currentTaskId.value);
	const cleanName = file.split(/[?#]/)[0].split(/[\\/]/).pop() || file;
	openPreview(url, cleanName);
}

async function loadCodeFileContent(filePath: string) {
	if (!filePath || !currentTaskId.value) return;
	if (Object.hasOwn(fileContentCache.value, filePath)) return;
	if (loadingCodeFiles.value.has(filePath)) return;

	const nextLoading = new Set(loadingCodeFiles.value);
	nextLoading.add(filePath);
	loadingCodeFiles.value = nextLoading;
	const nextErrors = { ...codeFileErrors.value };
	delete nextErrors[filePath];
	codeFileErrors.value = nextErrors;
	try {
		const url = buildFileUrl(filePath, currentTaskId.value);
		const res = await fetch(url);
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		const text = await res.text();
		fileContentCache.value = { ...fileContentCache.value, [filePath]: text };
	} catch (e: unknown) {
		codeFileErrors.value = {
			...codeFileErrors.value,
			[filePath]: e instanceof Error ? e.message : "读取 Python 文件失败",
		};
	} finally {
		const finishedLoading = new Set(loadingCodeFiles.value);
		finishedLoading.delete(filePath);
		loadingCodeFiles.value = finishedLoading;
	}
}

const rxNewline = /\r?\n/;
function codeFileContent(filePath: string) {
	return fileContentCache.value[filePath] ?? "";
}

function codeFileLines(filePath: string) {
	const content = codeFileContent(filePath);
	return content ? content.split(rxNewline) : [];
}

function codeFileLineCount(filePath: string) {
	return codeFileLines(filePath).length;
}

function isCodeFileExpanded(filePath: string) {
	return expandedCodeFiles.value.has(filePath);
}

function codeFileDisplayedContent(filePath: string) {
	const content = codeFileContent(filePath);
	return isCodeFileExpanded(filePath)
		? content
		: codeFileLines(filePath).slice(0, 10).join("\n");
}

function codeFileHasMoreThan10Lines(filePath: string) {
	return codeFileLineCount(filePath) > 10;
}

function toggleCodeFileExpanded(filePath: string) {
	const next = new Set(expandedCodeFiles.value);
	next.has(filePath) ? next.delete(filePath) : next.add(filePath);
	expandedCodeFiles.value = next;
}

function keepActiveCodeTocVisible() {
	if (!selectedFilePath.value) return;
	nextTick(() => {
		document
			.querySelector<HTMLElement>(
				`[data-code-toc-path="${CSS.escape(selectedFilePath.value)}"]`,
			)
			?.scrollIntoView({ behavior: "smooth", block: "nearest" });
	});
}

function updateActiveCodeFile() {
	const container = codeScrollHost.value;
	if (!container) return;
	const cards = Array.from(
		container.querySelectorAll<HTMLElement>("[data-code-card-path]"),
	);
	if (!cards.length) return;

	const focusLine =
		container.getBoundingClientRect().top + container.clientHeight * 0.3;
	let activeCard = cards[0];
	for (const card of cards) {
		if (card.getBoundingClientRect().top > focusLine) break;
		activeCard = card;
	}
	const nextPath = activeCard?.dataset.codeCardPath ?? "";
	if (nextPath && nextPath !== selectedFilePath.value) {
		selectedFilePath.value = nextPath;
		keepActiveCodeTocVisible();
	}
}

function handleCodeScroll() {
	if (codeScrollFrame !== null) return;
	codeScrollFrame = window.requestAnimationFrame(() => {
		codeScrollFrame = null;
		updateActiveCodeFile();
	});
}

function bindCodeScroll() {
	nextTick(() => {
		const container = codeScrollHost.value;
		if (!container) return;
		container.removeEventListener("scroll", handleCodeScroll);
		container.addEventListener("scroll", handleCodeScroll, {
			passive: true,
		});
		updateActiveCodeFile();
	});
}

function locateCodeFile(filePath: string) {
	const normalized = normalizePath(filePath);
	const base = fileBaseName(normalized);
	const target = codeFileSections.value
		.flatMap((section) => section.files)
		.find(
			(file) =>
				normalizePath(file.path) === normalized ||
				fileBaseName(file.path) === base,
		);
	if (!target) return;
	showToc.value = true;
	selectFile(target);
	highlightedFilePath.value = target.path;
	nextTick(() => {
		const card = codeScrollHost.value?.querySelector<HTMLElement>(
			`[data-code-card-path="${CSS.escape(target.path)}"]`,
		);
		card?.focus({ preventScroll: true });
	});
	setTimeout(() => {
		if (highlightedFilePath.value === target.path)
			highlightedFilePath.value = "";
	}, 2600);
}

function handleChatArtifactOpen(event: Event) {
	const detail = (event as CustomEvent).detail as {
		file?: string;
		type?: string;
	};
	if (detail?.type !== "code" || !detail.file) return;
	locateCodeFile(detail.file);
}

const codeFilePathSignature = computed(() =>
	codeFileSections.value
		.flatMap((section) => section.files)
		.map((file) => file.path)
		.join("|"),
);

watch(codeFilePathSignature, () => {
	const files = codeFileSections.value.flatMap((section) => section.files);
	if (
		!selectedFilePath.value ||
		!files.some((file) => file.path === selectedFilePath.value)
	) {
		selectedFilePath.value = files[0]?.path ?? "";
	}
	for (const file of files) void loadCodeFileContent(file.path);
	bindCodeScroll();
});

// ---- Lifecycle ----

watch(
	currentTaskId,
	() => {
		if (workspaceSyncTimer) {
			clearTimeout(workspaceSyncTimer);
			workspaceSyncTimer = null;
		}
		workspaceFiles.value = [];
		fileContentCache.value = {};
		expandedCodeFiles.value = new Set();
		loadingCodeFiles.value = new Set();
		codeFileErrors.value = {};
		void loadWorkspaceFiles();
	},
	{ immediate: true },
);

watch(
	() => props.refreshKey,
	() => {
		scheduleWorkspaceSync();
	},
);

onMounted(() => {
	window.addEventListener("chat-artifact-open", handleChatArtifactOpen);
	bindCodeScroll();
});

onBeforeUnmount(() => {
	if (workspaceSyncTimer) clearTimeout(workspaceSyncTimer);
	if (codeScrollFrame !== null) window.cancelAnimationFrame(codeScrollFrame);
	codeScrollHost.value?.removeEventListener("scroll", handleCodeScroll);
	window.removeEventListener("chat-artifact-open", handleChatArtifactOpen);
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
							:data-code-toc-path="file.path"
							class="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-slate-700 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1"
							:class="[
								selectedFilePath === file.path
									? 'bg-blue-100 text-blue-950 ring-1 ring-blue-300'
									: 'hover:bg-blue-50 hover:text-blue-900',
								highlightedFilePath === file.path
									? 'bg-cyan-100 text-slate-950 ring-2 ring-cyan-500 shadow-[0_0_0_4px_rgba(6,182,212,0.16)]'
									: '',
							]"
							@click="selectFile(file)"
						>
							<Code2
								class="mt-0.5 h-3.5 w-3.5 shrink-0"
								:class="selectedFilePath === file.path ? 'text-blue-700' : 'text-slate-500'"
							/>
							<div class="min-w-0 flex-1">
								<div class="truncate font-semibold">
									{{ file.name }}
								</div>
								<div
									class="line-clamp-2 text-[10px] leading-4"
									:class="selectedFilePath === file.path ? 'text-blue-700' : 'text-slate-500'"
								>
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
					<span class="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
						{{ codeFileSections.reduce((n, s) => n + s.files.length, 0) }} 个
					</span>
				</div>
				<Button
					variant="ghost"
					size="sm"
					:disabled="loadingFiles"
					@click="refreshCodeFiles"
				>
					<RefreshCw
						class="mr-1 h-4 w-4"
						:class="{ 'animate-spin': loadingFiles }"
					/>
					刷新
				</Button>
			</div>

			<div
				ref="codeScrollHost"
				class="min-h-0 flex-1 overflow-y-auto overflow-x-hidden"
			>
				<div v-if="codeFileSections.length" class="flex flex-col gap-3 p-4">
					<template
						v-for="section in codeFileSections"
						:key="`cards-${section.section}`"
					>
						<div class="mb-1 mt-2 flex items-center gap-2 text-sm font-bold text-slate-500">
							<FolderOpen class="h-4 w-4 text-blue-600" />
							<span>{{ section.sectionLabel }}</span>
							<span class="text-xs font-normal text-slate-400">
								{{ section.files.length }} 个文件
							</span>
						</div>

						<section
							v-for="file in section.files"
							:key="`card-${file.path}`"
							:data-code-card-path="file.path"
							tabindex="-1"
							class="overflow-hidden rounded-md border bg-white p-4 shadow-sm transition-all duration-300 focus:outline-none"
							:class="[
								selectedFilePath === file.path
									? 'border-blue-300 ring-2 ring-blue-100'
									: 'border-slate-200',
								highlightedFilePath === file.path
									? 'border-cyan-500 bg-cyan-50/40 ring-4 ring-cyan-200'
									: '',
							]"
						>
							<div class="flex items-start gap-3">
								<div class="rounded-lg bg-blue-50 p-2">
									<Code2 class="h-5 w-5 text-blue-700" />
								</div>
								<div class="min-w-0 flex-1">
									<div class="flex flex-wrap items-start justify-between gap-2">
										<div class="min-w-0">
											<h3 class="truncate text-base font-semibold text-slate-900">
												{{ file.name }}
											</h3>
											<p class="mt-0.5 break-all text-xs leading-5 text-slate-500">
												{{ file.path }}
											</p>
										</div>
										<button
											type="button"
											class="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 text-xs font-semibold text-slate-700 shadow-sm transition hover:border-blue-400 hover:bg-blue-50 hover:text-blue-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
											@click="openFilePreview(file.path)"
										>
											<ExternalLink class="h-3.5 w-3.5" />
											打开文件
										</button>
									</div>
									<p class="mt-2 text-sm leading-6 text-slate-600">
										{{ file.description }}
									</p>
									<div class="mt-3 flex flex-wrap items-center gap-2 text-xs">
										<span class="rounded-full bg-slate-100 px-2 py-1 text-slate-600">
											来源：{{
												file.attempt === "workspace"
													? "工作区文件"
													: file.attempt === "main"
														? "主力"
														: file.attempt
											}}
										</span>
										<span
											class="rounded-full px-2 py-1"
											:class="
												file.passed
													? 'bg-emerald-50 text-emerald-700'
													: 'bg-amber-50 text-amber-700'
											"
										>
											{{ file.passed ? "已通过产物检查" : "未通过或未检查" }}
										</span>
										<span
											v-if="codeFileLineCount(file.path)"
											class="rounded-full bg-blue-50 px-2 py-1 text-blue-700"
										>
											{{ codeFileLineCount(file.path) }} 行
										</span>
									</div>
								</div>
							</div>

							<div class="mt-4 overflow-hidden rounded-lg border border-slate-800 bg-slate-950">
								<div class="flex min-h-11 items-center justify-between gap-3 border-b border-slate-800 bg-slate-900 px-3 py-2">
									<div class="flex min-w-0 items-center gap-2">
										<span class="rounded bg-slate-800 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-cyan-300">
											Python
										</span>
										<span class="truncate text-xs text-slate-300">
											{{
												isCodeFileExpanded(file.path)
													? "完整代码"
													: codeFileHasMoreThan10Lines(file.path)
														? "前 10 行预览"
														: "完整代码"
											}}
										</span>
									</div>
									<button
										v-if="codeFileHasMoreThan10Lines(file.path)"
										type="button"
										:aria-expanded="isCodeFileExpanded(file.path)"
										class="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-blue-300 bg-blue-100 px-3 text-xs font-bold text-blue-950 shadow-sm transition hover:border-white hover:bg-white hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
										@click="toggleCodeFileExpanded(file.path)"
									>
										<ChevronsUp
											v-if="isCodeFileExpanded(file.path)"
											class="h-4 w-4"
										/>
										<ChevronsDown v-else class="h-4 w-4" />
										{{
											isCodeFileExpanded(file.path)
												? "收起到 10 行"
												: "展开全部代码"
										}}
									</button>
								</div>
								<div
									v-if="loadingCodeFiles.has(file.path)"
									class="p-4 text-xs text-slate-300"
								>
									<RefreshCw class="mr-1 inline h-3.5 w-3.5 animate-spin" />
									读取中...
								</div>
								<div
									v-else-if="codeFileErrors[file.path]"
									class="bg-red-950/50 p-4 text-xs text-red-200"
								>
									读取失败：{{ codeFileErrors[file.path] }}
								</div>
								<pre
									v-else
									class="overflow-auto p-4 font-mono text-xs leading-6 text-slate-100"
									:class="isCodeFileExpanded(file.path) ? 'max-h-none' : 'max-h-80'"
								><code>{{ codeFileDisplayedContent(file.path) }}</code></pre>
							</div>
						</section>
					</template>
				</div>

				<div
					v-else
					class="glass-card m-4 flex h-56 items-center justify-center text-sm text-slate-500"
				>
					{{ loadingFiles ? "正在读取 Python 文件..." : "暂无 Python 文件" }}
				</div>
			</div>
		</div>
	</div>
</template>
