<script setup lang="ts">
import { getWriterSeque } from "@/apis/commonApi";
import {
	getAllFilesDownloadUrl,
	getFileDownloadUrl,
	getFiles,
} from "@/apis/filesApi";
import CodeGallery from "@/components/AgentEditor/CodeGallery.vue";
import ImageGallery from "@/components/AgentEditor/ImageGallery.vue";
import ModelerEditor from "@/components/AgentEditor/ModelerEditor.vue";
import WriterEditor from "@/components/AgentEditor/WriterEditor.vue";
import ChatArea from "@/components/ChatArea.vue";
import ModelingDiscussion from "@/components/ModelingDiscussion.vue";
import QuestionDiscussion from "@/components/QuestionDiscussion.vue";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
	ResizableHandle,
	ResizablePanel,
	ResizablePanelGroup,
} from "@/components/ui/resizable";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTaskStore } from "@/stores/task";
import {
	Archive,
	ArrowLeft,
	ChevronDown,
	ChevronRight,
	Download,
	File,
	FileCode,
	FileImage,
	FileSpreadsheet,
	FileText,
	Folder,
	FolderOpen,
	Plus,
	RefreshCw,
	ScrollText,
} from "lucide-vue-next";
import {
	computed,
	onBeforeUnmount,
	onMounted,
	reactive,
	ref,
	watch,
} from "vue";
import { useRouter } from "vue-router";

const props = defineProps<{ task_id: string }>();

const taskStore = useTaskStore();
const router = useRouter();
const writerSequence = ref<string[]>([]);
const paperRefreshKey = ref(0);
const galleryRefreshKey = ref(0);

// 新消息到达时自动刷新图片/代码预览
watch(
	() => taskStore.messages.length,
	() => {
		galleryRefreshKey.value += 1;
	},
);
const startTime = ref<number>(Date.now());
const currentTime = ref<number>(Date.now());
let timer: ReturnType<typeof setInterval> | null = null;
const runningDuration = ref<string>("0s");
const isStopping = ref(false);
const isStarting = ref(false);
const discussionExpanded = ref(false);
const discussionAvailable = ref(false);
const discussionLocked = ref(false);
const localModelingConfirmed = ref(false);
const questionDiscussionExpanded = ref(false);
const questionDiscussionAvailable = ref(false);
const questionDiscussionLocked = ref(false);
const localQuestionConfirmed = ref(false);

// 面板展开状态持久化（用户手动关闭后刷新不再自动展开）
function panelStateKey(taskId: string, panel: string) {
	return `panel-expanded:${panel}:${taskId}`;
}
function getSavedPanelExpanded(taskId: string, panel: string) {
	if (typeof window === "undefined") return true;
	const v = window.localStorage.getItem(panelStateKey(taskId, panel));
	if (v === "closed") return false;
	return true;
}
function setSavedPanelExpanded(
	taskId: string,
	panel: string,
	expanded: boolean,
) {
	if (typeof window === "undefined") return;
	window.localStorage.setItem(
		panelStateKey(taskId, panel),
		expanded ? "open" : "closed",
	);
}
const terminalRuntimeStatuses = new Set([
	"stopped",
	"completed",
	"failed",
	"interrupted",
]);
const activeTab = ref<"modeler" | "writer" | "images" | "code">("modeler");

// ---- 子任务进度追踪 ----

const subTaskLabels: Record<string, string> = {
	eda: "EDA",
	ques1: "Q1",
	ques2: "Q2",
	ques3: "Q3",
	ques4: "Q4",
	ques5: "Q5",
	sensitivity_analysis: "灵敏度",
	firstPage: "封面",
	RepeatQues: "重述",
	analysisQues: "分析",
	modelAssumption: "假设",
	symbol: "符号",
	judge: "评价",
};
const solutionTaskOrder = [
	"eda",
	"ques1",
	"ques2",
	"ques3",
	"ques4",
	"ques5",
	"sensitivity_analysis",
];
const writeTaskOrder = [
	"firstPage",
	"RepeatQues",
	"analysisQues",
	"modelAssumption",
	"symbol",
	"judge",
];

type SubTaskNodeStatus =
	| "pending"
	| "active"
	| "coding"
	| "writing"
	| "done"
	| "stopping"
	| "stopped";

const subTaskNodes = computed(() => {
	const taskState = new Map<string, "coding" | "writing" | "done">();
	const seenKeys = new Set<string>();

	for (const msg of taskStore.messages) {
		if (msg.msg_type !== "system" || !("content" in msg)) continue;
		const content = (msg as { content?: string | null }).content ?? "";

		let match = content.match(/代码手求解成功(.+)$/);
		if (match) {
			const key = match[1].trim();
			seenKeys.add(key);
			taskState.set(key, "writing");
			continue;
		}

		match = content.match(/代码手开始求解(.+)$/);
		if (match) {
			const key = match[1].trim();
			seenKeys.add(key);
			if (!taskState.has(key)) taskState.set(key, "coding");
			continue;
		}

		match = content.match(/论文手完成(.+)部分/);
		if (match) {
			const key = match[1].trim();
			seenKeys.add(key);
			taskState.set(key, "done");
			continue;
		}

		match = content.match(/论文手开始写(.+)部分/);
		if (match) {
			const key = match[1].trim();
			seenKeys.add(key);
			if (taskState.get(key) !== "done") taskState.set(key, "writing");
		}
	}

	const nodes: Array<{
		key: string;
		label: string;
		status: SubTaskNodeStatus;
		index: number;
	}> = [];

	const desc =
		taskStore.currentProgress?.description ??
		taskStore.taskRuntimeState?.current_step ??
		taskStore.taskRuntimeState?.message ??
		"";
	const activeMatch = desc.match(/(?:正在求解|求解完成|正在撰写)[：:]\s*(.+)/);
	const activeKey = activeMatch ? activeMatch[1].trim() : "";
	const runtimeStatus = taskStore.taskStatus;
	const isStoppedLike = ["stopping", "stopped", "interrupted"].includes(
		runtimeStatus,
	);
	const stopNodeStatus: SubTaskNodeStatus =
		runtimeStatus === "stopping" ? "stopping" : "stopped";
	const shouldShowPrefix =
		taskStore.isRunning ||
		taskStore.messages.length > 0 ||
		runtimeStatus !== "ready";

	const hasSolutionTasks = solutionTaskOrder.some((k) => seenKeys.has(k));
	const hasWriterTasks = writeTaskOrder.some((k) => seenKeys.has(k));
	const modelerDone =
		hasSolutionTasks ||
		hasWriterTasks ||
		desc.includes("求解") ||
		desc.includes("代码") ||
		desc.includes("撰写") ||
		desc.includes("论文");
	const waitingQuestionConfirm =
		hasQuestionWaitMessage.value && !hasQuestionConfirmedMessage.value;
	const waitingModelingConfirm =
		hasModelingWaitMessage.value && !hasModelingConfirmedMessage.value;
	const questionConfirmedTransition =
		hasQuestionConfirmedMessage.value &&
		!hasModelingWaitMessage.value &&
		!hasModelingConfirmedMessage.value;

	const coordinatorDone =
		modelerDone ||
		waitingQuestionConfirm ||
		questionConfirmedTransition ||
		hasQuestionConfirmedMessage.value ||
		hasModelingWaitMessage.value ||
		hasModelingConfirmedMessage.value ||
		desc.includes("建模");

	const modelerActive =
		hasQuestionConfirmedMessage.value &&
		!modelerDone &&
		!waitingModelingConfirm;

	if (shouldShowPrefix) {
		nodes.push({
			key: "coordinator",
			label: "规划",
			status: coordinatorDone ? "done" : "active",
			index: nodes.length,
		});
		nodes.push({
			key: "modeler",
			label: "建模",
			status: modelerDone
				? "done"
				: waitingModelingConfirm
					? "done"
					: modelerActive
						? "active"
						: "pending",
			index: nodes.length,
		});
	}

	for (const key of solutionTaskOrder) {
		if (!seenKeys.has(key)) continue;
		const state = taskState.get(key) ?? "pending";
		nodes.push({
			key,
			label: subTaskLabels[key] ?? key,
			status: activeKey === key ? "active" : state === "done" ? "done" : state,
			index: nodes.length,
		});
	}

	for (const key of writeTaskOrder) {
		if (!seenKeys.has(key)) continue;
		const state = taskState.get(key) ?? "pending";
		nodes.push({
			key,
			label: subTaskLabels[key] ?? key,
			status: activeKey === key ? "active" : state === "done" ? "done" : state,
			index: nodes.length,
		});
	}

	if (isStoppedLike && nodes.length > 0) {
		const activeIndex = activeKey
			? nodes.findIndex((node) => node.key === activeKey)
			: -1;
		let candidateIndex = activeIndex;
		if (candidateIndex < 0) {
			for (let i = nodes.length - 1; i >= 0; i--) {
				if (["active", "coding", "writing"].includes(nodes[i].status)) {
					candidateIndex = i;
					break;
				}
			}
		}
		const stopIndex = candidateIndex >= 0 ? candidateIndex : nodes.length - 1;
		nodes[stopIndex] = {
			...nodes[stopIndex],
			status: stopNodeStatus,
		};
	}

	return nodes;
});

const getMessageTime = (createdAt?: string): number | null => {
	if (!createdAt) return null;
	const timestamp = Date.parse(createdAt);
	return Number.isNaN(timestamp) ? null : timestamp;
};

const taskStartTimestamp = computed(() => {
	const startedAt = getMessageTime(taskStore.taskRuntimeState?.started_at);
	if (startedAt != null) return startedAt;
	for (const message of taskStore.messages) {
		const timestamp = getMessageTime(message.created_at);
		if (timestamp != null) return timestamp;
	}
	return startTime.value;
});

function getTerminalSystemType(message: (typeof taskStore.messages)[number]) {
	if (message.msg_type !== "system") return null;
	const content = message.content ?? "";
	if (message.type === "success" && content.includes("任务处理完成")) {
		return "success";
	}
	if (message.type === "warning" && content.includes("任务已停止")) {
		return "warning";
	}
	if (message.type === "error") return "error";
	return null;
}

const taskEndTimestamp = computed(() => {
	if (terminalRuntimeStatuses.has(taskStore.taskStatus)) {
		const finishedAt = getMessageTime(taskStore.taskRuntimeState?.finished_at);
		if (finishedAt != null) return finishedAt;
	}
	for (let i = taskStore.messages.length - 1; i >= 0; i--) {
		const message = taskStore.messages[i];
		if (getTerminalSystemType(message) != null) {
			return getMessageTime(message.created_at) ?? Date.now();
		}
	}
	if (terminalRuntimeStatuses.has(taskStore.taskStatus)) {
		return getMessageTime(taskStore.taskRuntimeState?.updated_at) ?? Date.now();
	}
	return null;
});

const isTaskFinished = computed(() => taskEndTimestamp.value != null);
const latestSystemType = computed(() => {
	for (let i = taskStore.messages.length - 1; i >= 0; i--) {
		const message = taskStore.messages[i];
		const type = getTerminalSystemType(message);
		if (type != null) return type;
	}
	return null;
});

const runtimeStatus = computed(() => taskStore.taskStatus);
const isStoppingNow = computed(
	() => runtimeStatus.value === "stopping" || isStopping.value,
);
const isStoppedLike = computed(() =>
	["stopping", "stopped", "interrupted"].includes(runtimeStatus.value),
);
const startButtonLabel = computed(() => {
	if (isStarting.value) return "启动中...";
	if (
		runtimeStatus.value === "stopped" ||
		runtimeStatus.value === "interrupted"
	) {
		return "继续运行";
	}
	if (runtimeStatus.value === "failed") return "重新运行";
	return "开始运行";
});

/** 从进度描述推断当前大阶段类型，用于自动切换 Tab */
const activePhaseTab = computed<"modeler" | "coder" | "writer" | null>(() => {
	if (taskStore.writerMessages.length > 0) return "writer";
	if (
		taskStore.coderMessages.length > 0 ||
		taskStore.interpreterMessage.length > 0
	)
		return "coder";
	const desc =
		taskStore.currentProgress?.description ??
		taskStore.taskRuntimeState?.current_step ??
		"";
	if (desc.includes("建模")) return "modeler";
	return null;
});

const overallProgress = computed(() => {
	const runtimeProgress =
		taskStore.currentProgress?.percentage ??
		taskStore.taskRuntimeState?.progress;
	if (runtimeStatus.value === "completed" || runtimeStatus.value === "failed") {
		return 100;
	}
	if (latestSystemType.value === "success") return 100;
	// 仅在任务未处于活跃运行状态时才用历史错误消息拉满进度
	if (latestSystemType.value === "error" && !taskStore.isRunning) return 100;
	if (isStoppedLike.value) return Math.round(runtimeProgress ?? 0);
	if (runtimeProgress != null) {
		return Math.max(
			Math.round(runtimeProgress),
			taskStore.wsStatus === "connected" ? 3 : 0,
		);
	}
	return taskStore.wsStatus === "connected" ? 3 : 0;
});

const progressText = computed(() => {
	if (isWaitingQuestionConfirm.value) return "请在下方确认问题划分";
	if (isQuestionConfirmTransition.value)
		return "问题划分已确认，等待进入建模方案讨论";
	if (isWaitingModelingConfirm.value) return "请在下方确认各问建模方案";

	if (taskStore.currentProgress?.description)
		return taskStore.currentProgress.description;
	if (taskStore.taskRuntimeState?.current_step)
		return taskStore.taskRuntimeState.current_step;
	if (taskStore.taskRuntimeState?.message)
		return taskStore.taskRuntimeState.message;
	return taskStore.wsStatus === "connected" ? "任务启动中" : "等待连接";
});

const currentPhaseName = computed(() => {
	if (runtimeStatus.value === "stopping") return "正在停止";
	if (runtimeStatus.value === "stopped") return "已停止";
	if (runtimeStatus.value === "interrupted") return "已中断";
	if (runtimeStatus.value === "failed") return "运行出错";
	if (runtimeStatus.value === "completed") return "任务完成";

	if (isWaitingQuestionConfirm.value) return "等待确认问题划分";
	if (isQuestionConfirmTransition.value) return "等待进入建模方案讨论";
	if (isWaitingModelingConfirm.value) return "等待确认建模方案";

	// 仅在任务未处于活跃运行状态时才显示历史错误状态
	if (latestSystemType.value === "error" && !taskStore.isRunning)
		return "运行出错";
	if (latestSystemType.value === "warning" && !taskStore.isRunning)
		return "任务结束";
	const desc =
		taskStore.currentProgress?.description ??
		taskStore.taskRuntimeState?.current_step ??
		taskStore.taskRuntimeState?.message ??
		"";
	if (desc.includes("拆解") || desc.includes("规划")) return "任务规划";
	if (desc.includes("建模")) return "建模分析";
	if (desc.includes("求解")) return "代码执行";
	if (desc.includes("撰写") || desc.includes("论文")) return "论文写作";
	return taskStore.wsStatus === "connected" ? "任务启动" : "等待连接";
});

const progressStatus = computed(() => {
	if (runtimeStatus.value === "stopping") return "停止中";
	if (runtimeStatus.value === "stopped") return "已停止";
	if (runtimeStatus.value === "interrupted") return "已中断";
	if (runtimeStatus.value === "failed") return "出错";
	if (runtimeStatus.value === "completed") return "已完成";

	if (isWaitingQuestionConfirm.value || isWaitingModelingConfirm.value)
		return "待确认";

	if (isQuestionConfirmTransition.value) return "等待中";

	// 仅在任务未处于活跃运行状态时才用历史终止消息覆盖状态文本
	if (latestSystemType.value === "error" && !taskStore.isRunning) return "出错";
	if (latestSystemType.value === "warning" && !taskStore.isRunning)
		return "已结束";
	return taskStore.isRunning ? "进行中" : "等待中";
});

const updateDuration = () => {
	const endTimestamp = taskEndTimestamp.value;
	if (endTimestamp != null) {
		currentTime.value = endTimestamp;
		runningDuration.value = formatDuration(
			Math.max(0, endTimestamp - taskStartTimestamp.value),
		);
		if (timer) {
			clearInterval(timer);
			timer = null;
		}
		return;
	}
	if (!taskStore.isRunning) {
		runningDuration.value = "0s";
		return;
	}
	currentTime.value = Date.now();
	runningDuration.value = formatDuration(
		Math.max(0, currentTime.value - taskStartTimestamp.value),
	);
};

function formatDuration(ms: number): string {
	const seconds = Math.floor(ms / 1000);
	const hours = Math.floor(seconds / 3600);
	const minutes = Math.floor((seconds % 3600) / 60);
	const remainingSeconds = seconds % 60;
	if (hours > 0) return `${hours}h ${minutes}m ${remainingSeconds}s`;
	if (minutes > 0) return `${minutes}m ${remainingSeconds}s`;
	return `${remainingSeconds}s`;
}

async function handleStop() {
	isStopping.value = true;
	taskStore.addUserAction(
		"停止",
		"任务运行",
		"用户请求安全停止当前建模工作流。",
		{
			from: "User",
			to: "System",
			label: "发送停止指令",
		},
	);
	await taskStore.stopTask(props.task_id);
	isStopping.value = false;
}

async function handleStart() {
	isStarting.value = true;
	try {
		taskStore.addUserAction(
			runtimeStatus.value === "ready" ? "启动" : "继续",
			"任务运行",
			"用户请求启动或恢复当前建模工作流。",
			{
				from: "User",
				to: "System",
				label: "启动工作流",
			},
		);
		await taskStore.startTask(props.task_id);
	} finally {
		isStarting.value = false;
	}
}

function goBackToHome() {
	void router.push("/chat");
}

function openPdfPreview() {
	void router.push(`/task/${props.task_id}/pdf`);
}

// ---- Export / File tree ----

interface WorkspaceFile {
	filename: string;
	file_type: string;
	size?: number;
	modified_time?: string | number | Date;
}

// ---- 目录树类型 ----

interface TreeFile {
	/** 文件完整相对路径（含子目录），用于下载 */
	relativePath: string;
	/** 仅文件名部分，用于显示 */
	baseName: string;
	/** 文件扩展名 */
	ext: string;
}

interface TreeDir {
	/** 子目录名，如 "5.1_问题1的模型建立与求解" */
	name: string;
	/** 论文编号前缀，如 "5.1" */
	sectionNum: string;
	/** 目录中文标签，如 "问题1的模型建立与求解" */
	label: string;
	files: TreeFile[];
}

interface FileTree {
	/** work_dir 根目录下的文件（非子目录） */
	rootFiles: TreeFile[];
	/** 按论文章节分组的子目录 */
	dirs: TreeDir[];
}

const fileDialogOpen = ref(false);
const fileList = ref<WorkspaceFile[]>([]);
const fileListLoading = ref(false);
/** 展开的子目录集合 */
const expandedDirs = reactive(new Set<string>());
const downloadingFile = ref<string | null>(null);
const downloadingAll = ref(false);

// ---- 目录树计算 ----

/**
 * 将后端返回的平铺文件列表（含子目录相对路径）转换为目录树结构。
 * 后端 get_current_files() 使用 rglob 返回如 "5.1_问题1的模型建立与求解/5.1_prediction.png" 的路径。
 */
const fileTree = computed<FileTree>(() => {
	const rootFiles: TreeFile[] = [];
	const dirMap = new Map<string, TreeFile[]>();

	for (const f of fileList.value) {
		const raw = f.filename || "";
		if (!raw) continue;
		const normalized = raw.replace(/\\/g, "/");
		const slashIdx = normalized.indexOf("/");

		if (slashIdx === -1) {
			rootFiles.push({
				relativePath: normalized,
				baseName: normalized,
				ext: normalized.split(".").pop()?.toLowerCase() ?? "",
			});
		} else {
			const dirName = normalized.slice(0, slashIdx);
			const baseName = normalized.slice(slashIdx + 1);
			if (!dirMap.has(dirName)) dirMap.set(dirName, []);
			dirMap.get(dirName)?.push({
				relativePath: normalized,
				baseName,
				ext: baseName.split(".").pop()?.toLowerCase() ?? "",
			});
		}
	}

	const dirs: TreeDir[] = Array.from(dirMap.entries())
		.sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
		.map(([name, files]) => {
			const underscoreIdx = name.indexOf("_");
			const sectionNum =
				underscoreIdx !== -1 ? name.slice(0, underscoreIdx) : name;
			const label = underscoreIdx !== -1 ? name.slice(underscoreIdx + 1) : "";
			return { name, sectionNum, label, files };
		});

	return { rootFiles, dirs };
});

/** 切换子目录展开状态 */
function toggleDir(dirName: string) {
	if (expandedDirs.has(dirName)) {
		expandedDirs.delete(dirName);
	} else {
		expandedDirs.add(dirName);
	}
}

function handleExportPdf() {
	openPdfPreview();
}

async function handleExportFolder() {
	if (downloadingAll.value) return;
	downloadingAll.value = true;
	try {
		const res = await getAllFilesDownloadUrl(props.task_id);
		if (res.data?.download_url) {
			const link = document.createElement("a");
			link.href = res.data.download_url;
			link.download = `task_${props.task_id}_files.zip`;
			link.target = "_blank";
			document.body.appendChild(link);
			link.click();
			document.body.removeChild(link);
		}
	} finally {
		downloadingAll.value = false;
	}
}

function handleExportLogs() {
	taskStore.downloadMessages();
}

async function handleViewFileTree() {
	fileDialogOpen.value = true;
	fileListLoading.value = true;
	fileList.value = [];
	try {
		const res = await getFiles(props.task_id);
		fileList.value = (res.data ?? []).map((f) => ({
			filename:
				f.filename ?? (f as WorkspaceFile & { name?: string }).name ?? "",
			file_type: f.file_type ?? "",
			size: (f as WorkspaceFile).size,
			modified_time: (f as WorkspaceFile).modified_time,
		}));
		// 默认展开所有子目录
		expandedDirs.clear();
		for (const f of fileList.value) {
			const raw = (f.filename || "").replace(/\\/g, "/");
			const slashIdx = raw.indexOf("/");
			if (slashIdx !== -1) expandedDirs.add(raw.slice(0, slashIdx));
		}
	} finally {
		fileListLoading.value = false;
	}
}

async function downloadSingleFile(filename: string) {
	if (downloadingFile.value) return;
	downloadingFile.value = filename;
	try {
		const res = await getFileDownloadUrl(props.task_id, filename);
		if (res.data?.download_url) {
			const link = document.createElement("a");
			link.href = res.data.download_url;
			link.download = filename;
			link.target = "_blank";
			document.body.appendChild(link);
			link.click();
			document.body.removeChild(link);
		}
	} finally {
		downloadingFile.value = null;
	}
}

function getFileIcon(filename: string) {
	const ext = filename.split(".").pop()?.toLowerCase() ?? "";
	if (["png", "jpg", "jpeg", "gif", "bmp", "webp", "svg"].includes(ext))
		return FileImage;
	if (["py", "ipynb", "js", "ts", "json", "vue"].includes(ext)) return FileCode;
	if (["csv", "xlsx", "xls"].includes(ext)) return FileSpreadsheet;
	if (["txt", "md", "xml", "yml", "yaml"].includes(ext)) return FileText;
	return File;
}

function formatFileSize(size: number | undefined): string {
	if (!size) return "";
	const units = ["B", "KB", "MB", "GB"];
	let i = 0;
	let s = size;
	while (s >= 1024 && i < units.length - 1) {
		s /= 1024;
		i++;
	}
	return `${s.toFixed(1)} ${units[i]}`;
}

function refreshPaper() {
	paperRefreshKey.value += 1;
}

async function loadCurrentTask(taskId: string) {
	if (!taskId) return;
	taskStore.closeWebSocket();
	const wasRunning = await taskStore.loadTaskMessages(taskId);
	if (wasRunning) {
		taskStore.connectWebSocket(taskId);
	}
	// 刷新后重新检查是否需要显示模型对比区（绕过 watcher 时序问题）
	if (!discussionLocked.value) {
		const hasWait = taskStore.messages.some(
			(m) =>
				m.msg_type === "system" &&
				(m.content ?? "").includes("等待用户确认各问建模方案"),
		);
		if (hasWait) {
			discussionAvailable.value = true;
			discussionExpanded.value = getSavedPanelExpanded(
				props.task_id,
				"modeling",
			);
			questionDiscussionExpanded.value = false;
		}
	}
}

const hasModelingWaitMessage = computed(() =>
	taskStore.messages.some(
		(message) =>
			message.msg_type === "system" &&
			(message.content ?? "").includes("等待用户确认各问建模方案"),
	),
);

const hasQuestionWaitMessage = computed(() =>
	taskStore.messages.some(
		(message) =>
			message.msg_type === "system" &&
			(message.content ?? "").includes("等待用户确认问题划分"),
	),
);

const hasQuestionConfirmedMessage = computed(
	() =>
		localQuestionConfirmed.value ||
		taskStore.messages.some(
			(message) =>
				message.msg_type === "system" &&
				((message.content ?? "").includes("问题划分已确认") ||
					(message.content ?? "").includes("已复用问题划分")),
		),
);

const hasModelingConfirmedMessage = computed(
	() =>
		localModelingConfirmed.value ||
		taskStore.messages.some(
			(message) =>
				message.msg_type === "system" &&
				((message.content ?? "").includes("建模方案已确认") ||
					(message.content ?? "").includes("已复用建模方案选择")),
		),
);

const isWaitingQuestionConfirm = computed(
	() => hasQuestionWaitMessage.value && !hasQuestionConfirmedMessage.value,
);

const isQuestionConfirmTransition = computed(
	() =>
		hasQuestionConfirmedMessage.value &&
		!hasModelingWaitMessage.value &&
		!hasModelingConfirmedMessage.value &&
		!terminalRuntimeStatuses.has(taskStore.taskStatus),
);

const isWaitingModelingConfirm = computed(
	() => hasModelingWaitMessage.value && !hasModelingConfirmedMessage.value,
);
// Coordinator 完成后显示问题划分讨论（同时监听后端等待消息）
watch(
	() => {
		const msgs = taskStore.coordinatorMessages;
		if (
			hasQuestionWaitMessage.value ||
			hasQuestionConfirmedMessage.value ||
			hasModelingWaitMessage.value ||
			hasModelingConfirmedMessage.value
		)
			return true;
		if (msgs.length === 0) return false;
		const last = msgs[msgs.length - 1];
		return last.stream_state !== "streaming";
	},
	(done) => {
		if (done && !hasQuestionConfirmedMessage.value) {
			questionDiscussionAvailable.value = true;
			questionDiscussionExpanded.value = true;
			discussionExpanded.value = false;
		}
	},
	{ immediate: true },
);

// 问题划分讨论消息监听
watch(
	[hasQuestionWaitMessage, hasQuestionConfirmedMessage],
	([waiting, confirmed]) => {
		if (waiting) {
			questionDiscussionAvailable.value = true;
			questionDiscussionExpanded.value = !confirmed;
		}
		if (confirmed) {
			questionDiscussionAvailable.value = true;
			questionDiscussionExpanded.value = false;
			questionDiscussionLocked.value = true;
		}
	},
	{ immediate: true },
);

// 建模讨论消息监听（仅在问题划分已确认后才触发）
watch(
	[hasModelingWaitMessage, hasModelingConfirmedMessage],
	([waiting, confirmed]) => {
		// 已锁定（用户已确认建模方案）时，不再自动展开面板
		if (discussionLocked.value) return;
		// 问题讨论已确认 或 根本没有问题讨论阶段（旧任务/断点恢复）→ 允许打开
		if (
			waiting &&
			(hasQuestionConfirmedMessage.value || !hasQuestionWaitMessage.value)
		) {
			discussionAvailable.value = true;
			discussionExpanded.value = !confirmed;
		}
		if (confirmed) {
			discussionAvailable.value = true;
			discussionExpanded.value = false;
			discussionLocked.value = true;
		}
	},
	{ immediate: true },
);

// 新任务重置
watch(
	() => taskStore.taskStatus,
	(status) => {
		if (status === "ready") {
			questionDiscussionAvailable.value = false;
			questionDiscussionExpanded.value = false;
			questionDiscussionLocked.value = false;
			localQuestionConfirmed.value = false;
			discussionAvailable.value = false;
			discussionExpanded.value = false;
			discussionLocked.value = false;
			localModelingConfirmed.value = false;
			if (typeof window !== "undefined") {
				window.localStorage.removeItem(`question-confirmed:${props.task_id}`);
				window.localStorage.removeItem(`modeling-confirmed:${props.task_id}`);
			}
		}
	},
);

watch(
	() => props.task_id,
	(taskId) => {
		questionDiscussionAvailable.value = false;
		questionDiscussionExpanded.value = false;
		questionDiscussionLocked.value = false;
		discussionAvailable.value = false;
		discussionExpanded.value = false;
		discussionLocked.value = false;
		// 优先从 localStorage 恢复确认状态，避免刷新后重新弹出比选
		localQuestionConfirmed.value =
			typeof window !== "undefined" &&
			window.localStorage.getItem(`question-confirmed:${taskId}`) === "true";
		localModelingConfirmed.value =
			typeof window !== "undefined" &&
			window.localStorage.getItem(`modeling-confirmed:${taskId}`) === "true";
		void loadCurrentTask(taskId);
	},
	{ immediate: true },
);

function onQuestionConfirmed() {
	questionDiscussionExpanded.value = false;
	questionDiscussionLocked.value = true;
	questionDiscussionAvailable.value = true;
	localQuestionConfirmed.value = true;
	discussionExpanded.value = false;
	if (typeof window !== "undefined") {
		window.localStorage.setItem(`question-confirmed:${props.task_id}`, "true");
	}
}

function onModelingConfirmed() {
	discussionExpanded.value = false;
	discussionLocked.value = true;
	localModelingConfirmed.value = true;
	if (typeof window !== "undefined") {
		window.localStorage.setItem(`modeling-confirmed:${props.task_id}`, "true");
	}
}

onMounted(async () => {
	const res = await getWriterSeque();
	writerSequence.value = Array.isArray(res.data?.writer_seque)
		? res.data.writer_seque
		: [];
	updateDuration();
	timer = setInterval(updateDuration, 1000);
});

onBeforeUnmount(() => {
	taskStore.closeWebSocket();
	if (timer) clearInterval(timer);
});
</script>

<template>
  <div class="fixed inset-0">
    <ResizablePanelGroup direction="horizontal" class="h-full rounded-lg border">
      <ResizablePanel :default-size="36" class="h-full min-w-[320px]">
        <div class="flex h-full flex-col border-r border-white/20 glass-left-panel">
          <div class="border-b border-white/20 px-4 py-2 space-y-2 glass-header">
            <div class="flex items-center justify-between gap-3">
              <div class="flex min-w-0 items-start gap-2">
                <Button
                  variant="ghost"
                  size="icon"
                  class="h-8 w-8 shrink-0"
                  title="返回主界面"
                  aria-label="返回主界面"
                  @click="goBackToHome"
                >
                  <ArrowLeft class="h-4 w-4" />
                </Button>
                <div class="min-w-0 space-y-1">
                  <div class="text-sm text-gray-600 whitespace-nowrap">
                    运行时长: <span class="font-mono text-blue-600">{{ runningDuration }}</span>
                    <span v-if="isTaskFinished" class="ml-2 rounded-full bg-green-50 px-2 py-0.5 text-xs text-green-600">
                      已停止计时
                    </span>
                  </div>
                  <div class="flex items-center gap-1.5 text-sm whitespace-nowrap">
                    <span
                      class="inline-block h-2 w-2 rounded-full"
                      :class="{
                        'bg-green-500': taskStore.wsStatus === 'connected',
                        'bg-yellow-500 animate-pulse': taskStore.wsStatus === 'connecting' || taskStore.wsStatus === 'reconnecting',
                        'bg-red-500': taskStore.wsStatus === 'disconnected',
                      }"
                    />
                    <span class="text-gray-500">
                      {{
                        taskStore.wsStatus === 'connected' ? '已连接'
                        : taskStore.wsStatus === 'connecting' ? '连接中'
                        : taskStore.wsStatus === 'reconnecting' ? '重连中'
                        : '未连接'
                      }}
                    </span>
                  </div>
                </div>
              </div>
              <div class="flex shrink-0 items-center gap-2">
                <Button v-if="runtimeStatus === 'stopping'" variant="destructive" disabled>
                  停止中...
                </Button>
                <Button v-else-if="taskStore.isRunning" variant="destructive" :disabled="isStoppingNow" @click="handleStop">
                  {{ isStoppingNow ? "停止中..." : "停止运行" }}
                </Button>
                <Button v-else variant="default" :disabled="isStarting" @click="handleStart">
                  {{ startButtonLabel }}
                </Button>
                <!-- + 导出菜单 -->
                <DropdownMenu>
                  <DropdownMenuTrigger as-child>
                    <Button variant="outline" size="icon" class="shrink-0" title="更多操作">
                      <Plus class="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" class="w-48">
                    <DropdownMenuItem @click="handleExportPdf">
                      <Archive class="mr-2 h-4 w-4 text-slate-500" />
                      导出 PDF
                    </DropdownMenuItem>
                    <DropdownMenuItem @click="handleExportFolder" :disabled="downloadingAll">
                      <RefreshCw v-if="downloadingAll" class="mr-2 h-4 w-4 animate-spin text-slate-400" />
                      <FolderOpen v-else class="mr-2 h-4 w-4 text-slate-500" />
                      {{ downloadingAll ? '打包中...' : '导出文件夹' }}
                    </DropdownMenuItem>
                    <DropdownMenuItem @click="handleExportLogs">
                      <ScrollText class="mr-2 h-4 w-4 text-slate-500" />
                      导出日志
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem @click="handleViewFileTree">
                      <Download class="mr-2 h-4 w-4 text-slate-500" />
                      查看文件夹结构
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </div>
            <div class="rounded-xl border border-white/20 bg-white/30 backdrop-blur px-3 py-2 space-y-1.5">
              <!-- 顶部：阶段名 + 百分比 -->
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-1.5 min-w-0">
                  <span class="text-[10px] text-slate-400 shrink-0">当前阶段</span>
                  <span class="truncate text-sm font-semibold text-slate-900">{{ currentPhaseName }}</span>
                </div>
                <div class="flex items-center gap-2 shrink-0">
                  <span class="text-[10px] text-slate-400 hidden sm:inline">{{ progressText }}</span>
                  <span class="font-mono text-lg font-semibold text-blue-600">{{ overallProgress }}%</span>
                  <span
                    class="rounded-full px-2 py-0.5 text-[10px] font-medium"
                    :class="{
                      'bg-green-50 text-green-700': progressStatus === '已完成',
                      'bg-red-50 text-red-700': progressStatus === '出错',
                      'bg-amber-50 text-amber-700': progressStatus === '已结束' || progressStatus === '停止中' || progressStatus === '已停止' || progressStatus === '已中断' || progressStatus === '待确认',
                      'bg-blue-50 text-blue-700': progressStatus === '进行中',
                      'bg-slate-100 text-slate-500': progressStatus === '等待中',
                    }"
                  >{{ progressStatus }}</span>
                </div>
              </div>

              <!-- 进度条 -->
              <div class="relative h-2.5 rounded-full bg-slate-200 overflow-hidden">
                <div
                  class="absolute inset-y-0 left-0 rounded-full transition-all duration-700 ease-out"
                  :class="{
                    'bg-amber-500': isStoppedLike,
                    'bg-red-500': progressStatus === '出错',
                    'bg-green-500': progressStatus === '已完成',
                    'bg-blue-500': !isStoppedLike && progressStatus !== '出错' && progressStatus !== '已完成',
                  }"
                  :style="{ width: `${overallProgress}%` }"
                />
              </div>

              <!-- 子任务节点：动态从系统消息中提取 -->
              <div class="flex justify-start gap-0.5 overflow-x-auto scrollbar-none">
                <div
                  v-for="node in subTaskNodes"
                  :key="node.key"
                  class="flex flex-col items-center shrink-0"
                  style="min-width: 28px"
                >
                  <span
                    class="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[9px] font-semibold"
                    :class="{
                      'bg-blue-600 text-white': node.status === 'done',
                      'bg-blue-500 text-white': node.status === 'active',
                      'bg-blue-300 text-white': node.status === 'coding' || node.status === 'writing',
                      'bg-orange-500 text-white shadow-[0_0_18px_rgba(249,115,22,0.9)] animate-pulse': node.status === 'stopping',
                      'bg-orange-500 text-white shadow-[0_0_18px_rgba(249,115,22,0.75)]': node.status === 'stopped',
                      'bg-slate-200 text-slate-400': node.status === 'pending',
                    }"
                  >{{ node.status === "done" ? "✓" : node.index + 1 }}</span>
                  <span
                    class="text-[8px] mt-0.5 font-medium text-center leading-tight"
                    :class="{
                      'text-blue-700': node.status === 'active',
                      'text-slate-500': node.status === 'done',
                      'text-slate-400': node.status === 'pending',
                      'text-blue-600': node.status === 'coding' || node.status === 'writing',
                    }"
                  >{{ node.label }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Agent 消息流 -->
          <ChatArea
            class="flex-1 min-h-0"
            :messages="taskStore.messages"
            :task-status="taskStore.taskStatus"
            :taskId="props.task_id"
          />

          <!-- 建模讨论区（上方） -->
          <ModelingDiscussion
            v-if="discussionAvailable"
            :task_id="props.task_id"
            :expanded="discussionExpanded"
            :locked="discussionLocked"
            :disabled="discussionLocked"
            @toggle="discussionExpanded = !discussionExpanded; setSavedPanelExpanded(props.task_id, 'modeling', discussionExpanded); if (discussionExpanded) questionDiscussionExpanded = false"
            @confirm="onModelingConfirmed"
          />

          <!-- 问题划分讨论区（锚定底部） -->
          <QuestionDiscussion
            v-if="questionDiscussionAvailable"
            :task_id="props.task_id"
            :expanded="questionDiscussionExpanded"
            :locked="questionDiscussionLocked"
            :disabled="questionDiscussionLocked"
            @toggle="questionDiscussionExpanded = !questionDiscussionExpanded; if (questionDiscussionExpanded) discussionExpanded = false"
            @confirm="onQuestionConfirmed"
          />
        </div>
      </ResizablePanel>

      <ResizableHandle />

      <ResizablePanel :default-size="64" class="h-full">
        <Tabs v-model="activeTab" class="flex h-full flex-col">
          <div class="flex items-center justify-between border-b border-white/20 bg-white/50 px-3 py-1.5">
            <TabsList class="h-8">
              <TabsTrigger value="modeler" class="text-xs">
                {{ questionDiscussionAvailable && !questionDiscussionLocked ? "原始题目" : "建模方案" }}
              </TabsTrigger>
              <TabsTrigger value="writer" class="text-xs">论文预览</TabsTrigger>
              <TabsTrigger value="images" class="text-xs">图片</TabsTrigger>
              <TabsTrigger value="code" class="text-xs">代码</TabsTrigger>
            </TabsList>
          </div>
          <div class="min-h-0 flex-1">
            <TabsContent value="modeler" class="h-full m-0 p-0">
              <ModelerEditor :task_id="props.task_id" />
            </TabsContent>
            <TabsContent value="writer" class="h-full m-0 p-0">
              <WriterEditor
                :messages="taskStore.writerMessages"
                :writer-sequence="writerSequence"
                :refresh-key="paperRefreshKey"
              />
            </TabsContent>
            <TabsContent value="images" class="h-full m-0 p-0 overflow-y-auto">
              <ImageGallery :task_id="props.task_id" :refresh-key="galleryRefreshKey" />
            </TabsContent>
            <TabsContent value="code" class="h-full m-0 p-0 overflow-y-auto">
              <CodeGallery :task_id="props.task_id" :refresh-key="galleryRefreshKey" />
            </TabsContent>
          </div>
        </Tabs>
      </ResizablePanel>
    </ResizablePanelGroup>

    <!-- 文件夹结构对话框 -->
    <Dialog v-model:open="fileDialogOpen">
      <DialogContent class="max-w-lg">
        <DialogHeader>
          <DialogTitle class="flex items-center gap-2">
            <FolderOpen class="h-4 w-4" />
            文件夹结构
          </DialogTitle>
        </DialogHeader>
        <div class="mt-2">
          <div v-if="fileListLoading" class="flex items-center justify-center py-8 text-sm text-slate-400">
            <RefreshCw class="mr-2 h-4 w-4 animate-spin" />加载中...
          </div>
          <div v-else-if="!fileList.length" class="py-8 text-center text-sm text-slate-400">暂无文件</div>
          <ScrollArea v-else class="h-80">
            <div class="space-y-1 pr-2">
              <!-- ── 子目录（按论文章节分组） ── -->
              <div
                v-for="dir in fileTree.dirs"
                :key="dir.name"
                class="rounded-lg border border-gray-200 overflow-hidden"
              >
                <button
                  class="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 hover:bg-gray-100 transition-colors text-left select-none"
                  @click="toggleDir(dir.name)"
                >
                  <component
                    :is="expandedDirs.has(dir.name) ? ChevronDown : ChevronRight"
                    class="w-3.5 h-3.5 text-gray-400 flex-shrink-0"
                  />
                  <component
                    :is="expandedDirs.has(dir.name) ? FolderOpen : Folder"
                    class="w-4 h-4 text-amber-500 flex-shrink-0"
                  />
                  <span class="text-xs font-semibold text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded flex-shrink-0">
                    {{ dir.sectionNum }}
                  </span>
                  <span class="text-sm font-medium text-gray-700 truncate">{{ dir.label }}</span>
                  <span class="ml-auto text-xs text-gray-400 flex-shrink-0">{{ dir.files.length }} 个文件</span>
                </button>
                <div v-if="expandedDirs.has(dir.name)" class="divide-y divide-gray-100">
                  <div
                    v-for="file in dir.files"
                    :key="file.relativePath"
                    class="flex items-center gap-2.5 px-4 py-2 hover:bg-gray-50 transition-colors"
                  >
                    <component :is="getFileIcon(file.baseName)" class="w-4 h-4 text-gray-500 flex-shrink-0" />
                    <span class="flex-1 text-sm text-gray-800 truncate min-w-0">{{ file.baseName }}</span>
                    <Button
                      size="icon"
                      variant="ghost"
                      class="h-7 w-7 p-0 flex-shrink-0"
                      :disabled="downloadingFile === file.relativePath"
                      @click="downloadSingleFile(file.relativePath)"
                    >
                      <RefreshCw v-if="downloadingFile === file.relativePath" class="h-3.5 w-3.5 animate-spin" />
                      <Download v-else class="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              </div>

              <!-- ── 根目录文件 ── -->
              <template v-if="fileTree.rootFiles.length > 0">
                <div class="mt-2 mb-1 px-1">
                  <span class="text-xs font-medium text-gray-400 uppercase tracking-wide">根目录文件</span>
                </div>
                <div
                  v-for="file in fileTree.rootFiles"
                  :key="file.relativePath"
                  class="flex items-center gap-3 px-3 py-2 rounded-lg border hover:bg-gray-50 transition-colors"
                >
                  <component :is="getFileIcon(file.baseName)" class="w-4 h-4 text-gray-500 flex-shrink-0" />
                  <span class="flex-1 text-sm text-gray-800 truncate min-w-0">{{ file.baseName }}</span>
                  <Button
                    size="icon"
                    variant="ghost"
                    class="h-7 w-7 p-0 flex-shrink-0"
                    :disabled="downloadingFile === file.relativePath"
                    @click="downloadSingleFile(file.relativePath)"
                  >
                    <RefreshCw v-if="downloadingFile === file.relativePath" class="h-3.5 w-3.5 animate-spin" />
                    <Download v-else class="h-3.5 w-3.5" />
                  </Button>
                </div>
              </template>
            </div>
          </ScrollArea>
          <div class="mt-3 flex items-center justify-between border-t pt-3">
            <span class="text-xs text-slate-400">{{ fileList.length }} 个文件</span>
            <Button size="sm" variant="outline" :disabled="downloadingAll" @click="handleExportFolder">
              <RefreshCw v-if="downloadingAll" class="mr-1.5 h-3.5 w-3.5 animate-spin" />
              <Archive v-else class="mr-1.5 h-3.5 w-3.5" />
              {{ downloadingAll ? '打包中...' : '全部下载 (zip)' }}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>
