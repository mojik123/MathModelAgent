<script setup lang="ts">
import type { TaskRuntimeStatus } from "@/apis/commonApi";
import { useFilePreview } from "@/composables/useFilePreview";
import { useApiKeyStore } from "@/stores/apiKeys";
import { useTaskStore } from "@/stores/task";
import { getArtifactDisplayInfo } from "@/utils/artifactDisplay";
import { AgentType } from "@/utils/enum";
import { resolveTaskImageUrl } from "@/utils/markdown";
import type {
	Message,
	MessageAction,
	MessageFlow,
	OutputItem,
	ToolMessage,
} from "@/utils/response";
import {
	CheckCircle2,
	ChevronDown,
	CircleAlert,
	CircleX,
	Clock3,
	Code2,
	Download,
	FileText,
	FolderOpen,
	Layers,
	ListChecks,
	LoaderCircle,
	PenLine,
	Settings2,
	TerminalSquare,
	UserRound,
	Wrench,
} from "lucide-vue-next";
import { marked } from "marked";
import {
	computed,
	nextTick,
	onBeforeUnmount,
	onMounted,
	ref,
	watch,
} from "vue";
import { useRoute } from "vue-router";

const props = withDefaults(
	defineProps<{
		messages: Message[];
		taskStatus?: TaskRuntimeStatus;
		collapsed?: boolean;
	}>(),
	{ taskStatus: "ready" },
);

const emit = defineEmits<{ "toggle-collapse": [] }>();

type ActionStatus = "running" | "done" | "warning" | "error" | "pending";
type ActionKind =
	| "user"
	| "system"
	| "progress"
	| "agent"
	| "tool"
	| "file"
	| "output";

interface AgentAction {
	id: string;
	kind: ActionKind;
	title: string;
	detail: string;
	status: ActionStatus;
	timestamp: number;
	timeLabel: string;
	durationMs: number;
	agent: string;
	groupId?: string;
	meta?: string;
	files?: string[];
	content?: string;
	codePreview?: string;
	streamState?: "streaming" | "complete" | null;
	coordination?: string;
	flow?: MessageFlow;
	localAction?: boolean;
}

interface AgentGroup {
	id: string;
	name: string;
	role: string;
	status: ActionStatus;
	actions: AgentAction[];
	durationMs: number;
	lastAction?: AgentAction;
	fileCount: number;
}

const scrollRef = ref<HTMLDivElement | null>(null);
const now = ref(Date.now());
const visibleActionIds = ref<string[]>([]);
const pendingActionIds = ref<string[]>([]);
const expandedActions = ref<Set<string>>(new Set());
const newActionIds = ref<Set<string>>(new Set());
const pulseGroupIds = ref<Set<string>>(new Set());
const { openPreview, buildFileUrl } = useFilePreview();
const taskStore = useTaskStore();
const route = useRoute();
const currentTaskId = computed(
	() =>
		taskStore.currentTaskId ||
		(typeof route.params.task_id === "string" ? route.params.task_id : "") ||
		window.localStorage.getItem("currentTaskId") ||
		"",
);

// 手动开合状态表 — 只有用户点击 summary 才会改变
const manualOpenDetailIds = ref<Set<string>>(new Set());

const detailKey = (scope: string, id: string | number) =>
	`${currentTaskId.value || "current"}:${scope}:${id}`;

const isDetailOpen = (scope: string, id: string | number) =>
	manualOpenDetailIds.value.has(detailKey(scope, id));

const toggleDetailOpen = (scope: string, id: string | number) => {
	const key = detailKey(scope, id);
	const next = new Set(manualOpenDetailIds.value);
	if (next.has(key)) {
		next.delete(key);
	} else {
		next.add(key);
	}
	manualOpenDetailIds.value = next;
};

const userScrolledUp = ref(false);
let autoScrollTimeout: ReturnType<typeof setTimeout> | null = null;
let timer: ReturnType<typeof setInterval> | null = null;
let revealTimer: ReturnType<typeof setTimeout> | null = null;
let revealBurstCount = 0;
let fastReplayUntil = Date.now() + 1200;
const groupScrollRefs = new Map<string, HTMLDivElement>();

const terminalSystemTypes = new Set(["success", "warning", "error"]);

const isTerminalMessage = (message: Message) =>
	message.msg_type === "system" &&
	message.type != null &&
	terminalSystemTypes.has(message.type);

const terminalTaskStatuses = new Set<TaskRuntimeStatus>([
	"completed",
	"failed",
	"interrupted",
	"stopped",
]);

const isWorkflowTerminal = computed(() => {
	if (terminalTaskStatuses.has(props.taskStatus ?? "ready")) return true;

	const runtimeProgress = taskStore.taskRuntimeState?.progress;
	const currentProgress = taskStore.currentProgress?.percentage;

	if ((runtimeProgress ?? currentProgress ?? 0) >= 100) return true;

	return false;
});

const isTaskActive = computed(
	() =>
		!isWorkflowTerminal.value &&
		props.taskStatus !== "ready" &&
		props.taskStatus !== "completed" &&
		props.taskStatus !== "failed" &&
		props.taskStatus !== "interrupted" &&
		props.taskStatus !== "stopped",
);

const runtimeCurrentText = computed(
	() =>
		taskStore.currentProgress?.description ??
		taskStore.taskRuntimeState?.current_step ??
		taskStore.taskRuntimeState?.message ??
		"",
);

const inferActiveGroupFromText = (text: string): string | null => {
	if (!text) return null;
	// 优先匹配带索引的组（如 "[组#1] 正在求解"）
	const idxMatch = text.match(/\[组#(\d+)\]/);
	if (idxMatch) {
		const idx = idxMatch[1];
		if (/代码手|求解|Coder/.test(text)) return `q${idx}.coder.main`;
		if (/论文手|撰写|写作|Writer/.test(text)) return `q${idx}.writer`;
		if (/SubCoordinator|组协调|协调/.test(text))
			return `q${idx}.sub_coordinator`;
		if (/建模手|Modeler/.test(text)) return `q${idx}.modeler`;
	}
	if (/建模|Modeler/.test(text)) return "modeler";
	if (/代码|求解|执行|Coder/.test(text)) return "coder";
	if (/论文|撰写|Writer/.test(text)) return "writer";
	if (/协调|规划|Coordinator/.test(text)) return "coordinator";
	return null;
};

const paperSections = [
	{ id: "firstPage", label: "封面与摘要" },
	{ id: "RepeatQues", label: "问题重述" },
	{ id: "analysisQues", label: "问题分析" },
	{ id: "modelAssumption", label: "模型假设" },
	{ id: "symbol", label: "符号说明" },
	{ id: "judge", label: "模型评价" },
];

const agentNameMap: Record<string, string> = {
	[AgentType.COORDINATOR]: "CoordinatorAgent",
	[AgentType.SUB_COORDINATOR]: "SubCoordinatorAgent",
	[AgentType.MODELER]: "ModelerAgent",
	[AgentType.CODER]: "CoderAgent",
	[AgentType.WRITER]: "WriterAgent",
};

/** 根据 agent_type 和 agent_index 生成带组号的显示名称 */
const agentDisplayName = (
	agentType: string,
	agentIndex: number | null | undefined,
): string => {
	const base = agentNameMap[agentType] ?? agentType;
	if (agentIndex != null && agentIndex > 0) {
		const shortName: Record<string, string> = {
			CoderAgent: "代码手",
			WriterAgent: "写作手",
			ModelerAgent: "建模手",
			SubCoordinatorAgent: "组协调者",
		};
		const short = shortName[base];
		return short
			? `${base} (#${agentIndex} · ${short}${agentIndex})`
			: `${base} #${agentIndex}`;
	}
	return base;
};

/** 统一 groupId：agentType → 短名，带编号 */
const normalizeGroupId = (
	agentType: string,
	agentIndex: number | null | undefined,
	msg?: any,
): string => {
	if (msg?.agent_instance_id) return msg.agent_instance_id;
	if (msg?.group_id) return msg.group_id;
	const typeMap: Record<string, string> = {
		[AgentType.COORDINATOR]: "coordinator",
		[AgentType.SUB_COORDINATOR]: "sub_coordinator",
		[AgentType.MODELER]: "modeler",
		[AgentType.CODER]: "coder",
		[AgentType.WRITER]: "writer",
	};
	const base = typeMap[agentType] ?? String(agentType).toLowerCase();
	return agentIndex != null ? `${base}_${agentIndex}` : base;
};

const phaseLabelMap: Record<string, string> = {
	eda: "数据探索 EDA",
	sensitivity_analysis: "敏感性分析",
	firstPage: "封面与摘要",
	RepeatQues: "问题重述",
	analysisQues: "问题分析",
	modelAssumption: "模型假设",
	symbol: "符号说明",
	judge: "模型评价",
};

const keyLabel = (key: string) =>
	phaseLabelMap[key] ??
	paperSections.find((section) => section.id === key)?.label ??
	(key ? key.toUpperCase() : "当前阶段");

const formatActionTitle = (action: MessageAction) =>
	`${action.verb.trim()}：${action.object.trim()}`;

const groupIdFromParticipant = (
	participant?: string | null,
	agentIndex?: number | null,
) => {
	const text = participant ?? "";
	if (/User|用户/i.test(text)) return "user";
	if (/System|系统/i.test(text)) return "system";
	if (/SubCoordinator/i.test(text)) {
		return agentIndex != null ? `q${agentIndex}.sub_coordinator` : "coordinator";
	}
	if (/Coordinator/i.test(text)) return "coordinator";
	if (/Modeler/i.test(text)) {
		return agentIndex != null ? `q${agentIndex}.modeler` : "modeler";
	}
	if (/Coder/i.test(text)) {
		return agentIndex != null ? `q${agentIndex}.coder.main` : "coder";
	}
	if (/Writer/i.test(text)) {
		return agentIndex != null ? `q${agentIndex}.writer` : "writer";
	}
	return "";
};

const participantLabel = (participant?: string | null) => {
	const text = participant ?? "";
	if (/^user$/i.test(text) || text === "用户") return "User";
	if (/^system$/i.test(text) || text === "系统") return "System";
	if (/Coordinator/i.test(text)) return "CoordinatorAgent";
	if (/Modeler/i.test(text)) return "ModelerAgent";
	if (/Coder/i.test(text)) return "CoderAgent";
	if (/Writer/i.test(text)) return "WriterAgent";
	return text;
};

// ---- 系统消息解析 ----

const isDoneText = (text: string) =>
	/任务处理完成|任务已完成|任务已停止|已完成|已停止/i.test(text);

interface NormalizedSystemAction {
	title: string;
	detail: string;
	agent: string;
	kind: ActionKind;
	coordination?: string;
	flow?: MessageFlow;
	groupId?: string;
}

const normalizeSystemAction = (
	content: string,
	_type?: string | null,
	lastAgentName = "",
): NormalizedSystemAction | null => {
	if (!content || !content.trim()) return null;
	const firstLine = content.split("\n")[0].trim();
	const key = extractFlowKey(firstLine);
	const label = keyLabel(key);

	// 协调员分派任务
	const dispatch = firstLine.match(
		/→\s*(CoordinatorAgent|ModelerAgent|CoderAgent|WriterAgent)/,
	);
	if (dispatch) {
		const target = dispatch[1];
		return {
			title: "传递：工作指令",
			detail: content,
			agent: "System",
			kind: "system",
			coordination: target,
			flow: {
				from: "System",
				to: target,
				label: firstLine.replace(/^.*?→\s*/, "").trim() || "分配任务",
			},
		};
	}

	if (/图片修订/.test(firstLine)) {
		return {
			title: firstLine.includes("完成")
				? "完成：图片修订"
				: firstLine.includes("失败")
					? "失败：图片修订"
					: "执行：图片修订",
			detail: content,
			agent: "WriterAgent",
			kind: "agent",
			flow: firstLine.includes("启动")
				? { from: "User", to: "WriterAgent", label: "请求修改图片" }
				: firstLine.includes("完成")
					? { from: "WriterAgent", to: "User", label: "返回图片修订结果" }
					: undefined,
		};
	}

	if (/文本修订/.test(firstLine)) {
		return {
			title: firstLine.includes("完成")
				? "完成：文本修订"
				: firstLine.includes("失败")
					? "失败：文本修订"
					: "执行：文本修订",
			detail: content,
			agent: "WriterAgent",
			kind: "agent",
			flow: firstLine.includes("启动")
				? { from: "User", to: "WriterAgent", label: "请求修改文本" }
				: firstLine.includes("完成")
					? { from: "WriterAgent", to: "User", label: "返回文本修订结果" }
					: undefined,
		};
	}

	if (firstLine.includes("任务转交给建模手")) {
		return {
			title: "传递：问题结构",
			detail: content,
			agent: "CoordinatorAgent",
			kind: "agent",
			flow: {
				from: "CoordinatorAgent",
				to: "ModelerAgent",
				label: "移交建模任务",
			},
		};
	}

	if (
		/识别用户意图|拆解问题|协调者正在|问题拆解完成|问题格式校验/.test(firstLine)
	) {
		return {
			title: /完成/.test(firstLine) ? "拆解：任务问题" : "分析：题目结构",
			detail: content,
			agent: "CoordinatorAgent",
			kind: "agent",
			flow: /问题拆解完成/.test(firstLine)
				? {
						from: "CoordinatorAgent",
						to: "ModelerAgent",
						label: "输出问题拆解",
					}
				: undefined,
		};
	}

	if (/建模手|建模方案格式校验/.test(firstLine)) {
		if (firstLine.includes("分析完成")) {
			return {
				title: "传递：建模方案",
				detail: content,
				agent: "ModelerAgent",
				kind: "agent",
				flow: {
					from: "ModelerAgent",
					to: "CoderAgent",
					label: "提交求解方案",
				},
			};
		}
		return {
			title: /校验/.test(firstLine) ? "检查：建模方案格式" : "比选：建模方案",
			detail: content,
			agent: "ModelerAgent",
			kind: "agent",
		};
	}

	if (
		/代码手|开始执行代码|代码执行完成|创建代码沙盒|创建完成|初始化代码手|超过最大重试次数/.test(
			firstLine,
		)
	) {
		let title = "运行：求解代码";
		let flow: MessageFlow | undefined;

		if (firstLine.includes("代码手开始求解")) {
			title = `求解：${label}`;
			flow = {
				from: "ModelerAgent",
				to: "CoderAgent",
				label: `下达${label}求解`,
			};
		} else if (firstLine.includes("代码手求解成功")) {
			title = `返回：${label}求解结果`;
			flow = {
				from: "CoderAgent",
				to: "WriterAgent",
				label: `提交${label}结果`,
			};
		} else if (firstLine.includes("代码手调用")) {
			const tool =
				firstLine.match(/代码手调用(.+?)工具/)?.[1]?.trim() || "工具";
			title = `调用：${tool}工具`;
		} else if (firstLine.includes("开始执行代码")) {
			title = "运行：代码块";
		} else if (firstLine.includes("代码执行完成")) {
			title = "返回：代码执行结果";
		} else if (firstLine.includes("代码手反思纠正错误")) {
			title = "修正：代码错误";
		} else if (firstLine.includes("代码手完成任务")) {
			title = "完成：代码任务";
		} else if (firstLine.includes("初始化代码手")) {
			title = "初始化：代码手";
		} else if (firstLine.includes("创建代码沙盒")) {
			title = "创建：代码沙盒";
		} else if (firstLine.includes("创建完成")) {
			title = "完成：代码沙盒创建";
		} else if (firstLine.includes("超过最大重试次数")) {
			title = "停止：代码重试";
		} else if (/代码手.*编写代码|代码手.*生成代码/.test(firstLine)) {
			title = "编写：代码块";
		}
		return {
			title,
			detail: content,
			agent: "CoderAgent",
			kind: "agent",
			flow,
		};
	}

	if (/论文手|写作手|已生成图片描述|论文生成完成/.test(firstLine)) {
		let title = "撰写：论文内容";
		let flow: MessageFlow | undefined;
		if (firstLine.includes("论文手开始写")) {
			title = `撰写：${label}`;
			flow = {
				from: "CoderAgent",
				to: "WriterAgent",
				label: `移交${label}结果`,
			};
		} else if (firstLine.includes("论文手完成")) {
			title = `返回：${label}草稿`;
			flow = {
				from: "WriterAgent",
				to: "System",
				label: `提交${label}草稿`,
			};
		} else if (firstLine.includes("并行写作启动")) {
			title = "启动：并行写作";
		} else if (firstLine.includes("开始终稿整体检查")) {
			title = "检查：论文终稿";
		} else if (firstLine.includes("完成终稿整体检查")) {
			title = "完成：论文终稿检查";
			flow = {
				from: "WriterAgent",
				to: "User",
				label: "交付终稿",
			};
		} else if (firstLine.includes("写作手调用")) {
			const tool =
				firstLine.match(/写作手调用(.+?)工具/)?.[1]?.trim() || "工具";
			title = `调用：${tool}工具`;
		} else if (firstLine.includes("已生成图片描述")) {
			title = "生成：图片描述";
		} else if (firstLine.includes("论文生成完成")) {
			title = "完成：论文生成";
		}
		return {
			title,
			detail: content,
			agent: "WriterAgent",
			kind: "agent",
			flow,
		};
	}

	// SubCoordinator / 并行组协调消息
	if (/子问题组#\d+\s*(启动|完成|协调)/.test(firstLine)) {
		const idxMatch = firstLine.match(/组#(\d+)/);
		const idx = idxMatch ? idxMatch[1] : "";
		const isStart = /启动/.test(firstLine);
		const isDone = /完成/.test(firstLine);
		const title = isStart
			? `启动：子问题组 #${idx}`
			: isDone
				? `完成：子问题组 #${idx}`
				: `协调：子问题组 #${idx}`;
		return {
			title,
			detail: content,
			agent: `SubCoordinatorAgent #${idx}`,
			kind: "agent",
			groupId: idx ? `q${idx}.sub_coordinator` : undefined,
			flow: isDone
				? {
						from: `SubCoordinatorAgent #${idx}`,
						to: "WriterAgent",
						label: `提交组 #${idx} 结果`,
					}
				: isStart
					? {
							from: "CoordinatorAgent",
							to: `SubCoordinatorAgent #${idx}`,
							label: `分配子问题 #${idx}`,
						}
					: undefined,
		};
	}

	if (
		/全局协调者.*启动/.test(firstLine) ||
		/全局协调者.*完成|汇总/.test(firstLine)
	) {
		const isDone = /完成|汇总/.test(firstLine);
		return {
			title: isDone ? "汇总：子问题组结果" : "启动：全局协调",
			detail: content,
			agent: "CoordinatorAgent",
			kind: "agent",
			flow: isDone
				? {
						from: "CoordinatorAgent",
						to: "WriterAgent",
						label: "整合全部求解结果",
					}
				: undefined,
		};
	}

	if (firstLine.includes("启动 EDA")) {
		return {
			title: "启动：数据探索",
			detail: content,
			agent: "CoordinatorAgent",
			kind: "agent",
			flow: {
				from: "CoordinatorAgent",
				to: "CoderAgent",
				label: "启动 EDA 分析",
			},
		};
	}
	if (firstLine.includes("开始灵敏度分析")) {
		return {
			title: "启动：灵敏度分析",
			detail: content,
			agent: "CoordinatorAgent",
			kind: "agent",
			flow: {
				from: "CoordinatorAgent",
				to: "CoderAgent",
				label: "启动灵敏度分析",
			},
		};
	}
	if (firstLine.includes("并行写作启动")) {
		return {
			title: "启动：并行写作",
			detail: content,
			agent: "CoordinatorAgent",
			kind: "agent",
			flow: {
				from: "CoordinatorAgent",
				to: "WriterAgent",
				label: "分发写作任务",
			},
		};
	}
	if (firstLine.includes("集成协调者")) {
		return {
			title: "整合：论文终稿",
			detail: content,
			agent: "CoordinatorAgent",
			kind: "agent",
			flow: {
				from: "CoordinatorAgent",
				to: "WriterAgent",
				label: "启动终稿整合",
			},
		};
	}

	// ── 问题划分讨论 ───────────────────────────────────────────
	if (firstLine.includes("等待用户确认问题划分")) {
		return {
			title: "等待：确认问题划分",
			detail: content,
			agent: "System",
			kind: "system",
			flow: { from: "CoordinatorAgent", to: "User", label: "请求确认问题" },
		};
	}
	if (firstLine.includes("问题划分已确认")) {
		return {
			title: "确认：问题划分",
			detail: content,
			agent: "System",
			kind: "system",
			flow: { from: "User", to: "CoordinatorAgent", label: "确认问题划分" },
		};
	}
	if (firstLine.includes("从断点恢复：已复用问题划分")) {
		return {
			title: "恢复：问题划分",
			detail: content,
			agent: "System",
			kind: "system",
		};
	}
	// ── 模型候选生成 ───────────────────────────────────────────
	if (/正在结合题目和联网检索|模型候选方案生成完成/.test(firstLine)) {
		const isDone = firstLine.includes("生成完成");
		return {
			title: isDone ? "完成：模型候选生成" : "检索：建模方法",
			detail: content,
			agent: "ModelerAgent",
			kind: "agent",
			flow: isDone
				? { from: "ModelerAgent", to: "User", label: "候选模型就绪" }
				: { from: "ModelerAgent", to: "System", label: "联网检索方法" },
		};
	}
	if (/正在为第\s*\d+\s*问检索|正在为第\s*\d+\s*问生成候选/.test(firstLine)) {
		return {
			title: /检索/.test(firstLine) ? "检索：文献资料" : "生成：候选模型",
			detail: content,
			agent: "ModelerAgent",
			kind: "agent",
		};
	}
	if (firstLine.includes("等待用户确认各问建模方案")) {
		return {
			title: "等待：用户确认方案",
			detail: content,
			agent: "System",
			kind: "system",
			flow: {
				from: "ModelerAgent",
				to: "User",
				label: "请求确认模型",
			},
		};
	}

	if (firstLine.includes("建模方案已确认")) {
		return {
			title: "启动：正式建模",
			detail: content,
			agent: "System",
			kind: "system",
			flow: {
				from: "User",
				to: "ModelerAgent",
				label: "返回确认方案",
			},
		};
	}

	if (
		/任务已创建|任务开始处理|任务处理完成|任务已停止|任务执行失败|停止指令已发送/.test(
			firstLine,
		)
	) {
		const isComplete = firstLine.includes("完成");
		const isStop = firstLine.includes("停止") || firstLine.includes("失败");
		return {
			title: isComplete
				? "完成：任务流程"
				: isStop
					? "更新：任务流程"
					: "启动：任务流程",
			detail: content,
			agent: "System",
			kind: "system",
			flow: isComplete
				? { from: "System", to: "User", label: "任务处理完毕" }
				: isStop
					? { from: "User", to: "System", label: "终止任务" }
					: { from: "User", to: "System", label: "启动任务" },
		};
	}

	if (lastAgentName && lastAgentName !== "System") {
		return {
			title: `记录：${firstLine.length > 28 ? `${firstLine.slice(0, 28)}…` : firstLine}`,
			detail: content,
			agent: lastAgentName,
			kind: "agent",
		};
	}

	return {
		title: `记录：${firstLine.length > 28 ? `${firstLine.slice(0, 28)}…` : firstLine}`,
		detail: content,
		agent: "System",
		kind: "system",
	};
};

const extractFlowKey = (content: string) => {
	const direct = content.match(/\b(ques\d+|eda|sensitivity_analysis)\b/i);
	if (direct) return direct[1];
	const map: Record<string, string> = {
		封面: "firstPage",
		摘要: "firstPage",
		重述: "RepeatQues",
		分析: "analysisQues",
		假设: "modelAssumption",
		符号: "symbol",
		评价: "judge",
	};
	for (const [k, v] of Object.entries(map)) {
		if (content.includes(k)) return v;
	}
	return "";
};

const firstUsefulSentence = (text: string, maxLen = 60) => {
	const lines = text.split("\n");
	for (const line of lines) {
		const cleaned = line
			.replace(/^#{1,4}\s+|^[-*]\s+|^\d+\.\s*|^>\s*|^\|.*\|\s*$/g, "")
			.trim();
		if (
			!cleaned ||
			cleaned.startsWith("\\\\") ||
			cleaned.startsWith("![") ||
			cleaned.startsWith("<")
		)
			continue;
		if (/^(图\d|[【\[]|\*\*|__)/.test(cleaned)) continue;
		if (cleaned.length < 8) continue;
		if (cleaned.length <= maxLen) return cleaned;
		return `${cleaned.slice(0, maxLen)}…`;
	}
	return "";
};

const writerSectionLabel = (message: {
	sub_title?: string;
	content?: string | null;
}) => {
	if (message.sub_title) {
		return (
			phaseLabelMap[message.sub_title] ??
			paperSections.find((s) => s.id === message.sub_title)?.label ??
			message.sub_title
		);
	}
	const content = message.content ?? "";
	const h = content.match(/^#{1,4}\s+(.+)$/m)?.[1]?.trim();
	return h ?? "论文内容";
};

interface WriterFacts {
	keywords: string[];
	imageRefs: string[];
	formulaCount: number;
	tableCount: number;
	files: string[];
	wordCount: number;
}

const writerFacts = (content: string): WriterFacts => {
	const keywords = Array.from(
		new Set(
			(content.match(/\*\*([^*]+)\*\*/g) ?? [])
				.map((t) => t.replace(/\*\*/g, "").trim())
				.filter(Boolean),
		),
	);
	const imageRefs = Array.from(
		new Set(
			Array.from(content.matchAll(/!\[([^\]]*)\]/g))
				.map((m) => m[1].trim())
				.filter(Boolean),
		),
	);
	const formulaCount = (content.match(/\$\$|\\begin\{/g) ?? []).length;
	const tableCount = (content.match(/\|.*\|.*\|/g) ?? []).length;
	const files = Array.from(
		new Set(
			Array.from(content.matchAll(/[\w.-]+\.[a-z]{2,4}\b/gi))
				.map((m) => m[0])
				.filter((f) =>
					/\.(csv|xlsx?|png|jpg|jpeg|svg|py|md|json|tex|txt|pdf)\b/i.test(f),
				),
		),
	);
	const wordCount = content
		.replace(/[#*\-_\[\]()\\`>|\s]+/g, " ")
		.trim()
		.split(/\s+/).length;
	return { keywords, imageRefs, formulaCount, tableCount, files, wordCount };
};

const runtimeWorkText = (groupId: string) => {
	if (/^sub_coordinator_\d+$/.test(groupId)) {
		const idx = groupId.split("_").pop();
		return `组 #${idx} 协调者，正在统筹该组任务`;
	}
	if (/^coder_\d+$/.test(groupId)) {
		const idx = groupId.split("_").pop();
		return `代码手 #${idx}，正在求解子问题`;
	}
	if (/^writer_\d+$/.test(groupId)) {
		const idx = groupId.split("_").pop();
		return `写作手 #${idx}，正在撰写论文段落`;
	}
	if (/^modeler_\d+$/.test(groupId)) {
		const idx = groupId.split("_").pop();
		return `建模手 #${idx}，正在细化建模方案`;
	}
	const map: Record<string, string> = {
		coordinator: "接收命令，正在分析题目",
		modeler: "接收命令，正在比选方案",
		coder: "接收命令，正在求解模型",
		writer: "接收命令，正在撰写论文",
	};
	return map[groupId] ?? "接收命令，正在执行";
};

const groupOrder = [
	"system",
	"user",
	"coordinator",
	"modeler",
	"coder",
	"writer",
];

/** 获取 groupMeta，支持动态索引 group（如 coder_1、writer_2） */
const getGroupMeta = (
	groupId: string,
): { name: string; role: string; model?: string } => {
	const apiKeyStore = useApiKeyStore();
	const modelInfo = (type: string) => {
		const config = apiKeyStore.getAllAgentConfigs()[type];
		if (!config) return "";
		const apiType = config.apiType || "openai-chat";
		const model = config.modelId || "unknown";
		return `${apiType} / ${model}`;
	};
	const static_meta: Record<string, { name: string; role: string }> = {
		system: { name: "System", role: "空闲，等待流程调度" },
		user: { name: "User", role: "空闲，等待用户操作" },
		coordinator: {
			name: "CoordinatorAgent",
			role: `空闲，等待题目分析  ·  ${modelInfo("coordinator")}`,
		},
		modeler: {
			name: "ModelerAgent",
			role: `空闲，等待建模指令  ·  ${modelInfo("modeler")}`,
		},
		coder: {
			name: "CoderAgent",
			role: `空闲，等待求解指令  ·  ${modelInfo("coder")}`,
		},
		writer: {
			name: "WriterAgent",
			role: `空闲，等待写作指令  ·  ${modelInfo("writer")}`,
		},
		tool: { name: "Tool / File", role: "空闲，等待工具调用" },
	};
	const paperWriterMatch = groupId.match(/^paper\.writer\.(.+)$/);
	if (paperWriterMatch) {
		const key = paperWriterMatch[1];
		const sectionName =
			phaseLabelMap[key] ??
			paperSections.find((s) => s.id === key)?.label ??
			key;
		return {
			name: `论文写作 · ${sectionName}`,
			role: `负责终稿章节「${sectionName}」并行写作`,
		};
	}

	if (static_meta[groupId]) return static_meta[groupId];

	// 新格式 q1.coder.r2
	const parsed = parseGroupId(groupId);
	if (parsed) {
		const qIdx = parsed.index;
		const role = parsed.role;

		const attemptLabel =
			parsed.attemptKind === "main"
				? "主力"
				: parsed.attemptKind === "backup"
					? `备用${parsed.attemptIndex}`
					: parsed.attemptKind === "race"
						? `竞速${parsed.attemptIndex}`
						: "";

		const nameMap: Record<QuestionRole, string> = {
			sub_coordinator: `Q${qIdx} · SubCoordinatorAgent`,
			modeler: `Q${qIdx} · ModelerAgent`,
			coder: `Q${qIdx} · CoderAgent${attemptLabel ? ` ${attemptLabel}` : ""}`,
			writer: `Q${qIdx} · WriterAgent`,
		};

		const roleMap: Record<QuestionRole, string> = {
			sub_coordinator: `负责第 ${qIdx} 问任务协调  ·  ${modelInfo("coordinator")}`,
			modeler: `负责第 ${qIdx} 问建模细化  ·  ${modelInfo("modeler")}`,
			coder: attemptLabel
				? `第 ${qIdx} 问代码求解 · ${attemptLabel}  ·  ${modelInfo("coder")}`
				: `负责第 ${qIdx} 问代码求解  ·  ${modelInfo("coder")}`,
			writer: `负责第 ${qIdx} 问结果撰写  ·  ${modelInfo("writer")}`,
		};

		return {
			name: nameMap[role] ?? groupId,
			role: roleMap[role] ?? "等待执行",
		};
	}

	const idxMatch = groupId.match(
		/^(sub_coordinator|modeler|coder|writer)_(\d+)$/,
	);
	if (idxMatch) {
		const [, type, idx] = idxMatch;
		const nameMap: Record<string, string> = {
			sub_coordinator: "SubCoordinatorAgent",
			modeler: "ModelerAgent",
			coder: "CoderAgent",
			writer: "WriterAgent",
		};
		const roleMap: Record<string, string> = {
			sub_coordinator: `协调组 #${idx}，统筹子问题流程`,
			modeler: `建模手 #${idx}，专注子问题建模  ·  ${modelInfo("modeler")}`,
			coder: `代码手 #${idx}，专注子问题求解  ·  ${modelInfo("coder")}`,
			writer: `写作手 #${idx}，专注子问题写作  ·  ${modelInfo("writer")}`,
		};
		return {
			name: `${nameMap[type]} #${idx}`,
			role: roleMap[type] ?? `子问题 #${idx} 专属`,
		};
	}
	return { name: groupId, role: "等待执行" };
};

// 兼容旧代码中直接访问 groupMeta 的地方
const groupMeta: Record<string, { name: string; role: string }> = new Proxy(
	{} as Record<string, { name: string; role: string }>,
	{
		get(_target, key: string) {
			return getGroupMeta(key);
		},
		has(_target, _key) {
			return true;
		},
	},
);

// ---- Helpers ----

const parseTimestamp = (createdAt: string | undefined, fallback: number) => {
	if (!createdAt) return fallback;
	const parsed = Date.parse(createdAt);
	return Number.isNaN(parsed) ? fallback : parsed;
};

const formatClock = (timestamp: number) =>
	new Date(timestamp).toLocaleTimeString("zh-CN", {
		hour: "2-digit",
		minute: "2-digit",
		second: "2-digit",
	});

const formatDuration = (ms: number) => {
	const seconds = Math.max(0, Math.floor(ms / 1000));
	const minutes = Math.floor(seconds / 60);
	const remainingSeconds = seconds % 60;
	if (minutes > 0) return `${minutes}m ${remainingSeconds}s`;
	return `${remainingSeconds}s`;
};

const clipText = (value: string, maxLength = 1800) => {
	if (value.length <= maxLength) return value;
	return `${value.slice(0, maxLength)}\n\n...内容较长，已折叠显示前 ${maxLength} 字`;
};

const toggleExpand = (actionId: string) => {
	const next = new Set(expandedActions.value);
	if (next.has(actionId)) {
		next.delete(actionId);
	} else {
		next.clear();
		next.add(actionId);
	}
	expandedActions.value = next;
	nextTick(() => {
		const el = document.querySelector(`[data-expand-id="${actionId}"]`);
		if (el) el.scrollTop = el.scrollHeight;
	});
};

const escapeHtml = (value: string) =>
	value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const escapeAttr = (value: string) =>
	escapeHtml(value).replace(/"/g, "&quot;").replace(/'/g, "&#39;");

const previewUrlFor = (file: string) => buildFileUrl(file, currentTaskId.value);

const openFilePreview = (file: string) => {
	const info = getArtifactDisplayInfo(file, currentTaskId.value);
	openPreview(previewUrlFor(info.normalizedPath), info.normalizedPath);
};

const artifactDisplayName = (file: string) =>
	getArtifactDisplayInfo(file, currentTaskId.value).fullName;

/** 展开区域图片点击委托 */
function onExpandedClick(e: MouseEvent) {
	const target = e.target as HTMLElement;
	if (target.tagName === "IMG" && target.classList.contains("inline-thumb")) {
		const src = target.getAttribute("src") ?? "";
		const rawPath =
			target.getAttribute("data-artifact-path") ||
			target.getAttribute("alt") ||
			"image.png";
		openPreview(src, rawPath);
		return;
	}
	const fileButton = target.closest<HTMLElement>("[data-preview-file]");
	if (fileButton) {
		const file = fileButton.dataset.previewFile ?? "";
		if (file) openFilePreview(file);
	}
}

/** 渲染内容：图片转为可点击缩略图，文件路径美化为圆角标签 */
function renderContentWithImages(content: string): string {
	const escaped = escapeHtml(content);
	const imageHtml: string[] = [];
	const withImageTokens = escaped.replace(
		/!\[([^\]]*)\]\(([^)]+)\)/g,
		(_match: string, alt: string, src: string) => {
			const imageUrl = resolveTaskImageUrl(src, currentTaskId.value);
			const imageInfo = getArtifactDisplayInfo(src, currentTaskId.value);
			const imageName = imageInfo.fullName || alt || "图片";
			const token = `__INLINE_IMAGE_${imageHtml.length}__`;
			imageHtml.push(
				`<img src="${escapeAttr(imageUrl)}" alt="${escapeAttr(imageName)}" data-artifact-path="${escapeAttr(imageInfo.normalizedPath)}" class="inline-thumb max-w-[200px] max-h-[120px] rounded cursor-pointer hover:opacity-80 transition-opacity border border-white/30" />`,
			);
			return token;
		},
	);
	// 将文件路径美化为蓝色圆角标签，但不匹配已包裹在 HTML 标签内的内容
	return withImageTokens
		.replace(
			/(?<![="'>\w])((?:[\w-]+\/)*[\w-]+\.(?:py|md|ipynb|tex|json|toml|txt|csv|xlsx|yaml|yml|cfg|ini|pdf|bib|sh|R))\b/gi,
			(_match: string, file: string) =>
				`<button type="button" class="file-action-chip chip-blue cursor-pointer underline decoration-current/40 underline-offset-2" data-preview-file="${escapeAttr(file)}">${escapeHtml(getArtifactDisplayInfo(file, currentTaskId.value).fullName)}</button>`,
		)
		.replace(
			/__INLINE_IMAGE_(\d+)__/g,
			(_match: string, index: string) => imageHtml[Number(index)] ?? "",
		);
}

/** 判断文件操作是否为写入/保存类型 */
const isWriteAction = (title: string) =>
	/写入|保存|修改|write|save/i.test(title);

/** 返回文件芯片的 CSS 类名 */
const chipKindClass = (kind: string, title: string) => {
	if (kind === "tool") return "chip-violet";
	if (kind === "output") return "chip-green";
	if (kind === "file" && isWriteAction(title)) return "chip-amber";
	return "chip-blue";
};

/** 解析文件动作标题，拆出动词和文件名 */
const parseFileActionTitle = (title: string) => {
	const match = title.match(/^(.+?):\s+(.+)$/);
	return match ? { verb: match[1].trim(), filename: match[2].trim() } : null;
};

const parseToolActionTitle = (title: string) =>
	title.match(/^调用：工具\s+(.+)$/)?.[1]?.trim() ?? "";

const actionVerbClass = (action: AgentAction) => {
	if (action.kind === "user") return "action-verb-user";
	if (action.kind === "system" || action.kind === "progress")
		return "action-verb-system";
	if (action.kind === "tool") return "action-verb-tool";
	if (action.kind === "file") return "action-verb-file";
	if (action.kind === "output") return "action-verb-output";
	if (/WriterAgent/.test(action.agent)) return "action-verb-writer";
	if (/CoderAgent/.test(action.agent)) return "action-verb-coder";
	if (/ModelerAgent/.test(action.agent)) return "action-verb-modeler";
	if (/SubCoordinatorAgent/.test(action.agent))
		return "action-verb-sub-coordinator";
	if (/CoordinatorAgent/.test(action.agent)) return "action-verb-coordinator";
	return "action-verb-default";
};

/** 解析 Agent 动作标题，拆出动词和内容 */
const parseAgentActionTitle = (title: string) => {
	const verbPattern =
		"提交|选择|确认|应用|询问|修改|打开|启动|停止|继续|重画|传递|返回|接收|拆解|分析|比选|建立|生成|编写|运行|求解|调用|读取|写入|保存|整理|解读|撰写|检查|更新|完成|扫描|修正|创建|初始化|等待|记录";
	const match = title.match(new RegExp(`^(${verbPattern})(?:：|:)?\\s*(.+)$`));
	if (match) return { verb: match[1].trim(), content: match[2].trim() };
	return null;
};

const coordinationLabel = (target?: string) => {
	if (target === "modeler") return "ModelerAgent";
	if (target === "coder") return "CoderAgent";
	if (target === "writer") return "WriterAgent";
	return participantLabel(target);
};

const actionTitleChipClass = (action: AgentAction) => {
	if (action.flow || action.coordination)
		return "action-title-chip action-title-flow";
	if (action.kind === "tool") return "action-title-chip action-title-tool";
	if (action.kind === "output") return "action-title-chip action-title-output";
	if (action.kind === "file") return "action-title-chip action-title-file";
	if (action.kind === "progress")
		return "action-title-chip action-title-progress";
	if (action.kind === "user") return "action-title-chip action-title-user";
	if (/WriterAgent/.test(action.agent))
		return "action-title-chip action-title-writer";
	if (/CoderAgent/.test(action.agent))
		return "action-title-chip action-title-coder";
	if (/ModelerAgent/.test(action.agent))
		return "action-title-chip action-title-modeler";
	if (/SubCoordinatorAgent/.test(action.agent))
		return "action-title-chip action-title-sub-coordinator";
	if (/CoordinatorAgent/.test(action.agent))
		return "action-title-chip action-title-coordinator";
	return "action-title-chip action-title-default";
};

const summarizeAgentContent = (message: Message) => {
	if (message.msg_type !== "agent") return message.content ?? "";
	if (message.action?.detail) return message.action.detail;
	const content = message.content ?? "";
	const compact = content
		.replace(/```[\s\S]*?```/g, " ")
		.replace(/[#>*_\-`]/g, " ")
		.replace(/\s+/g, " ")
		.trim();
	const heading =
		content.match(/^#{1,4}\s+(.+)$/m)?.[1]?.trim() ??
		content
			.match(
				/^(?:第[一二三四五六七八九十\d]+[章节问]|问题\s*\d+)[^\n。]*/m,
			)?.[0]
			?.trim() ??
		"";
	const files = Array.from(
		new Set(
			Array.from(
				content.matchAll(
					/[\w一-龥.-]+\.(?:csv|xlsx|xls|json|png|jpg|jpeg|svg|py|md|tex)/gi,
				),
			)
				.map((match) => match[0])
				.slice(0, 3),
		),
	);
	const fileText = files.length ? `；涉及 ${files.join("、")}` : "";

	if (message.agent_type === AgentType.COORDINATOR) {
		return heading
			? `拆解：${heading}${fileText}`
			: `拆解题目结构、约束和小问分工${fileText}`;
	}
	if (message.agent_type === AgentType.SUB_COORDINATOR) {
		const idx =
			"agent_index" in message
				? (message as { agent_index?: number | null }).agent_index
				: null;
		const indexTag = idx != null ? ` #${idx}` : "";
		return heading
			? `组协调者${indexTag}：${heading}${fileText}`
			: `统筹子问题组${indexTag} 任务流程${fileText}`;
	}
	if (message.agent_type === AgentType.MODELER) {
		const model =
			compact.match(
				/(?:线性规划|整数规划|动态规划|随机森林|回归|聚类|蒙特卡洛|遗传算法|灰色预测|时间序列|灵敏度分析)/,
			)?.[0] ?? "模型方案";
		return heading
			? `${model}：${heading}${fileText}`
			: `细化${model}、变量、约束和求解步骤${fileText}`;
	}
	if (message.agent_type === AgentType.CODER) {
		const codeMatch = content.match(/```(?:python)?\s*([\s\S]*?)```/i);
		const code = codeMatch?.[1] ?? content;
		const ops: string[] = [];
		if (/read_(?:csv|excel|json|table)|pd\.read_|open\(/.test(code))
			ops.push("读取数据");
		if (/dropna|fillna|isnull|duplicated|清洗|预处理/.test(code))
			ops.push("清洗数据");
		if (/groupby|corr|describe|value_counts|统计|相关/.test(code))
			ops.push("统计分析");
		if (
			/fit\(|predict\(|RandomForest|LinearRegression|LogisticRegression|模型/.test(
				code,
			)
		)
			ops.push("训练/预测模型");
		if (/plt\.|sns\.|savefig|plot\(/.test(code)) ops.push("绘图");
		if (/to_(?:csv|excel|json)|write_text|savefig/.test(code))
			ops.push("保存结果");
		const opText = ops.length
			? ops.slice(0, 4).join("、")
			: heading || compact.slice(0, 42) || "准备代码执行";
		return `${opText}${fileText}`;
	}
	if (message.agent_type === AgentType.WRITER) {
		const section = writerSectionLabel(message);
		const facts = writerFacts(content);
		const pieces = [`生成 ${section}`];
		if (facts.keywords.length)
			pieces.push(facts.keywords.slice(0, 3).join("、"));
		if (facts.imageRefs.length)
			pieces.push(
				`解读 ${facts.imageRefs.length} 张图：${facts.imageRefs.join("、")}`,
			);
		if (facts.formulaCount > 0)
			pieces.push(`整理 ${facts.formulaCount} 处公式/符号`);
		if (facts.tableCount > 0) pieces.push("包含表格说明");
		if (facts.files.length) pieces.push(`引用 ${facts.files.join("、")}`);
		if (facts.wordCount > 0) pieces.push(`约 ${facts.wordCount} 字`);
		const sentence = firstUsefulSentence(content);
		if (sentence) pieces.push(`要点：${sentence}`);
		return pieces.join("；");
	}
	return "";
};

const agentActionTitle = (message: Message) => {
	if (message.msg_type !== "agent") return "";
	if (message.action) return formatActionTitle(message.action);
	const content = message.content ?? "";
	const heading =
		content.match(/^#{1,4}\s+(.+)$/m)?.[1]?.trim() ??
		content.match(
			/(摘要|问题重述|问题分析|模型假设|符号说明|模型建立|模型求解|结果分析|灵敏度分析|模型评价|参考文献)/,
		)?.[0] ??
		"";
	if (message.agent_type === AgentType.CODER) {
		if (/read_(?:csv|excel|json|table)|pd\.read_/.test(content))
			return "编写：数据读取代码";
		if (/dropna|fillna|isnull|duplicated|清洗|预处理/.test(content))
			return "编写：数据清洗代码";
		if (
			/fit\(|predict\(|RandomForest|LinearRegression|LogisticRegression/.test(
				content,
			)
		)
			return "编写：模型训练代码";
		if (/plt\.|sns\.|savefig|plot\(/.test(content)) return "编写：可视化代码";
		return heading ? `编写：${heading}` : "编写：求解代码";
	}
	if (message.agent_type === AgentType.WRITER) {
		const section = writerSectionLabel(message);
		const facts = writerFacts(content);
		if (facts.imageRefs.length) return `解读：${section}图表`;
		if (facts.formulaCount > 0) return `整理：${section}公式`;
		if (/结果|求解|分析|评价|灵敏度/.test(section))
			return `撰写：${section}分析`;
		const sentence = firstUsefulSentence(content, 20);
		return sentence && section === "论文内容"
			? `撰写：${sentence}`
			: `撰写：${section}`;
	}
	if (message.agent_type === AgentType.MODELER)
		return heading ? `建立：${heading}` : "建立：建模方案";
	if (message.agent_type === AgentType.COORDINATOR)
		return heading ? `拆解：${heading}` : "拆解：任务问题";
	if (message.agent_type === AgentType.SUB_COORDINATOR) {
		const idx =
			"agent_index" in message
				? (message as { agent_index?: number | null }).agent_index
				: null;
		const indexTag = idx != null ? ` #${idx}` : "";
		return heading
			? `协调${indexTag}：${heading}`
			: `协调${indexTag}：子问题组`;
	}
	return `输出：${agentNameMap[message.agent_type] ?? message.agent_type} 消息`;
};

	// extractFileActions removed — now using extractArtifactFilesFromToolMessage
	const artifactFilePattern =
		/((?:[\w一-龥.-]+\/)+[\w.-]+\.(?:py|png|jpg|jpeg|svg|webp))/gi;

	const isPreviewImageFile = (file: string) =>
		/\.(png|jpg|jpeg|svg|webp)$/i.test(file);

	const isFullPythonFile = (file: string) =>
		/\.py$/i.test(file);

	const artifactFileDescription = (file: string) => {
		if (isFullPythonFile(file)) {
			const name = file.split(/[\\/]/).pop() || file;
			if (name === "code.py" || /^code_[br]\d+\.py$/i.test(name)) {
				return "本章节完整 Python 汇总代码，可打开查看完整求解流程。";
			}
			if (/_step_\d+\.py$/i.test(name)) {
				return "该步骤保存的完整 Python 文件，可打开查看对应处理过程。";
			}
			return "生成该图或该结果的完整 Python 文件，可打开预览。";
		}

		if (isPreviewImageFile(file)) {
			return "生成的图片结果，可点击打开预览。";
		}

		return "任务生成的文件，可打开预览。";
	};

	const extractArtifactFilesFromToolMessage = (message: ToolMessage) => {
		const text = [
			toolOutputDetail(message),
			toolOutputSummary(message),
		]
			.filter(Boolean)
			.join("\n");

		const files = Array.from(text.matchAll(artifactFilePattern))
			.map((match) => match[1])
			.filter(Boolean);

		const uniqueFiles = Array.from(new Set(files));

		return uniqueFiles
			.filter((file) => isFullPythonFile(file) || isPreviewImageFile(file))
			.map((file) => ({
				file,
				title: isFullPythonFile(file)
					? "保存：Python 文件"
					: "生成：图片预览",
				detail: artifactFileDescription(file),
			}));
	};

const toolDetail = (message: ToolMessage) => {
	const blocks: string[] = [];
	if (message.input) {
		if ("code" in message.input && typeof message.input.code === "string") {
			blocks.push(`执行代码：\n\n\`\`\`python\n${message.input.code}\n\`\`\``);
		} else {
			blocks.push(
				`工具输入：\n\n\`\`\`json\n${JSON.stringify(message.input, null, 2)}\n\`\`\``,
			);
		}
	}
	if (Array.isArray(message.output) && message.output.length > 0) {
		const output = message.output
			.map((item) => {
				if (typeof item === "string") return item;
				const execution = item as OutputItem;
				if (execution.res_type === "error") {
					return `${execution.name}: ${execution.value}\n${execution.traceback ?? ""}`;
				}
				if (
					"format" in execution &&
					(execution.format === "png" || execution.format === "jpeg")
				) {
					return `[${execution.format}] 图像结果已生成`;
				}
				return execution.msg ?? `[${execution.res_type}]`;
			})
			.filter(Boolean)
			.join("\n");
		if (output) blocks.push(`输出结果：\n\n\`\`\`text\n${output}\n\`\`\``);
	}
	return blocks.join("\n\n") || "工具已调用，等待返回结果。";
};

const compactCodePreview = (code: string) =>
	code
		.split("\n")
		.map((line) => line.trimEnd())
		.filter((line) => line.trim() && !line.trim().startsWith("#"))
		.slice(0, 10)
		.join("\n");

const ansiEscapePattern = new RegExp(
	`${String.fromCharCode(27)}\\[[0-9;]*m`,
	"g",
);

const compactOutputText = (value: string | undefined, maxLength = 120) => {
	const text = (value ?? "")
		.replace(ansiEscapePattern, "")
		.replace(/\s+/g, " ")
		.trim();
	if (!text) return "";
	return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
};

const toolOutputItemText = (item: string | OutputItem, maxLength = 120) => {
	if (typeof item === "string") {
		const text = compactOutputText(item, maxLength);
		return text ? `文本输出：${text}` : "空文本输出";
	}
	if (item.res_type === "error") {
		const errorText = compactOutputText(
			`${item.name}: ${item.value}`,
			maxLength,
		);
		return errorText ? `执行错误：${errorText}` : "执行错误";
	}
	if (item.res_type === "stderr") {
		const text = compactOutputText(item.msg, maxLength);
		return text ? `标准错误：${text}` : "标准错误输出";
	}
	if (item.res_type === "stdout") {
		const text = compactOutputText(item.msg, maxLength);
		return text ? `标准输出：${text}` : "标准输出为空";
	}
	if ("format" in item) {
		if (
			item.format === "png" ||
			item.format === "jpeg" ||
			item.format === "svg"
		) {
			return `生成 ${item.format.toUpperCase()} 图像结果`;
		}
		if (item.format === "pdf") return "生成 PDF 文件结果";
		const text = compactOutputText(item.msg, maxLength);
		return text
			? `${item.format.toUpperCase()} 结果：${text}`
			: `${item.format.toUpperCase()} 结果`;
	}
	const text = compactOutputText(item.msg, maxLength);
	return text ? `${item.res_type}：${text}` : item.res_type;
};

const toolOutputDetail = (message: ToolMessage) => {
	if (!Array.isArray(message.output) || message.output.length === 0) return "";
	return message.output
		.map((item, index) => `${index + 1}. ${toolOutputItemText(item, 600)}`)
		.join("\n");
};

const toolOutputSummary = (message: ToolMessage) => {
	if (!Array.isArray(message.output) || message.output.length === 0) return "";
	const items = message.output.map((item) => toolOutputItemText(item, 96));
	if (items.length <= 2) return items.join("；");
	return `${items.slice(0, 2).join("；")}；等 ${items.length} 项`;
};

// ---- Computed ----

// ---- 流式消息节流：避免每个 token 都触发全量重算 ----

const displayMessages = ref<Message[]>([]);
let streamThrottleTimer: ReturnType<typeof setTimeout> | null = null;

watch(
	() => props.messages,
	(msgs) => {
		const hasStreaming = msgs.some(
			(m) =>
				m.msg_type === "agent" &&
				"stream_state" in m &&
				m.stream_state === "streaming",
		);
		if (hasStreaming && !streamThrottleTimer) {
			streamThrottleTimer = setTimeout(() => {
				displayMessages.value = [...msgs];
				streamThrottleTimer = null;
			}, 250);
		} else if (!hasStreaming) {
			if (streamThrottleTimer) {
				clearTimeout(streamThrottleTimer);
				streamThrottleTimer = null;
			}
			displayMessages.value = [...msgs];
		}
	},
	{ deep: true, immediate: true },
);

// 在已有的 onBeforeUnmount 中追加清理（后面单独处理）

const baseTimestamp = computed(() => {
	const firstWithTime = displayMessages.value.find(
		(message) => message.created_at,
	);
	return parseTimestamp(firstWithTime?.created_at, Date.now());
});

const rawActions = computed(() => {
	const actions: AgentAction[] = [];
	let lastAgentName = "";
	let lastAgentGroupId = "";
	// 追踪每个 Agent 的最后一个流式动作，用于合并重复的 streaming 消息
	const lastStreamingAction = new Map<string, AgentAction>();

	displayMessages.value.forEach((message, index) => {
		const timestamp = parseTimestamp(
			message.created_at,
			baseTimestamp.value + index * 1000,
		);
		const timeLabel = formatClock(timestamp);

		if (message.msg_type === "user") {
			const action = message.action;
			actions.push({
				id: message.id,
				kind: "user",
				title: action ? formatActionTitle(action) : "提交：建模任务",
				detail: action?.detail || "提交用户题目、附件说明和需要回答的小问",
				status: "done",
				timestamp,
				timeLabel,
				durationMs: 0,
				agent: "User",
				content: message.content ?? "",
				flow: action?.flow,
				localAction: message.local_action,
			});
			return;
		}

		if (message.msg_type === "progress") {
			actions.push({
				id: message.id,
				kind: "progress",
				title: `更新：执行进度 ${message.percentage}%`,
				detail: message.description,
				status: message.percentage >= 100 ? "done" : "running",
				timestamp,
				timeLabel,
				durationMs: 0,
				agent: "System",
				meta: `${message.current}/${message.total}`,
			});
			return;
		}

		if (message.msg_type === "system") {
			const result = message.action
				? {
						title: formatActionTitle(message.action),
						detail: message.action.detail || (message.content ?? ""),
						flow: message.action.flow,
						agent: "System",
						kind: "system" as ActionKind,
					}
				: normalizeSystemAction(
						message.content ?? "",
						message.type,
						lastAgentName,
					);
			if (!result) return;
			const coordinationTarget = result.coordination;
			const flow = result.flow;
			actions.push({
				id: message.id,
				kind: result.kind,
				title: result.title,
				detail: result.detail,
				status:
					message.type === "error"
						? "error"
						: message.type === "warning"
							? "warning"
							: isDoneText(message.content ?? "")
								? "done"
								: "running",
				timestamp,
				timeLabel,
				durationMs: 0,
				agent: result.agent,
				groupId: result.groupId,
				content: message.content ?? "",
				coordination: coordinationTarget,
				flow,
				localAction: message.local_action,
			});
			lastAgentName = result.agent;
			return;
		}

		if (message.msg_type === "agent") {
			const agentIndex =
				"agent_index" in message
					? (message as { agent_index?: number | null }).agent_index
					: null;
			// 基础类型名（用于 stream key 去重）
			const agentLabel = agentNameMap[message.agent_type] ?? message.agent_type;
			// 带编号的显示名（用于 AgentAction.agent）
			const agentDisplayLabel = agentDisplayName(
				message.agent_type,
				agentIndex,
			);
			const streamState =
				"stream_state" in message
					? (message as { stream_state?: "streaming" | "complete" | null })
							.stream_state
					: null;
			// 流式 key 包含 index，避免不同组的流式消息互相覆盖
			const streamKey =
				agentIndex != null ? `${agentLabel}#${agentIndex}` : agentLabel;
			const title = agentActionTitle(message);
			const content = message.content ?? "";

			// 流式消息：合并到同一个 Agent 实例的已有动作中，避免重复创建
			const existing = lastStreamingAction.get(streamKey);
			if (streamState === "streaming" && existing && existing.title === title) {
				existing.content = content;
				existing.detail = content;
				existing.timestamp = timestamp;
				existing.timeLabel = timeLabel;
				existing.streamState = streamState;
			} else {
				const detail =
					streamState === "streaming"
						? content
						: summarizeAgentContent(message);
				const action: AgentAction = {
					id: message.id,
					kind: "agent",
					title,
					detail,
					status: "running",
					timestamp,
					timeLabel,
					durationMs: 0,
					agent: agentDisplayLabel,
					content,
					streamState,
					flow: message.action?.flow,
					localAction: message.local_action,
					groupId: normalizeGroupId(
						message.agent_type,
						agentIndex,
						message as any,
					),
				};
				actions.push(action);
				if (streamState === "streaming") {
					lastStreamingAction.set(streamKey, action);
				}
			}
			lastAgentName = agentDisplayLabel;
			lastAgentGroupId = normalizeGroupId(
				message.agent_type,
				agentIndex,
				message as any,
			);
			return;
		}

		if (message.msg_type === "tool") {
			const code =
				message.input &&
				"code" in message.input &&
				typeof message.input.code === "string"
					? message.input.code
					: "";

			// 非 execute_code 工具仍然显示工具调用
			if (message.tool_name !== "execute_code") {
				actions.push({
					id: `${message.id}:call`,
					kind: "tool",
					title: `调用：工具 ${message.tool_name}`,
					detail: "发起外部检索或工具查询",
					status:
						Array.isArray(message.output) && message.output.length > 0
							? "done"
							: "running",
					timestamp,
					timeLabel,
					durationMs: 0,
					agent: lastAgentName || "Tool",
					groupId: lastAgentGroupId || "coder",
					content: toolDetail(message),
				});
			}

			// execute_code 只显示真实保存的 .py / 图片文件
			const artifactFiles = extractArtifactFilesFromToolMessage(message);

			artifactFiles.forEach((item, fileIndex) => {
				actions.push({
					id: `${message.id}:artifact:${fileIndex}`,
					kind: "file",
					title: item.title,
					detail: item.detail,
					status: "done",
					timestamp: timestamp + fileIndex + 1,
					timeLabel,
					durationMs: 0,
					agent: lastAgentName || "File",
					files: [item.file],
					groupId: lastAgentGroupId || "coder",
				});
			});

			// 错误结果仍然保留
			const hasError =
				Array.isArray(message.output) &&
				message.output.some(
					(item) =>
						typeof item !== "string" &&
						item &&
						"res_type" in item &&
						item.res_type === "error",
				);

			if (hasError && message.tool_name === "execute_code") {
				actions.push({
					id: `${message.id}:output`,
					kind: "output",
					title: "返回：代码执行错误",
					detail: toolOutputDetail(message),
					status: "error",
					timestamp: timestamp + 500,
					timeLabel,
					durationMs: 0,
					agent: lastAgentName || "Tool",
					content: toolOutputDetail(message),
					groupId: lastAgentGroupId || "coder",
				});
			}
		}
	});

	return actions.sort((left, right) => left.timestamp - right.timestamp);
});

const actionItems = computed<AgentAction[]>(() => {
	const terminal = displayMessages.value.some(isTerminalMessage);
	const inferredRuntimeGroup = isTaskActive.value
		? inferActiveGroupFromText(runtimeCurrentText.value)
		: null;
	return rawActions.value.map((action, index, items) => {
		const next = items[index + 1];
		const isLast = index === items.length - 1;
		const hasNewerFromSameAgent = items
			.slice(index + 1)
			.some((a) => a.kind === "agent" && a.agent === action.agent);
		const isStreaming =
			action.kind === "agent" &&
			action.streamState === "streaming" &&
			!hasNewerFromSameAgent;
		const status: ActionStatus =
			action.status === "error"
				? "error"
				: action.status === "warning"
					? "warning"
					: isWorkflowTerminal.value
						? "done"
						: action.localAction
							? action.status
							: action.status === "warning" && isLast
								? "warning"
								: terminal
									? "done"
									: isStreaming
										? "running"
										: !isLast
											? "done"
											: inferredRuntimeGroup &&
													getGroupId(action) !== inferredRuntimeGroup
												? "done"
												: isTaskActive.value || props.taskStatus === "ready"
													? "running"
													: "done";
		const endTime =
			status === "running" ? now.value : (next?.timestamp ?? action.timestamp);
		return {
			...action,
			status,
			durationMs: Math.max(0, endTime - action.timestamp),
		};
	});
});

const triggerActionEffects = (actionIds: string[], duration = 1200) => {
	if (!actionIds.length) return;
	const ids = actionIds.filter((id) =>
		actionItems.value.some((action) => action.id === id),
	);
	if (!ids.length) return;

	const nextNewActionIds = new Set(newActionIds.value);
	const nextGroupIds = new Set(pulseGroupIds.value);
	for (const id of ids) {
		nextNewActionIds.add(id);
		const action = actionItems.value.find((item) => item.id === id);
		if (!action) continue;
		nextGroupIds.add(getGroupId(action));
		if (action.flow) {
			const fromGroup = groupIdFromParticipant(action.flow.from);
			const toGroup = groupIdFromParticipant(action.flow.to);
			if (fromGroup) nextGroupIds.add(fromGroup);
			if (toGroup) nextGroupIds.add(toGroup);
		}
		if (action.coordination) {
			const targetGroup = groupIdFromParticipant(action.coordination);
			nextGroupIds.add(targetGroup || action.coordination);
		}
	}
	newActionIds.value = nextNewActionIds;
	pulseGroupIds.value = nextGroupIds;

	setTimeout(() => {
		const remainingActionIds = new Set(newActionIds.value);
		const remainingGroupIds = new Set(pulseGroupIds.value);
		for (const id of ids) {
			remainingActionIds.delete(id);
			const action = actionItems.value.find((item) => item.id === id);
			if (!action) continue;
			remainingGroupIds.delete(getGroupId(action));
			if (action.flow) {
				const fromGroup = groupIdFromParticipant(action.flow.from);
				const toGroup = groupIdFromParticipant(action.flow.to);
				if (fromGroup) remainingGroupIds.delete(fromGroup);
				if (toGroup) remainingGroupIds.delete(toGroup);
			}
			if (action.coordination) {
				const targetGroup = groupIdFromParticipant(action.coordination);
				remainingGroupIds.delete(targetGroup || action.coordination);
			}
		}
		newActionIds.value = remainingActionIds;
		pulseGroupIds.value = remainingGroupIds;
	}, duration);
};

const revealActionIds = (actionIds: string[], animate = true) => {
	const visible = new Set(visibleActionIds.value);
	const idsToReveal = actionIds.filter((id) => !visible.has(id));
	if (!idsToReveal.length) return;
	visibleActionIds.value = [...visibleActionIds.value, ...idsToReveal];
	if (animate) triggerActionEffects(idsToReveal);
};

const revealPendingActionsFast = () => {
	if (revealTimer) {
		clearTimeout(revealTimer);
		revealTimer = null;
	}
	const ids = [...pendingActionIds.value];
	if (!ids.length) return;
	pendingActionIds.value = [];
	revealBurstCount = 0;
	revealActionIds(ids, true);
};

const revealNextAction = () => {
	const nextId = pendingActionIds.value.shift();
	if (!nextId) {
		revealBurstCount = 0;
		return;
	}
	revealActionIds([nextId]);
	revealBurstCount += 1;
	scheduleReveal();
};

const getRevealDelay = () => {
	const backlog = pendingActionIds.value.length;
	if (backlog <= 0) return 1000;
	const pressure = Math.max(0, backlog - 2);
	const accelerated = 1000 * 0.74 ** (revealBurstCount + pressure);
	return Math.max(70, Math.round(accelerated));
};

const scheduleReveal = () => {
	if (revealTimer || pendingActionIds.value.length === 0) return;
	revealTimer = setTimeout(() => {
		revealTimer = null;
		revealNextAction();
	}, getRevealDelay());
};

const setGroupScrollRef = (id: string, element: unknown) => {
	if (element instanceof HTMLDivElement) {
		groupScrollRefs.set(id, element);
	} else {
		groupScrollRefs.delete(id);
	}
};

const isTaskCompleted = computed(() => props.taskStatus === "completed");

const displayedActionItems = computed(() => {
	const visible = new Set(visibleActionIds.value);
	return actionItems.value.filter((action) => visible.has(action.id));
});

const renderedActionItems = computed(() =>
	displayedActionItems.value.length > 0 || actionItems.value.length === 0
		? displayedActionItems.value
		: actionItems.value,
);

/** 从 AgentAction.agent 字符串中提取数字编号（如 "CoderAgent #1 · 代码手1" → 1） */
const extractAgentIndex = (agentStr: string): number | null => {
	const m = agentStr.match(/#(\d+)/);
	return m ? Number(m[1]) : null;
};

const canonicalQuestionGroupId = (groupId: string) => {
	const legacy = groupId.match(/^(sub_coordinator|modeler|coder|writer)_(\d+)$/);
	if (!legacy) return groupId;
	const [, role, idx] = legacy;
	if (role === "sub_coordinator") return `q${idx}.sub_coordinator`;
	if (role === "modeler") return `q${idx}.modeler`;
	if (role === "coder") return `q${idx}.coder.main`;
	if (role === "writer") return `q${idx}.writer`;
	return groupId;
};

const getGroupId = (action: AgentAction) => {
	if (action.groupId) return canonicalQuestionGroupId(action.groupId);
	if (action.kind === "user") return "user";
	const agentStr = action.agent ?? "";
	const idx = extractAgentIndex(agentStr);

	// 精确匹配（含编号的带索引 Agent）
	if (/SubCoordinatorAgent/.test(agentStr)) {
		return idx != null ? `q${idx}.sub_coordinator` : "coordinator";
	}
	if (/CoordinatorAgent/.test(agentStr)) return "coordinator";
	if (/ModelerAgent/.test(agentStr)) {
		return idx != null ? `q${idx}.modeler` : "modeler";
	}
	if (/CoderAgent/.test(agentStr)) {
		return idx != null ? `q${idx}.coder.main` : "coder";
	}
	if (/WriterAgent/.test(agentStr)) {
		return idx != null ? `q${idx}.writer` : "writer";
	}

	if (
		action.kind === "tool" ||
		action.kind === "file" ||
		action.kind === "output"
	) {
		return "coder";
	}
	return "system";
};

const runtimeActiveGroupId = computed(() => {
	if (!isTaskActive.value) return null;
	const inferred = inferActiveGroupFromText(runtimeCurrentText.value);
	if (inferred) return inferred;
	const latest = [...actionItems.value]
		.reverse()
		.find((action) =>
			["agent", "system", "progress", "tool", "file", "output"].includes(
				action.kind,
			),
		);
	return latest ? getGroupId(latest) : null;
});

const getGroupStatus = (
	actions: AgentAction[],
	groupId: string,
): ActionStatus => {
	if (actions.some((action) => action.status === "error")) return "error";
	if (actions.some((action) => action.status === "warning")) return "warning";
	if (actions.some((action) => action.status === "running")) return "running";
	// 有动作且无进行中 → 该 agent 已完成（不论整体任务是否结束）
	if (actions.length > 0) return "done";
	// 尚无任何动作 → 还未开始
	return "pending";
};

/** 动态组排序：固定组在前，子问题组按编号排在后面 */
const buildGroupOrder = (groupIds: Iterable<string>): string[] => {
	const fixed = new Set(groupOrder);
	// 收集所有动态组（含索引的 group ID），按类型+编号排序
	const dynamic: string[] = [];
	for (const id of groupIds) {
		if (!fixed.has(id)) dynamic.push(id);
	}
	dynamic.sort((a, b) => {
		const pa = parseGroupId(a);
		const pb = parseGroupId(b);

		if (pa && pb) {
			if (pa.index !== pb.index) return pa.index - pb.index;

			const roleOrder: Record<QuestionRole, number> = {
				sub_coordinator: 0,
				modeler: 1,
				coder: 2,
				writer: 3,
			};

			if (roleOrder[pa.role] !== roleOrder[pb.role]) {
				return roleOrder[pa.role] - roleOrder[pb.role];
			}

			const attemptOrder = (p: ParsedQuestionGroupId) => {
				if (p.attemptKind === "main") return 0;
				if (p.attemptKind === "backup") return 10 + (p.attemptIndex ?? 0);
				if (p.attemptKind === "race") return 20 + (p.attemptIndex ?? 0);
				return 0;
			};

			return attemptOrder(pa) - attemptOrder(pb);
		}

		if (pa) return -1;
		if (pb) return 1;

		const typeOrder: Record<string, number> = {
			sub_coordinator: 0,
			modeler: 1,
			coder: 2,
			writer: 3,
		};

		const ma = a.match(/^(sub_coordinator|modeler|coder|writer)_(\d+)$/);
		const mb = b.match(/^(sub_coordinator|modeler|coder|writer)_(\d+)$/);
		const orderA = ma ? typeOrder[ma[1]] : 9;
		const orderB = mb ? typeOrder[mb[1]] : 9;

		if (orderA !== orderB) return orderA - orderB;
		return Number(ma?.[2] ?? 0) - Number(mb?.[2] ?? 0);
	});

	// 子问题组放到所有固定主 Agent 之后，按编号排序
	const result = [...groupOrder, ...dynamic];
	return result;
};

const agentGroups = computed<AgentGroup[]>(() => {
	const grouped = new Map<string, AgentAction[]>();
	for (const action of renderedActionItems.value) {
		const groupId = getGroupId(action);
		grouped.set(groupId, [...(grouped.get(groupId) ?? []), action]);
	}

	const orderedIds = buildGroupOrder(grouped.keys());

	return orderedIds
		.filter((groupId) => grouped.has(groupId))
		.map((groupId) => {
			const actions = grouped.get(groupId) ?? [];
			const status = getGroupStatus(actions, groupId);
			const firstAction = actions[0];
			const lastAction = actions[actions.length - 1];
			const durationMs =
				status === "running"
					? Math.max(0, now.value - (firstAction?.timestamp ?? now.value))
					: actions.reduce((total, action) => total + action.durationMs, 0);
			const files = new Set(actions.flatMap((action) => action.files ?? []));
			const meta = getGroupMeta(groupId);
			return {
				id: groupId,
				name: meta.name,
				role: meta.role,
				status,
				actions,
				durationMs,
				lastAction,
				fileCount: files.size,
			};
		});
});

// ---- Group current-work status ----

interface GroupWork {
	text: string;
	state: "working" | "commanded" | "idle";
}

const groupWorkStatus = computed<Record<string, GroupWork>>(() => {
	const map: Record<string, GroupWork> = {
		system: { text: "等待流程调度", state: "idle" },
		user: { text: "等待用户交互", state: "idle" },
		coordinator: { text: "等待题目分析", state: "idle" },
		modeler: { text: "等待建模指令", state: "idle" },
		coder: { text: "等待求解指令", state: "idle" },
		writer: { text: "等待写作指令", state: "idle" },
	};
	// 为所有已存在的动态 group 初始化默认状态
	for (const group of agentGroups.value) {
		if (!map[group.id]) {
			map[group.id] = { text: getGroupMeta(group.id).role, state: "idle" };
		}
	}

	// Forward scan — last matching rule wins, reflecting most-recent state
	for (const action of renderedActionItems.value) {
		if (action.flow) {
			const fromGroup = groupIdFromParticipant(action.flow.from);
			const toGroup = groupIdFromParticipant(action.flow.to);
			const fromLabel = participantLabel(action.flow.from);
			const toLabel = participantLabel(action.flow.to);
			const flowLabel = action.flow.label || action.title;
			if (fromGroup && map[fromGroup]) {
				map[fromGroup] = {
					text: `下达命令，等待 ${toLabel} 恢复：${flowLabel}`,
					state: "commanded",
				};
			}
			if (toGroup && map[toGroup]) {
				map[toGroup] = {
					text: `接收 ${fromLabel} 命令，等待执行：${flowLabel}`,
					state: "commanded",
				};
			}
			if (action.agent === participantLabel(action.flow.from)) {
				const groupId = getGroupId(action);
				if (map[groupId]) {
					map[groupId] = {
						text: `传递结果，等待 ${toLabel} 恢复：${flowLabel}`,
						state: "commanded",
					};
				}
			}
		}
		const c = `${action.title}\n${action.content ?? ""}`;
		const ownerGroup = getGroupId(action);
		const setWork = (
			baseGroup: string,
			text: string,
			state: GroupWork["state"],
		) => {
			const target =
				ownerGroup &&
				(ownerGroup === baseGroup ||
					ownerGroup.startsWith(baseGroup + "_") ||
					ownerGroup.includes("." + baseGroup))
					? ownerGroup
					: baseGroup;
			if (!map[target])
				map[target] = { text: getGroupMeta(target).role, state: "idle" };
			map[target] = { text, state };
			if (target !== baseGroup) map[baseGroup] = { text, state };
		};

		// ── CoderAgent ──
		if (c.includes("创建代码沙盒") || c.includes("初始化代码手")) {
			setWork("coder", "准备就绪，待命中", "commanded");
		} else if (c.includes("代码手开始求解")) {
			const key = extractFlowKey(c);
			const lbl = keyLabel(key);
			setWork("coder", `正在求解${lbl}`, "commanded");
		} else if (
			c.includes("代码手调用") ||
			c.includes("开始执行代码") ||
			c.includes("运行：代码块") ||
			c.includes("代码执行完成")
		) {
			const curText = (ownerGroup && map[ownerGroup]?.text) || map.coder.text;
			setWork(
				"coder",
				curText.startsWith("正在求解") ? curText : "正在执行代码",
				"working",
			);
		} else if (c.includes("代码手反思纠正错误")) {
			setWork("coder", "正在改错修复", "working");
		} else if (c.includes("超过最大重试次数")) {
			setWork("coder", "改错中止，沿用现有结果", "idle");
		} else if (c.includes("代码手完成任务")) {
			const prev = (ownerGroup && map[ownerGroup]?.text) || map.coder.text;
			setWork(
				"coder",
				prev.startsWith("正在求解")
					? `${prev.replace("正在求解", "已完成")}求解`
					: "代码任务完成",
				"idle",
			);
		} else if (c.includes("代码手求解成功")) {
			const key = extractFlowKey(c);
			const lbl = keyLabel(key);
			setWork("coder", `已完成${lbl}求解`, "idle");
		}

		// ── WriterAgent ──
		if (c.includes("论文手开始写")) {
			const key = extractFlowKey(c);
			const lbl = keyLabel(key);
			setWork("writer", `正在进行${lbl}写作`, "commanded");
		} else if (c.includes("论文手完成")) {
			const key = extractFlowKey(c);
			const lbl = keyLabel(key);
			setWork("writer", `已完成${lbl}写作`, "idle");
		} else if (c.includes("论文生成完成")) {
			setWork("writer", "论文全部写作完成", "idle");
		} else if (c.includes("终稿整体检查")) {
			setWork("writer", "正在检查论文终稿", "working");
		}

		// ── ModelerAgent ──
		if (c.includes("任务转交给建模手")) {
			setWork("modeler", "接收建模任务", "commanded");
		} else if (
			c.includes("建模手开始") ||
			c.includes("建模手正在") ||
			c.includes("比选：建模方案")
		) {
			setWork("modeler", "正在制定建模方案", "working");
		} else if (c.includes("建模手分析完成")) {
			setWork("modeler", "建模方案已完成", "idle");
		}

		// ── CoordinatorAgent ──
		if (c.includes("识别用户意图") || c.includes("协调者正在分析")) {
			setWork("coordinator", "正在拆解问题结构", "working");
		} else if (c.includes("问题拆解完成")) {
			setWork("coordinator", "问题拆解已完成", "idle");
		}

		// ── Terminal system states ──
		if (ownerGroup !== "system") continue;
		if (c.includes("任务处理完成")) {
			map.system = { text: "任务全部完成", state: "idle" };
		} else if (c.includes("任务已停止")) {
			map.system = { text: "任务已停止", state: "idle" };
		} else if (c.includes("任务执行失败")) {
			map.system = { text: "任务执行失败", state: "idle" };
		}
	}

	// 将基类 group 的状态传播到对应的动态索引 variant（支持并行子 Agent）
	for (const group of agentGroups.value) {
		const entry = map[group.id];
		if (entry && entry.state !== "idle") continue;
		const base = group.id.replace(/_\d+$/, "");
		if (base !== group.id && map[base]?.state !== "idle") {
			map[group.id] = { ...map[base] };
		}
	}

	if (isWorkflowTerminal.value || !isTaskActive.value) {
		for (const group of agentGroups.value) {
			map[group.id] = {
				text: "已完成，等待查看结果",
				state: "idle",
			};
		}

		for (const id of ["coordinator", "modeler", "coder", "writer", "system"]) {
			if (map[id]) {
				map[id] = {
					text: id === "system" ? "任务全部完成" : "已完成，等待查看结果",
					state: "idle",
				};
			}
		}

		return map;
	}

	// 任意正在运行的 group 升级为 working 状态
	for (const group of agentGroups.value) {
		const entry = map[group.id];
		if (entry && group.status === "running" && entry.state !== "working") {
			map[group.id] = { ...entry, state: "working" };
		}
	}

	return map;
});

const groupWorkClass = (groupId: string): string => {
	const state = groupWorkStatus.value[groupId]?.state ?? "idle";
	if (state === "working") return "work-text-working";
	if (state === "commanded") return "work-text-commanded";
	return "work-text-idle";
};

const groupWorkStateLabel = (groupId: string) => {
	const state = groupWorkStatus.value[groupId]?.state ?? "idle";
	if (state === "working") return "执行";
	if (state === "commanded") return "等待";
	return "空闲";
};

const groupWorkPillClass = (groupId: string) => {
	const state = groupWorkStatus.value[groupId]?.state ?? "idle";
	if (state === "working") return "work-pill-working";
	if (state === "commanded") return "work-pill-commanded";
	return "work-pill-idle";
};

function effectiveGroupStatus(group: AgentGroup | null): ActionStatus {
	if (!group) return "pending";

	if (group.status === "error") return "error";
	if (group.status === "warning") return "warning";

	if (isWorkflowTerminal.value) {
		return group.actions.length > 0 ? "done" : "pending";
	}

	const workState = groupWorkStatus.value[group.id]?.state;

	if (group.status === "running" || workState === "working") {
		return "running";
	}

	if (workState === "commanded") {
		return "pending";
	}

	return group.status;
}

const runningAction = computed(() => {
	const activeGroup = runtimeActiveGroupId.value;
	if (activeGroup) {
		const action =
			[...renderedActionItems.value]
				.reverse()
				.find((item) => getGroupId(item) === activeGroup) ??
			[...actionItems.value]
				.reverse()
				.find((item) => getGroupId(item) === activeGroup);
		if (action) {
			return {
				...action,
				status: "running" as ActionStatus,
				durationMs: Math.max(0, now.value - action.timestamp),
			};
		}
	}
	return (
		[...renderedActionItems.value]
			.reverse()
			.find((action) => action.status === "running") ??
		[...actionItems.value]
			.reverse()
			.find((action) => action.status === "running")
	);
});

const runningAgentPills = computed(() => {
	if (isWorkflowTerminal.value) return [];

	return agentGroups.value
		.filter((group) => {
			if (group.id === "user" || group.id === "system") return false;
			const workState = groupWorkStatus.value[group.id]?.state;
			return group.status === "running" || workState === "working";
		})
		.slice(0, 6)
		.map((group) => {
			const work = groupWorkStatus.value[group.id];
			const lastTimestamp = group.lastAction?.timestamp ?? now.value;

			return {
				id: group.id,
				name: group.name,
				status: group.status,
				state: work?.state ?? "idle",
				text: work?.text ?? group.lastAction?.title ?? group.role,
				durationMs:
					group.status === "running"
						? Math.max(0, now.value - lastTimestamp)
						: group.durationMs,
			};
		});
});

const hiddenRunningAgentCount = computed(() => {
	if (isWorkflowTerminal.value) return 0;

	const all = agentGroups.value.filter((group) => {
		if (group.id === "user" || group.id === "system") return false;
		const workState = groupWorkStatus.value[group.id]?.state;
		return group.status === "running" || workState === "working";
	});
	return Math.max(0, all.length - 6);
});

// 所有正在运行的 Agent 组（支持并行多 Agent 同时高亮）
const activeGroupIds = computed(() => {
	const ids = new Set<string>();
	if (isWorkflowTerminal.value) return ids;
	for (const group of agentGroups.value) {
		if (effectiveGroupStatus(group) === "running") ids.add(group.id);
	}
	return ids;
});

const activeGroupId = computed(() => {
	if (runtimeActiveGroupId.value) return runtimeActiveGroupId.value;
	if (runningAction.value) {
		return getGroupId(runningAction.value);
	}
	for (let i = actionItems.value.length - 1; i >= 0; i--) {
		const action = actionItems.value[i];
		if (
			action.kind === "agent" ||
			action.kind === "system" ||
			action.kind === "tool" ||
			action.kind === "output"
		) {
			return getGroupId(action);
		}
	}
	return null;
});

const finishedAgentCount = computed(
	() => agentGroups.value.filter((group) => group.status === "done").length,
);

// ---- 子问题分组包裹 ----

interface QuestionGroupData {
	index: number;
	groups: AgentGroup[];
	status: ActionStatus;
	progressText: string;
	isActive: boolean;
	totalActions: number;
	durationMs: number;
}

const questionGroupsData = computed<QuestionGroupData[]>(() => {
	const indexed = new Map<number, AgentGroup[]>();
	for (const group of agentGroups.value) {
		const parsed = parseGroupId(group.id);
		if (!parsed) continue;
		if (!indexed.has(parsed.index)) indexed.set(parsed.index, []);
		indexed.get(parsed.index)?.push(group);
	}
	return Array.from(indexed.entries())
		.sort(([a], [b]) => a - b)
		.map(([idx, groups]) => {
			const effectiveStatuses = groups.map((g) => effectiveGroupStatus(g));

			const allDone =
				effectiveStatuses.length > 0 &&
				effectiveStatuses.every((status) => status === "done");

			const hasError = effectiveStatuses.some((status) => status === "error");
			const hasWarning = effectiveStatuses.some(
				(status) => status === "warning",
			);
			const isRunning = effectiveStatuses.some(
				(status) => status === "running",
			);
			const hasPending = effectiveStatuses.some(
				(status) => status === "pending",
			);
			const status: ActionStatus = hasError
				? "error"
				: hasWarning
					? "warning"
					: isRunning
						? "running"
						: allDone
							? "done"
							: "pending";
			const runningGroup = groups.find(
				(g) => effectiveGroupStatus(g) === "running",
			);
			const runningCount = groups.filter(
				(g) => effectiveGroupStatus(g) === "running",
			).length;
			const pendingCount = groups.filter(
				(g) => effectiveGroupStatus(g) === "pending",
			).length;
			const doneCount = groups.filter(
				(g) => effectiveGroupStatus(g) === "done",
			).length;
			let progressText = `${groups.length} 个 Agent`;
			if (runningCount > 1) {
				const names = groups
					.filter((g) => effectiveGroupStatus(g) === "running")
					.map((g) =>
						g.name
							.replace(/Agent.*/, "")
							.trim()
							.replace(/\s+#\d+$/, ""),
					)
					.join(" · ");
				progressText = `⚡ 并行：${names}`;
			} else if (runningGroup) {
				progressText = `${runningGroup.name} 进行中`;
			} else if (allDone) {
				progressText = "全部完成";
			} else if (pendingCount > 0) {
				progressText = `${doneCount}/${groups.length} 完成，${pendingCount} 个等待`;
			} else {
				if (doneCount > 0) progressText = `${doneCount}/${groups.length} 完成`;
			}
			const totalActions = groups.reduce((sum, g) => sum + g.actions.length, 0);
			const durationMs = groups.reduce((sum, g) => sum + g.durationMs, 0);
			return {
				index: idx,
				groups,
				status,
				progressText,
				isActive: !isWorkflowTerminal.value && (isRunning || hasPending),
				totalActions,
				durationMs,
			};
		});
});

// 论文写作组：收集 paper.writer.* Agent，独立于求解子问题组
const writerSectionOrder = [
	"firstPage",
	"toc",
	"RepeatQues",
	"analysisQues",
	"modelAssumption",
	"symbol",
	"judge",
];

function paperWriterOrder(id: string): number {
	const key = id.match(/^paper\.writer\.(.+)$/)?.[1] ?? "";
	const idx = writerSectionOrder.indexOf(key);
	return idx >= 0 ? idx : 999;
}

const writerGroupsData = computed<AgentGroup[]>(() => {
	return agentGroups.value
		.filter((group) => /^paper\.writer\./.test(group.id))
		.sort((a, b) => paperWriterOrder(a.id) - paperWriterOrder(b.id));
});

const indexedGroupIdSet = computed(() => {
	const ids = new Set<string>();
	for (const qg of questionGroupsData.value) {
		for (const g of qg.groups) ids.add(g.id);
	}
	for (const wg of writerGroupsData.value) ids.add(wg.id);
	return ids;
});

type TopLevelItem =
	| { kind: "group"; group: AgentGroup }
	| (QuestionGroupData & { kind: "question_group" })
	| { kind: "writer_group"; groups: AgentGroup[] };

const topLevelItems = computed<TopLevelItem[]>(() => {
	const items: TopLevelItem[] = [];
	const indexedIds = indexedGroupIdSet.value;
	const seenQGroups = new Set<number>();
	for (const group of agentGroups.value) {
		if (!indexedIds.has(group.id)) {
			items.push({ kind: "group", group });
		} else {
			const parsed = parseGroupId(group.id);
			if (parsed && !seenQGroups.has(parsed.index)) {
				seenQGroups.add(parsed.index);
				const qg = questionGroupsData.value.find(
					(q) => q.index === parsed.index,
				);
				if (qg) items.push({ kind: "question_group", ...qg });
			}
		}
	}
	if (writerGroupsData.value.length > 0) {
		items.push({ kind: "writer_group", groups: writerGroupsData.value });
	}
	return items;
});

const statusLabel = (status: ActionStatus) => {
	if (status === "running") return "动作中";
	if (status === "done") return "已完成";
	if (status === "warning") return "已停止";
	if (status === "error") return "出错";
	return "等待中";
};

const statusClass = (status: ActionStatus) => {
	switch (status) {
		case "running":
			return "text-blue-700 bg-blue-50 border-blue-200";
		case "done":
			return "text-green-700 bg-green-50 border-green-200";
		case "warning":
			return "text-amber-700 bg-amber-50 border-amber-200";
		case "error":
			return "text-red-700 bg-red-50 border-red-200";
		default:
			return "text-slate-500 bg-slate-50 border-slate-200";
	}
};

// ---- 子问题流水线 ----

type QuestionRole = "sub_coordinator" | "modeler" | "coder" | "writer";
type QuestionAttemptKind = "main" | "backup" | "race" | null;

interface ParsedQuestionGroupId {
	index: number;
	role: QuestionRole;
	attempt: string | null;
	attemptKind: QuestionAttemptKind;
	attemptIndex: number | null;
}

function parseGroupId(groupId: string): ParsedQuestionGroupId | null {
	const modern = groupId.match(
		/^q(\d+)\.(sub_coordinator|modeler|coder|writer)(?:\.(main|b\d+|r\d+))?$/,
	);

	if (modern) {
		const [, indexText, role, attemptText] = modern;
		let attemptKind: QuestionAttemptKind = null;
		let attemptIndex: number | null = null;

		if (attemptText === "main") {
			attemptKind = "main";
			attemptIndex = 1;
		} else if (attemptText?.startsWith("b")) {
			attemptKind = "backup";
			attemptIndex = Number(attemptText.slice(1));
		} else if (attemptText?.startsWith("r")) {
			attemptKind = "race";
			attemptIndex = Number(attemptText.slice(1));
		}

		return {
			index: Number(indexText),
			role: role as QuestionRole,
			attempt: attemptText ?? null,
			attemptKind,
			attemptIndex,
		};
	}

	const legacy = groupId.match(/^(sub_coordinator|modeler|coder)_(\d+)$/);

	if (legacy) {
		const [, role, indexText] = legacy;
		return {
			index: Number(indexText),
			role: role as QuestionRole,
			attempt: null,
			attemptKind: null,
			attemptIndex: null,
		};
	}

	return null;
}

interface WorkflowRow {
	index: number;
	subCoordinator: AgentGroup | null;
	modeler: AgentGroup | null;
	coders: AgentGroup[];
	winnerCoder: AgentGroup | null;
	writer: AgentGroup | null;
	overallStatus: ActionStatus;
}

const workflowRows = computed<WorkflowRow[]>(() => {
	const rows = new Map<number, WorkflowRow>();
	const ensureRow = (idx: number) => {
		if (!rows.has(idx)) {
			rows.set(idx, {
				index: idx,
				subCoordinator: null,
				modeler: null,
				coders: [],
				winnerCoder: null,
				writer: null,
				overallStatus: "pending",
			});
		}
		return rows.get(idx)!;
	};
	for (const group of agentGroups.value) {
		const parsed = parseGroupId(group.id);
		if (!parsed) continue;
		const row = ensureRow(parsed.index);
		if (parsed.role === "sub_coordinator") row.subCoordinator = group;
		else if (parsed.role === "modeler") row.modeler = group;
		else if (parsed.role === "coder") {
			row.coders.push(group);
			if (
				group.actions.some((a) =>
					`${a.title}\n${a.content ?? ""}`.includes("代码手求解成功"),
				)
			) {
				row.winnerCoder = group;
			}
		} else if (parsed.role === "writer") row.writer = group;
	}
	for (const row of rows.values()) {
		const groups = [
			row.subCoordinator,
			row.modeler,
			row.winnerCoder ?? row.coders[0],
			row.writer,
		].filter(Boolean) as AgentGroup[];
		const statuses = groups.map((g) => effectiveGroupStatus(g));

		if (statuses.some((status) => status === "error")) {
			row.overallStatus = "error";
		} else if (statuses.some((status) => status === "warning")) {
			row.overallStatus = "warning";
		} else if (statuses.some((status) => status === "running")) {
			row.overallStatus = "running";
		} else if (
			statuses.length > 0 &&
			statuses.every((status) => status === "done")
		) {
			row.overallStatus = "done";
		} else {
			row.overallStatus = "pending";
		}
	}
	return Array.from(rows.values()).sort((a, b) => a.index - b.index);
});

function coderNodeLabel(row: WorkflowRow): string {
	if (row.coders.length <= 1) return "代码";

	const parsedCoders = row.coders
		.map((g) => parseGroupId(g.id))
		.filter(Boolean) as ParsedQuestionGroupId[];

	const hasRace = parsedCoders.some((p) => p.attemptKind === "race");
	const hasBackup = parsedCoders.some((p) => p.attemptKind === "backup");

	if (hasRace) {
		const doneCount = row.coders.filter((g) => g.status === "done").length;
		return `代码 竞速 ${doneCount}/${row.coders.length}`;
	}

	if (hasBackup) {
		const backupCount = parsedCoders.filter(
			(p) => p.attemptKind === "backup",
		).length;
		return `代码 备用${backupCount > 1 ? ` \xd7${backupCount}` : ""}`;
	}

	return `代码 ${row.coders.length}个`;
}

function inferredPipelineStatus(
	row: WorkflowRow,
	role: "subCoordinator" | "coder" | "writer",
): ActionStatus {
	const writerStatus = effectiveGroupStatus(row.writer);
	const coderStatus = row.winnerCoder
		? effectiveGroupStatus(row.winnerCoder)
		: row.coders.some((g) => effectiveGroupStatus(g) === "done")
			? "done"
			: row.coders.some((g) => effectiveGroupStatus(g) === "running")
				? "running"
				: row.coders.length > 0
					? effectiveGroupStatus(row.coders[0])
					: "pending";

	if (role === "writer") return writerStatus;

	if (role === "coder") {
		if (writerStatus === "done") return "done";
		return coderStatus;
	}

	if (role === "subCoordinator") {
		if (writerStatus === "done" || coderStatus === "done") return "done";
		return effectiveGroupStatus(row.subCoordinator);
	}

	return "pending";
}

function pipelineNodeClassByStatus(status: ActionStatus): string {
	switch (status) {
		case "running":
			return "pipeline-node-running";
		case "done":
			return "pipeline-node-done";
		case "error":
			return "pipeline-node-error";
		case "warning":
			return "pipeline-node-warning";
		default:
			return "pipeline-node-pending";
	}
}

function pipelineNodeClass(group: AgentGroup | null): string {
	if (!group) return "pipeline-node-pending";

	switch (effectiveGroupStatus(group)) {
		case "running":
			return "pipeline-node-running";
		case "done":
			return "pipeline-node-done";
		case "error":
			return "pipeline-node-error";
		case "warning":
			return "pipeline-node-warning";
		default:
			return "pipeline-node-pending";
	}
}

// ---- 最近 Agent 通信记录 ----

const recentCommunications = computed(() =>
	actionItems.value
		.filter((a) => a.flow)
		.slice(-8)
		.reverse(),
);

// ---- Watchers ----

watch(
	actionItems,
	(items) => {
		if (items.length === 0) {
			visibleActionIds.value = [];
			pendingActionIds.value = [];
			newActionIds.value = new Set();
			pulseGroupIds.value = new Set();
			fastReplayUntil = Date.now() + 1200;
			if (revealTimer) {
				clearTimeout(revealTimer);
				revealTimer = null;
			}
			return;
		}

		const currentIds = new Set(items.map((action) => action.id));
		visibleActionIds.value = visibleActionIds.value.filter((id) =>
			currentIds.has(id),
		);
		pendingActionIds.value = pendingActionIds.value.filter(
			(id) => currentIds.has(id) && !visibleActionIds.value.includes(id),
		);
		const knownIds = new Set([
			...visibleActionIds.value,
			...pendingActionIds.value,
		]);
		let addedCount = 0;
		for (const action of items) {
			if (!knownIds.has(action.id)) {
				pendingActionIds.value.push(action.id);
				knownIds.add(action.id);
				addedCount += 1;
			}
		}

		const isInitialReplay = Date.now() <= fastReplayUntil;
		const isSnapshotBacklog =
			visibleActionIds.value.length === 0 && pendingActionIds.value.length > 1;
		const isLargeReconnectBacklog =
			addedCount >= 8 || pendingActionIds.value.length >= 12;
		if (isInitialReplay || isSnapshotBacklog || isLargeReconnectBacklog) {
			revealPendingActionsFast();
			return;
		}

		if (visibleActionIds.value.length === 0) {
			revealNextAction();
		}
		scheduleReveal();
	},
	{ immediate: true },
);

watch(
	() => renderedActionItems.value.length,
	async () => {
		await nextTick();
		scrollExpandedToBottom();
		scrollOuterToBottom();
		scrollGroupWindowsToBottom();
	},
);

const isNearBottom = (el: HTMLElement) =>
	el.scrollHeight - el.scrollTop - el.clientHeight < 120;

function scrollOuterToBottom(force = false) {
	const el = scrollRef.value;
	if (!el) return;
	if (force || !userScrolledUp.value) {
		el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
	}
}

function scrollGroupWindowsToBottom() {
	for (const groupElement of groupScrollRefs.values()) {
		if (isNearBottom(groupElement) || !userScrolledUp.value) {
			groupElement.scrollTo({
				top: groupElement.scrollHeight,
				behavior: "smooth",
			});
		}
	}
}

function scrollExpandedToBottom() {
	for (const id of expandedActions.value) {
		const el = document.querySelector(`[data-expand-id="${id}"]`);
		if (el) el.scrollTop = el.scrollHeight;
	}
}

function scrollToGroupCard(groupId) {
	const el = scrollRef.value;
	if (!el) return;
	const card = el.querySelector(`[data-group-id="${groupId}"]`) || null;
	if (card) {
		card.scrollIntoView({ behavior: "smooth", block: "nearest" });
	}
}

function onOuterScroll() {
	const el = scrollRef.value;
	if (!el) return;
	userScrolledUp.value = !isNearBottom(el);
	if (isNearBottom(el)) {
		userScrolledUp.value = false;
	}
	if (autoScrollTimeout) clearTimeout(autoScrollTimeout);
	autoScrollTimeout = setTimeout(() => {
		userScrolledUp.value = false;
	}, 3000);
}

watch(
	() => props.messages,
	async () => {
		await nextTick();
		scrollExpandedToBottom();
	},
	{ deep: true },
);

// ---- Lifecycle ----

onMounted(() => {
	timer = setInterval(() => {
		now.value = Date.now();
	}, 1000);
	scheduleReveal();
});

onBeforeUnmount(() => {
	if (timer) clearInterval(timer);
	if (revealTimer) clearTimeout(revealTimer);
});
</script>

<template>
	<div class="flex h-full flex-col glass-root" :class="{ 'agent-status-collapsed': collapsed }">
		<div class="glass-header border-b border-white/20 px-4 py-3">
				<div class="min-w-0">
					<div class="flex items-center gap-2 text-sm font-semibold text-slate-950">
						<ListChecks class="h-4 w-4 text-blue-600" />
						Agent 执行状态
					</div>

					<div v-if="runningAgentPills.length" class="parallel-agent-pills mt-2">
						<div
							v-for="pill in runningAgentPills"
							:key="pill.id"
							class="parallel-agent-pill"
							:class="{
								'parallel-agent-pill-working': pill.state === 'working' || pill.status === 'running',
								'parallel-agent-pill-commanded': pill.state === 'commanded',
							}"
							:title="`${pill.name} / ${pill.text}`"
						>
							<LoaderCircle
								v-if="pill.state === 'working' || pill.status === 'running'"
								class="h-3.5 w-3.5 shrink-0 animate-spin"
							/>
							<Clock3 v-else class="h-3.5 w-3.5 shrink-0" />
							<span class="parallel-agent-pill-name">{{ pill.name }}</span>
							<span class="parallel-agent-pill-detail">{{ pill.text }}</span>
							<span class="parallel-agent-pill-time">{{ formatDuration(pill.durationMs) }}</span>
						</div>
						<span v-if="hiddenRunningAgentCount > 0" class="parallel-agent-more">
							+{{ hiddenRunningAgentCount }}
						</span>
					</div>
				</div>
			</div>



		

		


			<!-- 子问题流水线视图 -->
		<div v-if="workflowRows.length > 0" class="pipeline-section border-b border-white/20 px-4 py-2">
			<div v-for="row in workflowRows" :key="row.index" class="pipeline-row">
				<span class="pipeline-label">Q{{ row.index }}</span>
				<div class="pipeline-nodes">
					<div class="pipeline-node" :class="pipelineNodeClassByStatus(inferredPipelineStatus(row, 'subCoordinator'))" :title="row.subCoordinator?.name ?? '协调 Agent'">
						<Settings2 class="h-2.5 w-2.5 shrink-0" />
						<span>协调</span>
						<LoaderCircle v-if="inferredPipelineStatus(row, 'subCoordinator') === 'running'" class="h-2 w-2 shrink-0 animate-spin" />
						<CheckCircle2 v-else-if="inferredPipelineStatus(row, 'subCoordinator') === 'done'" class="h-2 w-2 shrink-0" />
					</div>
					<span class="pipeline-arrow">→</span>
					<div class="pipeline-node" :class="pipelineNodeClassByStatus(inferredPipelineStatus(row, 'coder'))" :title="(row.winnerCoder?.name ?? row.coders.map(g => g.name).join(' / ')) || '代码 Agent'">
						<Code2 class="h-2.5 w-2.5 shrink-0" />
						<span>{{ coderNodeLabel(row) }}</span>
						<LoaderCircle v-if="inferredPipelineStatus(row, 'coder') === 'running'" class="h-2 w-2 shrink-0 animate-spin" />
						<CheckCircle2 v-else-if="inferredPipelineStatus(row, 'coder') === 'done'" class="h-2 w-2 shrink-0" />
					</div>
					<span class="pipeline-arrow">→</span>
					<div class="pipeline-node" :class="pipelineNodeClassByStatus(inferredPipelineStatus(row, 'writer'))" :title="row.writer?.name ?? '撰写 Agent'">
						<PenLine class="h-2.5 w-2.5 shrink-0" />
						<span>撰写</span>
						<LoaderCircle v-if="inferredPipelineStatus(row, 'writer') === 'running'" class="h-2 w-2 shrink-0 animate-spin" />
						<CheckCircle2 v-else-if="inferredPipelineStatus(row, 'writer') === 'done'" class="h-2 w-2 shrink-0" />
					</div>
				</div>
			</div>
		</div>

		<!-- 最近 Agent 通信记录 -->
		<div v-if="recentCommunications.length > 0" class="comms-section border-b border-white/20 px-4 py-2">
			<div class="comms-header">最近动作</div>
			<div class="comms-list">
				<template v-for="action in recentCommunications" :key="action.id">
					<div class="comms-party-pill comms-from-pill" :title="participantLabel(action.flow!.from)">
						{{ participantLabel(action.flow!.from) }}
					</div>
					<span class="comms-grid-arrow">→</span>
					<div class="comms-party-pill comms-to-pill" :title="participantLabel(action.flow!.to)">
						{{ participantLabel(action.flow!.to) }}
					</div>
					<div class="comms-label-pill" :class="{ 'comms-label-empty': !action.flow!.label }" :title="action.flow!.label || ''">
						{{ action.flow!.label || '—' }}
					</div>
				</template>
			</div>
		</div>

		<div class="main-scroll-shell flex-1 min-h-0">
			<div ref="scrollRef" class="agent-scroll h-full overflow-y-auto px-4 py-4" @scroll="onOuterScroll">
				<div v-if="agentGroups.length === 0" class="border-y border-dashed border-slate-200 py-4 text-sm text-slate-500">
					等待任务开始...
				</div>

				<div class="space-y-3">
					<template v-for="item in topLevelItems" :key="item.kind === 'group' ? item.group?.id : `qg-${(item as any).index ?? 'w'}`">

					<!-- 普通 Agent 卡片 -->
					<details
						v-if="item.kind === 'group' && item.group"
						:data-group-id="item.group.id"
						class="group glass-card rounded-2xl border border-white/20 bg-white/40 backdrop-blur-md shadow-[0_4px_24px_rgba(0,0,0,0.04),0_0_0_1px_rgba(255,255,255,0.5)_inset] transition-all duration-300 hover:shadow-[0_8px_32px_rgba(59,130,246,0.1),0_0_0_1px_rgba(255,255,255,0.6)_inset] hover:border-blue-300/30"
						:class="{ 'active-agent-glow': activeGroupIds.has(item.group.id) && item.group.status !== 'done', 'card-pulse': pulseGroupIds.has(item.group.id) || item.group.actions.some(a => newActionIds.has(a.id)) }"
						:open="isDetailOpen('group', item.group.id)"
											>
						<summary
							class="flex cursor-pointer list-none items-start gap-3 px-3 py-3"
							@click.prevent="toggleDetailOpen('group', item.group.id)"
						>
							<div class="pt-0.5">
								<UserRound v-if="item.group.id === 'user'" class="h-5 w-5 text-indigo-600" />
								<Settings2 v-else-if="item.group.id === 'coordinator' || item.group.id === 'modeler' || item.group.id === 'system'" class="h-5 w-5 text-blue-600" />
								<Code2 v-else-if="item.group.id === 'coder'" class="h-5 w-5 text-slate-700" />
								<PenLine v-else-if="item.group.id === 'writer'" class="h-5 w-5 text-slate-700" />
								<Wrench v-else class="h-5 w-5 text-violet-600" />
							</div>

							<div class="min-w-0 flex-1">
								<div class="flex min-w-0 items-center gap-2">
									<span class="truncate text-sm font-semibold text-slate-950">{{ item.group.name }}</span>
									<span class="shrink-0 font-mono text-[11px] text-slate-500">{{ formatDuration(item.group.durationMs) }}</span>
								</div>
								<div class="mt-1 flex items-center gap-1.5 overflow-hidden">
									<span class="work-state-pill" :class="groupWorkPillClass(item.group.id)">
										{{ groupWorkStateLabel(item.group.id) }}
									</span>
									<span v-if="groupWorkStatus[item.group.id]?.state === 'commanded'" class="work-dot" />
									<span class="truncate text-xs" :class="groupWorkClass(item.group.id)">
										{{ groupWorkStatus[item.group.id]?.text ?? item.group.role }}
									</span>
								</div>
								<div class="summary-action-viewport mt-1">
									<Transition name="summary-roll" mode="out-in">
										<div
											v-if="item.group.lastAction"
											:key="item.group.lastAction.id"
											class="summary-action-line truncate text-xs text-slate-700"
										>
											{{ item.group.lastAction.title }}
										</div>
									</Transition>
								</div>
							</div>

							<div class="flex shrink-0 items-center gap-2 pt-0.5 text-[11px] text-slate-500">
								<span>{{ item.group.actions.length }} 条动作</span>
								<span v-if="item.group.fileCount > 0">{{ item.group.fileCount }} 个文件</span>
								<ChevronDown class="h-4 w-4 transition group-open:rotate-180" />
							</div>
						</summary>

						<div class="group-action-shell">
							<div :ref="(element) => setGroupScrollRef(item.group ? item.group.id : '', element)" class="group-action-window border-t border-slate-100">
								<div class="divide-y divide-white/10">
									<div
										v-for="action in item.group.actions"
										:key="action.id"
										class="action-line px-3 py-2"
										:class="{ 'card-merge': newActionIds.has(action.id) }"
									>
										<div class="flex min-w-0 items-center gap-2">
											<span class="shrink-0 font-mono text-[11px] text-slate-400">{{ action.timeLabel }}</span>
											<span v-if="action.status === 'running'" class="shrink-0 font-mono text-[11px] text-blue-500">{{ formatDuration(action.durationMs) }}</span>
											<LoaderCircle v-if="action.status === 'running'" class="h-4 w-4 shrink-0 animate-spin text-blue-600" />
											<CheckCircle2 v-else-if="action.status === 'done'" class="h-4 w-4 shrink-0 text-slate-300" />
											<CircleAlert v-else-if="action.status === 'warning'" class="h-4 w-4 shrink-0 text-amber-600" />
											<CircleX v-else-if="action.status === 'error'" class="h-4 w-4 shrink-0 text-red-600" />
											<Clock3 v-else class="h-4 w-4 shrink-0 text-slate-300" />
											<UserRound v-if="action.kind === 'user'" class="h-3.5 w-3.5 shrink-0 text-indigo-600" />
											<Settings2 v-else-if="action.kind === 'system' || action.kind === 'progress'" class="h-3.5 w-3.5 shrink-0 text-blue-600" />
											<Wrench v-else-if="action.kind === 'tool'" class="h-3.5 w-3.5 shrink-0 text-violet-600" />
											<FileText v-else-if="action.kind === 'file'" class="h-3.5 w-3.5 shrink-0 text-cyan-700" />
											<TerminalSquare v-else-if="action.kind === 'output'" class="h-3.5 w-3.5 shrink-0 text-emerald-700" />
											<Code2 v-else-if="action.agent === 'CoderAgent'" class="h-3.5 w-3.5 shrink-0 text-slate-600" />
											<PenLine v-else-if="action.agent === 'WriterAgent'" class="h-3.5 w-3.5 shrink-0 text-slate-600" />
											<FileText v-else class="h-3.5 w-3.5 shrink-0 text-slate-600" />
											<template v-if="action.kind === 'tool' && parseToolActionTitle(action.title)">
												<span class="action-verb-chip action-verb-tool shrink-0">调用</span>
												<span class="action-title-chip action-title-tool shrink-0 truncate">
													工具 {{ parseToolActionTitle(action.title) }}
												</span>
											</template>
											<template v-else-if="action.kind === 'file' && action.files?.length">
												<span class="action-verb-chip action-verb-file shrink-0">{{ action.title.split('：')[0] || '文件' }}</span>
												<a
													v-for="file in action.files"
													:key="file"
													:href="previewUrlFor(file)"
													class="action-file-chip inline-flex shrink-0 cursor-pointer items-center gap-0.5"
													:class="chipKindClass(action.kind, action.title)"
													@click.prevent.stop="openFilePreview(file)"
												>
													<FolderOpen class="h-3 w-3 shrink-0" />
													{{ getArtifactDisplayInfo(file, currentTaskId).shortName }}
												</a>
											</template>
											<template v-else-if="parseAgentActionTitle(action.title)">
												<span class="action-verb-chip" :class="actionVerbClass(action)" shrink-0>{{ parseAgentActionTitle(action.title)!.verb }}</span>
												<span class="action-title-chip shrink-0 truncate" :class="actionTitleChipClass(action)">{{ parseAgentActionTitle(action.title)!.content }}</span>
											</template>
											<span v-else class="shrink min-w-0 truncate" :class="actionTitleChipClass(action)">{{ action.title }}</span>
											<span v-if="action.flow" class="workflow-chip shrink-0">
												<span class="workflow-party">{{ participantLabel(action.flow.from) }}</span>
												<span class="workflow-arrow">→</span>
												<span class="workflow-party">{{ participantLabel(action.flow.to) }}</span>
												<span v-if="action.flow.label" class="workflow-label">{{ action.flow.label }}</span>
											</span>
											<span v-else-if="action.coordination" class="coordination-chip shrink-0">
												→ {{ coordinationLabel(action.coordination) }}
											</span>
											<span v-if="action.status === 'running'" class="shrink-0 rounded-full border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-700">进行中</span>
											<span v-else-if="action.status === 'warning' || action.status === 'error'" class="shrink-0 rounded-full border px-1.5 py-0.5 text-[10px]" :class="statusClass(action.status)">{{ statusLabel(action.status) }}</span>
										</div>
										<div class="action-detail-slot mt-1">
											<div class="flex items-start gap-1">
												<span
													v-if="action.content"
													class="expand-toggle mt-[2px] shrink-0 cursor-pointer select-none text-[10px] leading-none text-slate-400 hover:text-slate-600"
													@click.stop="toggleExpand(action.id)"
												>{{ expandedActions.has(action.id) ? '▼' : '▶' }}</span>
												<div
													v-if="expandedActions.has(action.id) && action.content"
													:data-expand-id="action.id"
													class="expanded-inline flex-1 max-h-52 overflow-y-auto text-[0.72rem] leading-4 text-slate-500"
												 @click="onExpandedClick"
												 v-html="renderContentWithImages(action.content)" />
												<div v-else-if="action.detail" class="detail-preview flex-1">{{ action.detail }}</div>
												<div v-else-if="action.kind !== 'file' && action.files?.length" class="flex flex-wrap gap-1">
													<a
														v-for="file in action.files"
														:key="file"
														:href="previewUrlFor(file)"
														class="file-action-chip inline-flex items-center gap-0.5 cursor-pointer hover:opacity-80 transition-opacity"
														:class="chipKindClass(action.kind, action.title)"
														@click.prevent.stop="openFilePreview(file)"
													>
														<Wrench v-if="action.kind === 'tool'" class="h-3 w-3 shrink-0" />
														<TerminalSquare v-else-if="action.kind === 'output'" class="h-3 w-3 shrink-0" />
														<Download v-else-if="isWriteAction(action.title)" class="h-3 w-3 shrink-0" />
														<FolderOpen v-else class="h-3 w-3 shrink-0" />
														{{ artifactDisplayName(file) }}
													</a>
												</div>
											</div>
										</div>
									</div>
								</div>
							</div>
						</div>
					</details>

						<!-- 子问题分组包裹卡片 -->
						<details
							v-else-if="item.kind === 'question_group'"
							class="question-group-shell group glass-card rounded-2xl border border-amber-200/40 bg-amber-50/30 backdrop-blur-md shadow-[0_4px_24px_rgba(245,158,11,0.06),0_0_0_1px_rgba(255,255,255,0.5)_inset] transition-all duration-300"
							:class="{ 'question-group-active': item.isActive }"
							:open="isDetailOpen('question_group', item.index)"
													>
							<summary
								class="flex cursor-pointer list-none items-start gap-3 px-4 py-3.5"
								@click.prevent="toggleDetailOpen('question_group', item.index)"
							>
								<div class="pt-0.5">
									<div class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-100 ring-2 ring-amber-200/50">
										<Layers class="h-4 w-4 text-amber-600" />
									</div>
								</div>
								<div class="min-w-0 flex-1">
									<div class="flex min-w-0 items-center gap-2">
										<span class="truncate text-sm font-semibold text-slate-900">子问题 #{{ item.index }}</span>
										<span class="shrink-0 font-mono text-[11px] text-slate-500">{{ formatDuration(item.durationMs) }}</span>
									</div>
									<div class="mt-1 flex items-center gap-2 text-xs text-slate-600">
										<span>{{ item.progressText }}</span>
										<span class="text-slate-300">·</span>
										<span>{{ item.totalActions }} 条动作</span>
									</div>
								</div>
								<div class="flex shrink-0 items-center gap-2 pt-0.5 text-[11px] text-slate-500">
									<span>{{ item.groups.length }} 个 Agent</span>
									<ChevronDown class="h-4 w-4 transition group-open:rotate-180" />
								</div>
							</summary>

							<!-- 展开后的子 Agent 卡片列表 -->
							<div class="question-group-body border-t border-amber-200/30 px-3 py-2 space-y-2">
								<details
									v-for="subGroup in item.groups"
									:key="subGroup.id"
									:data-group-id="subGroup.id"
									class="group glass-card rounded-xl border border-white/20 bg-white/50 backdrop-blur-sm shadow-[0_2px_12px_rgba(0,0,0,0.02)] transition-all duration-300 hover:shadow-[0_4px_16px_rgba(59,130,246,0.08)] hover:border-blue-200/30"
									:class="{ 'active-agent-glow': activeGroupIds.has(subGroup.id) && subGroup.status !== 'done', 'card-pulse': pulseGroupIds.has(subGroup.id) || subGroup.actions.some(a => newActionIds.has(a.id)) }"
									:open="isDetailOpen('sub_group', subGroup.id)"
								>
									<summary
									class="flex cursor-pointer list-none items-start gap-2.5 px-3 py-2.5"
									@click.prevent="toggleDetailOpen('sub_group', subGroup.id)"
								>
										<div class="pt-0.5">
											<Settings2 v-if="parseGroupId(subGroup.id)?.role === 'sub_coordinator' || subGroup.id.startsWith('sub_coordinator')" class="h-4 w-4 text-blue-600" />
											<Code2 v-else-if="parseGroupId(subGroup.id)?.role === 'coder' || subGroup.id.startsWith('coder')" class="h-4 w-4 text-slate-700" />
											<PenLine v-else-if="parseGroupId(subGroup.id)?.role === 'writer' || subGroup.id.startsWith('writer')" class="h-4 w-4 text-slate-700" />
											<Wrench v-else class="h-4 w-4 text-violet-600" />
										</div>
										<div class="min-w-0 flex-1">
											<div class="flex min-w-0 items-center gap-1.5">
												<span class="truncate text-xs font-semibold text-slate-800">{{ subGroup.name }}</span>
												<span class="rounded-full border px-1.5 py-0.5 text-[10px]" :class="statusClass(effectiveGroupStatus(subGroup))">{{ statusLabel(effectiveGroupStatus(subGroup)) }}</span>
												<span class="shrink-0 font-mono text-[10px] text-slate-500">{{ formatDuration(subGroup.durationMs) }}</span>
											</div>
											<div class="mt-0.5 flex items-center gap-1.5 overflow-hidden">
												<span class="work-state-pill" :class="groupWorkPillClass(subGroup.id)">
													{{ groupWorkStateLabel(subGroup.id) }}
												</span>
												<span v-if="groupWorkStatus[subGroup.id]?.state === 'commanded'" class="work-dot" />
												<span class="truncate text-[10px]" :class="groupWorkClass(subGroup.id)">
													{{ groupWorkStatus[subGroup.id]?.text ?? subGroup.role }}
												</span>
											</div>
										</div>
										<div class="flex shrink-0 items-center gap-1.5 text-[10px] text-slate-500">
											<span>{{ subGroup.actions.length }} 条</span>
											<ChevronDown class="h-3.5 w-3.5 transition group-open:rotate-180" />
										</div>
									</summary>

									<div class="group-action-shell">
										<div :ref="(element) => setGroupScrollRef(subGroup.id, element)" class="group-action-window border-t border-slate-100">
											<div class="divide-y divide-white/10">
												<div
													v-for="action in subGroup.actions"
													:key="action.id"
													class="action-line px-3 py-2"
													:class="{ 'card-merge': newActionIds.has(action.id) }"
												>
													<div class="flex min-w-0 items-center gap-2">
														<span class="shrink-0 font-mono text-[10px] text-slate-400">{{ action.timeLabel }}</span>
														<span v-if="action.status === 'running'" class="shrink-0 font-mono text-[10px] text-blue-500">{{ formatDuration(action.durationMs) }}</span>
														<LoaderCircle v-if="action.status === 'running'" class="h-3.5 w-3.5 shrink-0 animate-spin text-blue-600" />
														<CheckCircle2 v-else-if="action.status === 'done'" class="h-3.5 w-3.5 shrink-0 text-slate-300" />
														<CircleAlert v-else-if="action.status === 'warning'" class="h-3.5 w-3.5 shrink-0 text-amber-600" />
														<CircleX v-else-if="action.status === 'error'" class="h-3.5 w-3.5 shrink-0 text-red-600" />
														<Clock3 v-else class="h-3.5 w-3.5 shrink-0 text-slate-300" />
														<span class="shrink min-w-0 truncate text-[0.72rem]" :class="actionTitleChipClass(action)">{{ action.title }}</span>
														<span v-if="action.status === 'running'" class="shrink-0 rounded-full border border-blue-200 bg-blue-50 px-1 py-0.5 text-[9px] text-blue-700">进行中</span>
														<span v-else-if="action.status === 'warning' || action.status === 'error'" class="shrink-0 rounded-full border px-1 py-0.5 text-[9px]" :class="statusClass(action.status)">{{ statusLabel(action.status) }}</span>
													</div>
												</div>
											</div>
										</div>
									</div>
								</details>
							</div>
						</details>

						<!-- 论文写作组卡片 -->
						<details
							v-else-if="item.kind === 'writer_group'"
							class="writer-group-shell group glass-card rounded-2xl border border-emerald-200/40 bg-emerald-50/30 backdrop-blur-md shadow-[0_4px_24px_rgba(16,185,129,0.06),0_0_0_1px_rgba(255,255,255,0.5)_inset] transition-all duration-300"
							:open="isDetailOpen('writer_group', 'main')"
						>
							<summary
								class="flex cursor-pointer list-none items-start gap-3 px-4 py-3.5"
								@click.prevent="toggleDetailOpen('writer_group', 'main')"
							>
								<div class="pt-0.5">
									<div class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-100 ring-2 ring-emerald-200/50">
										<PenLine class="h-4 w-4 text-emerald-600" />
									</div>
								</div>
								<div class="min-w-0 flex-1">
									<div class="flex min-w-0 items-center gap-2">
										<span class="truncate text-sm font-semibold text-slate-900">论文写作</span>
										<span class="shrink-0 font-mono text-[11px] text-slate-500">{{ item.groups.length }} 个写作 Agent</span>
									</div>
									<div class="mt-1 text-xs text-slate-600">
										各问建模完成后统一撰写论文各章节
									</div>
								</div>
								<div class="flex shrink-0 items-center gap-2 pt-0.5 text-[11px] text-slate-500">
									<span>{{ item.groups.length }} 个 Agent</span>
									<ChevronDown class="h-4 w-4 transition group-open:rotate-180" />
								</div>
							</summary>

							<!-- 展开后的写作 Agent 卡片列表 -->
							<div class="writer-group-body border-t border-emerald-200/30 px-3 py-2 space-y-2">
								<details
									v-for="writerGroup in item.groups"
									:key="writerGroup.id"
									:data-group-id="writerGroup.id"
									class="group glass-card rounded-xl border border-white/20 bg-white/50 backdrop-blur-sm shadow-[0_2px_12px_rgba(0,0,0,0.02)] transition-all duration-300 hover:shadow-[0_4px_16px_rgba(59,130,246,0.08)] hover:border-blue-200/30"
									:class="{ 'active-agent-glow': activeGroupIds.has(writerGroup.id) && writerGroup.status !== 'done', 'card-pulse': pulseGroupIds.has(writerGroup.id) || writerGroup.actions.some(a => newActionIds.has(a.id)) }"
									:open="isDetailOpen('writer_group', writerGroup.id)"
								>
									<summary
										class="flex cursor-pointer list-none items-start gap-2.5 px-3 py-2.5"
										@click.prevent="toggleDetailOpen('writer_group', writerGroup.id)"
									>
										<div class="pt-0.5">
											<PenLine class="h-4 w-4 text-emerald-600" />
										</div>
										<div class="min-w-0 flex-1">
											<div class="flex min-w-0 items-center gap-1.5">
												<span class="truncate text-xs font-semibold text-slate-800">{{ writerGroup.name }}</span>
												<span class="rounded-full border px-1.5 py-0.5 text-[10px]" :class="statusClass(writerGroup.status)">{{ statusLabel(writerGroup.status) }}</span>
												<span class="shrink-0 font-mono text-[10px] text-slate-500">{{ formatDuration(writerGroup.durationMs) }}</span>
											</div>
											<div class="mt-0.5 flex items-center gap-1.5 overflow-hidden">
												<span class="work-state-pill" :class="groupWorkPillClass(writerGroup.id)">
													{{ groupWorkStateLabel(writerGroup.id) }}
												</span>
												<span v-if="groupWorkStatus[writerGroup.id]?.state === 'commanded'" class="work-dot" />
												<span class="truncate text-[10px]" :class="groupWorkClass(writerGroup.id)">
													{{ groupWorkStatus[writerGroup.id]?.text ?? writerGroup.role }}
												</span>
											</div>
										</div>
										<div class="flex shrink-0 items-center gap-1.5 text-[10px] text-slate-500">
											<span>{{ writerGroup.actions.length }} 条</span>
											<ChevronDown class="h-3.5 w-3.5 transition group-open:rotate-180" />
										</div>
									</summary>

									<div class="group-action-shell">
										<div :ref="(element) => setGroupScrollRef(writerGroup.id, element)" class="group-action-window border-t border-slate-100">
											<div class="divide-y divide-white/10">
												<div
													v-for="action in writerGroup.actions"
													:key="action.id"
													class="action-line px-3 py-2"
													:class="{ 'card-merge': newActionIds.has(action.id) }"
												>
													<div class="flex min-w-0 items-center gap-2">
														<span class="shrink-0 font-mono text-[10px] text-slate-400">{{ action.timeLabel }}</span>
														<span v-if="action.status === 'running'" class="shrink-0 font-mono text-[10px] text-blue-500">{{ formatDuration(action.durationMs) }}</span>
														<LoaderCircle v-if="action.status === 'running'" class="h-3.5 w-3.5 shrink-0 animate-spin text-blue-600" />
														<CheckCircle2 v-else-if="action.status === 'done'" class="h-3.5 w-3.5 shrink-0 text-slate-300" />
														<CircleAlert v-else-if="action.status === 'warning'" class="h-3.5 w-3.5 shrink-0 text-amber-600" />
														<CircleX v-else-if="action.status === 'error'" class="h-3.5 w-3.5 shrink-0 text-red-600" />
														<Clock3 v-else class="h-3.5 w-3.5 shrink-0 text-slate-300" />
														<span class="shrink min-w-0 truncate text-[0.72rem]" :class="actionTitleChipClass(action)">{{ action.title }}</span>
														<span v-if="action.status === 'running'" class="shrink-0 rounded-full border border-blue-200 bg-blue-50 px-1 py-0.5 text-[9px] text-blue-700">进行中</span>
														<span v-else-if="action.status === 'warning' || action.status === 'error'" class="shrink-0 rounded-full border px-1 py-0.5 text-[9px]" :class="statusClass(action.status)">{{ statusLabel(action.status) }}</span>
													</div>
												</div>
											</div>
										</div>
									</div>
								</details>
							</div>
						</details>

					</template>
				</div>
			</div>
		</div>

	</div>
</template>

<style scoped>
/* ====== 液态玻璃根容器 ====== */
.glass-root {
	background: linear-gradient(135deg, rgba(248,250,252,0.95) 0%, rgba(241,245,249,0.9) 30%, rgba(226,232,240,0.85) 60%, rgba(241,245,249,0.9) 100%);
	backdrop-filter: blur(20px);
	-webkit-backdrop-filter: blur(20px);
}

.glass-root::before {
	content: "";
	position: absolute;
	inset: 0;
	background: radial-gradient(ellipse 80% 60% at 50% -10%, rgba(147,197,253,0.12), transparent 60%),
		radial-gradient(ellipse 60% 50% at 80% 80%, rgba(167,139,250,0.08), transparent 55%),
		radial-gradient(ellipse 50% 40% at 10% 50%, rgba(56,189,248,0.06), transparent 50%);
	pointer-events: none;
	z-index: 0;
}

/* ====== 头部栏 ====== */
.glass-header {
	background: rgba(255,255,255,0.55);
	backdrop-filter: blur(16px);
	-webkit-backdrop-filter: blur(16px);
	position: relative;
	z-index: 1;
}

.agent-status-collapsed .glass-header {
	padding-top: 0.5rem;
	padding-bottom: 0.5rem;
}
/* ====== 并行 Agent 胶囊 ====== */
.parallel-agent-pills {
	display: flex;
	align-items: center;
	min-height: 2.25rem;
	max-width: 100%;
	overflow-x: auto;
	overflow-y: visible;
	padding: 0.2rem 0.4rem 0.2rem 0;
}

.parallel-agent-pill {
	--pill-width: 10rem;
	position: relative;
	z-index: 1;
	display: inline-flex;
	align-items: center;
	gap: 0.35rem;
	width: var(--pill-width);
	max-width: var(--pill-width);
	min-width: var(--pill-width);
	height: 1.9rem;
	border-radius: 999px;
	border: 1px solid rgba(147, 197, 253, 0.55);
	background: rgba(239, 246, 255, 0.88);
	backdrop-filter: blur(12px);
	-webkit-backdrop-filter: blur(12px);
	padding: 0 0.65rem;
	font-size: 0.72rem;
	line-height: 1;
	color: #2563eb;
	box-shadow: 0 0 14px rgba(59, 130, 246, 0.14);
	transition:
		margin 220ms ease,
		width 220ms ease,
		max-width 220ms ease,
		min-width 220ms ease,
		transform 220ms ease,
		opacity 220ms ease,
		box-shadow 220ms ease;
}

.parallel-agent-pill + .parallel-agent-pill {
	margin-left: calc(var(--pill-width) * -0.7);
}

/* 悬停任意胶囊时：非悬停的胶囊变半透明 */
.parallel-agent-pills:has(.parallel-agent-pill:hover) .parallel-agent-pill:not(:hover) {
	opacity: 0.45;
}

/* 悬停胶囊右侧的兄弟：用正常间距向右散开 */
.parallel-agent-pill:hover ~ .parallel-agent-pill {
	margin-left: 0.4rem;
}

/* 悬停的胶囊：原地展开，浮起，盖住左侧 */
.parallel-agent-pill:hover {
	z-index: 20;
	width: 18rem;
	max-width: 18rem;
	min-width: 18rem;
	opacity: 1 !important;
	transform: translateY(-1px);
	box-shadow: 0 0 18px rgba(59, 130, 246, 0.22), 0 6px 18px rgba(15, 23, 42, 0.08);
}

.parallel-agent-more {
	flex-shrink: 0;
	display: inline-flex;
	align-items: center;
	justify-content: center;
	height: 2rem;
	min-width: 2rem;
	padding: 0 0.45rem;
	border-radius: 999px;
	border: 1px solid rgba(148, 163, 184, 0.4);
	background: rgba(248, 250, 252, 0.75);
	font-size: 0.7rem;
	font-weight: 700;
	color: #64748b;
	margin-left: 0.2rem;
}

.parallel-agent-pill-working {
	border-color: rgba(96, 165, 250, 0.65);
	background: linear-gradient(90deg, rgba(239, 246, 255, 0.96), rgba(238, 242, 255, 0.88));
	color: #2563eb;
}

.parallel-agent-pill-commanded {
	border-color: rgba(251, 191, 36, 0.62);
	background: linear-gradient(90deg, rgba(255, 251, 235, 0.96), rgba(254, 243, 199, 0.88));
	color: #a16207;
}

.parallel-agent-pill-name {
	min-width: 0;
	max-width: 8.5rem;
	overflow: hidden;
	white-space: nowrap;
	text-overflow: ellipsis;
	font-weight: 700;
}

.parallel-agent-pill-detail {
	display: none;
	min-width: 0;
	overflow: hidden;
	white-space: nowrap;
	text-overflow: ellipsis;
	font-weight: 500;
}

.parallel-agent-pill:hover .parallel-agent-pill-name {
	max-width: 7rem;
}

.parallel-agent-pill:hover .parallel-agent-pill-detail {
	display: inline;
	max-width: 7rem;
}

.parallel-agent-pill-time {
	margin-left: auto;
	font-family: "Cascadia Code", "Fira Code", "JetBrains Mono", ui-monospace, monospace;
	font-size: 0.66rem;
	opacity: 0.82;
}


.agent-status-collapsed .main-scroll-shell {
	background: rgba(255,255,255,0.22);
}

.agent-status-collapsed .agent-scroll {
	padding-top: 0.5rem;
	padding-bottom: 0.75rem;
}

.agent-status-collapsed .glass-card > summary {
	padding-top: 0.55rem;
	padding-bottom: 0.55rem;
}

.agent-status-collapsed .group-action-shell {
	display: none;
}

/* ====== 液态玻璃药丸 ====== */
.glass-pill {
	position: relative;
	z-index: 1;
	transition: box-shadow 0.4s ease, border-color 0.4s ease;
}

.glass-pill:hover {
	box-shadow: 0 0 20px rgba(59,130,246,0.25), 0 0 40px rgba(59,130,246,0.08) !important;
	border-color: rgba(59,130,246,0.5) !important;
}

/* ====== Agent 玻璃卡片 ====== */
.glass-card {
	position: relative;
	z-index: 1;
}

.glass-card::after {
	content: "";
	position: absolute;
	inset: 0;
	border-radius: inherit;
	background: linear-gradient(135deg, rgba(255,255,255,0.4) 0%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.3) 100%);
	pointer-events: none;
	opacity: 0;
	transition: opacity 0.4s ease;
}

.glass-card:hover::after {
	opacity: 1;
}


	/* ====== 子问题分组包裹卡片 ====== */
	.question-group-shell {
		position: relative;
		z-index: 1;
		border-color: rgba(245, 158, 11, 0.25);
		background: linear-gradient(135deg, rgba(254, 243, 199, 0.25) 0%, rgba(255, 251, 235, 0.18) 40%, rgba(248, 250, 252, 0.22) 100%);
	}

	.question-group-shell::before {
		content: "";
		position: absolute;
		inset: 0;
		border-radius: inherit;
		background: radial-gradient(ellipse 60% 35% at 50% 0%, rgba(245, 158, 11, 0.08), transparent 55%);
		pointer-events: none;
	}

	.question-group-active {
		border-color: rgba(245, 158, 11, 0.5) !important;
		box-shadow: 0 0 16px 2px rgba(245, 158, 11, 0.14), 0 0 32px 6px rgba(245, 158, 11, 0.06), 0 0 0 1px rgba(255, 255, 255, 0.5) inset !important;
	}

	.question-group-body {
		background: rgba(255, 251, 235, 0.15);
		backdrop-filter: blur(8px);
		-webkit-backdrop-filter: blur(8px);
	}
/* ====== 滚动条 ====== */
.agent-scroll {
	mask-image: linear-gradient(to bottom, transparent 0, #000 1.25rem, #000 100%);
	-webkit-mask-image: linear-gradient(to bottom, transparent 0, #000 1.25rem, #000 100%);
}

.agent-scroll::-webkit-scrollbar {
	width: 4px;
}

.agent-scroll::-webkit-scrollbar-track {
	background: transparent;
}

.agent-scroll::-webkit-scrollbar-thumb {
	border-radius: 999px;
	background: rgba(148,163,184,0.35);
	backdrop-filter: blur(4px);
}

.agent-scroll::-webkit-scrollbar-thumb:hover {
	background: rgba(100,116,139,0.5);
}

/* ====== 主滚动壳 ====== */
.main-scroll-shell {
	flex: 1;
	min-height: 0;
	position: relative;
	overflow: hidden;
	background: rgba(255,255,255,0.35);
	backdrop-filter: blur(12px);
	-webkit-backdrop-filter: blur(12px);
}

.main-scroll-shell::before {
	content: "";
	position: absolute;
	inset: 0;
	background: radial-gradient(ellipse 50% 40% at 50% 50%, rgba(147,197,253,0.08), transparent 70%);
	pointer-events: none;
	z-index: 0;
}

/* ====== Group 指示器 ====== */
.group {
	position: relative;
}

.summary-action-viewport {
	position: relative;
	height: 1rem;
	overflow: hidden;
}

.summary-action-line {
	display: block;
	line-height: 1rem;
	will-change: transform, opacity, filter;
}

.summary-roll-enter-active,
.summary-roll-leave-active {
	transition:
		transform 0.34s cubic-bezier(0.22, 1, 0.36, 1),
		opacity 0.24s ease,
		filter 0.34s ease;
}

.summary-roll-enter-from {
	opacity: 0;
	transform: translateY(110%);
	filter: blur(2px);
}

.summary-roll-leave-to {
	opacity: 0;
	transform: translateY(-85%);
	filter: blur(2px);
}

/* ====== 动作面板壳 ====== */
.group-action-shell {
	position: relative;
	background: rgba(255,255,255,0.45);
	backdrop-filter: blur(12px);
	-webkit-backdrop-filter: blur(12px);
	border-radius: 0 0 1rem 1rem;
}

.group-action-shell::before {
	content: "";
	position: absolute;
	inset: 0;
	border-radius: inherit;
	background: linear-gradient(180deg, rgba(255,255,255,0.3) 0%, rgba(255,255,255,0.05) 100%);
	pointer-events: none;
}

/* ====== 动作窗口 ====== */
.group-action-window {
	max-height: 15.75rem;
	overflow-y: auto;
	overscroll-behavior: contain;
	background: transparent;
	mask-image: linear-gradient(to bottom, transparent 0, #000 1rem, #000 100%);
	-webkit-mask-image: linear-gradient(to bottom, transparent 0, #000 1rem, #000 100%);
}

.group-action-window::-webkit-scrollbar {
	width: 4px;
}

.group-action-window::-webkit-scrollbar-track {
	background: transparent;
}

.group-action-window::-webkit-scrollbar-thumb {
	border-radius: 999px;
	background: rgba(148,163,184,0.3);
}

/* ====== 展开内容滚动条 ====== */
.expanded-inline::-webkit-scrollbar {
	width: 4px;
}

.expanded-inline::-webkit-scrollbar-track {
	background: transparent;
}

.expanded-inline::-webkit-scrollbar-thumb {
	border-radius: 999px;
	background: rgba(148,163,184,0.3);
}

/* ====== 动作行 ====== */
.action-line {
	min-height: 4.6rem;
	border-radius: 10px;
	margin: 2px 6px;
	background: rgba(255,255,255,0.3);
	backdrop-filter: blur(4px);
	-webkit-backdrop-filter: blur(4px);
	border: 1px solid rgba(255,255,255,0.4);
	transition: background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
}

.action-line:hover {
	background: rgba(255,255,255,0.55);
	border-color: rgba(148,163,184,0.25);
	box-shadow: 0 2px 12px rgba(0,0,0,0.04), 0 0 0 1px rgba(255,255,255,0.6) inset;
}

.action-detail-slot {
	min-height: 2.1rem;
	padding-left: 7.25rem;
}

/* ====== 折叠预览文本 ====== */
.detail-preview {
	display: -webkit-box;
	max-height: 2rem;
	overflow: hidden;
	color: #64748b;
	font-size: 0.72rem;
	line-height: 1rem;
	-webkit-box-orient: vertical;
	-webkit-line-clamp: 2;
	mask-image: linear-gradient(to bottom, #000 72%, transparent 100%);
	-webkit-mask-image: linear-gradient(to bottom, #000 72%, transparent 100%);
}

/* ====== 代码预览 ====== */
.code-preview {
	position: relative;
	max-height: 2.1rem;
	overflow: hidden;
	border-left: 2px solid rgba(148,163,184,0.35);
	border-radius: 0 6px 6px 0;
	background: linear-gradient(90deg, rgba(241,245,249,0.7), rgba(241,245,249,0));
	padding: 0.12rem 0.5rem;
	font-size: 0.68rem;
	line-height: 1rem;
	color: #64748b;
	white-space: pre-wrap;
	word-break: break-word;
	mask-image: linear-gradient(to bottom, #000 72%, transparent 100%);
	-webkit-mask-image: linear-gradient(to bottom, #000 72%, transparent 100%);
}

/* ====== 输入栏 ====== */
.glass-input-bar {
	background: rgba(255,255,255,0.5);
	backdrop-filter: blur(16px);
	-webkit-backdrop-filter: blur(16px);
	position: relative;
	z-index: 1;
}

/* ====== 新动作卡牌浮现动画 ====== */
.card-merge {
	position: relative;
	overflow: visible;
}

.card-merge::before {
	content: "";
	position: absolute;
	inset: -4px;
	border-radius: 12px;
	background: radial-gradient(ellipse 80% 60% at 50% 30%, rgba(59,130,246,0.18), transparent 70%);
	opacity: 0;
	animation: card-merge-shadow 1s ease-out forwards;
	pointer-events: none;
	z-index: -1;
}

@keyframes card-merge-shadow {
	0% { opacity: 0; transform: translateY(12px) scale(0.96); }
	30% { opacity: 1; transform: translateY(0) scale(1); }
	100% { opacity: 0; transform: translateY(0) scale(1); }
}

/* ====== 卡片新动作：蓝色光圈吸入 + 弹性缩放 ====== */
.card-pulse {
	animation: card-spring-bounce 0.85s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.card-pulse::after {
	content: "";
	position: absolute;
	inset: -6px;
	border-radius: 20px;
	border: 2px solid rgba(59,130,246,0.55);
	pointer-events: none;
	animation: ring-absorb 0.7s cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

@keyframes ring-absorb {
	0% {
		opacity: 1;
		inset: -6px;
		border-width: 2px;
	}
	60% {
		opacity: 0.6;
		inset: -2px;
		border-width: 1.5px;
	}
	100% {
		opacity: 0;
		inset: -1px;
		border-width: 1px;
	}
}

@keyframes card-spring-bounce {
	0% { transform: scale(1); }
	15% { transform: scale(0.975); }
	45% { transform: scale(1.008); }
	70% { transform: scale(0.996); }
	100% { transform: scale(1); }
}

/* ====== 活跃 Agent 呼吸光效 ====== */
.active-agent-glow {
	animation: agent-glow-pulse 2.8s ease-in-out infinite alternate;
	border-color: rgba(59,130,246,0.3) !important;
	box-shadow: 0 0 12px 2px rgba(59,130,246,0.2), 0 0 30px 6px rgba(59,130,246,0.08), 0 0 0 1px rgba(255,255,255,0.5) inset;
}

@keyframes agent-glow-pulse {
	from {
		box-shadow: 0 0 8px 2px rgba(59,130,246,0.14), 0 0 20px 4px rgba(59,130,246,0.04), 0 0 0 1px rgba(255,255,255,0.4) inset;
	}
	to {
		box-shadow: 0 0 16px 3px rgba(59,130,246,0.3), 0 0 36px 8px rgba(59,130,246,0.12), 0 0 0 1px rgba(255,255,255,0.6) inset;
	}
}

/* ====== Agent 当前工作状态 - 三态动画 ====== */

.work-state-pill {

	display: inline-flex;
	flex-shrink: 0;
	align-items: center;
	border-radius: 999px;
	border: 1px solid;
	padding: 0.05rem 0.42rem;
	font-size: 10px;
	font-weight: 700;
	line-height: 1rem;
}

.work-pill-idle {
	border-color: #e2e8f0;
	background: rgba(248, 250, 252, 0.9);
	color: #94a3b8;
}

.work-pill-commanded {
	border-color: rgba(251, 191, 36, 0.55);
	background: linear-gradient(90deg, rgba(255, 251, 235, 0.98), rgba(254, 243, 199, 0.82));
	color: #a16207;
	box-shadow: 0 0 12px rgba(245, 158, 11, 0.12);
}

.work-pill-working {
	border-color: rgba(96, 165, 250, 0.55);
	background: linear-gradient(90deg, rgba(239, 246, 255, 0.98), rgba(238, 242, 255, 0.85));
	color: #2563eb;
	box-shadow: 0 0 14px rgba(59, 130, 246, 0.16);
}

/* 工作中：蓝紫渐变光流 */
@keyframes work-flow {
	0%   { background-position: 180% center; }
	100% { background-position: -180% center; }
}

.work-text-working {
	background: linear-gradient(
		90deg,
		#64748b 0%,
		#3b82f6 25%,
		#818cf8 50%,
		#3b82f6 75%,
		#64748b 100%
	);
	background-size: 200% auto;
	-webkit-background-clip: text;
	background-clip: text;
	-webkit-text-fill-color: transparent;
	animation: work-flow 2.5s linear infinite;
	font-weight: 500;
}

/* 已下达指令：琥珀色脉冲圆点 */
@keyframes dot-pulse {
	0%, 100% { opacity: 1;    transform: scale(1); }
	50%       { opacity: 0.3; transform: scale(0.65); }
}

.work-dot {
	flex-shrink: 0;
	display: inline-block;
	width: 5px;
	height: 5px;
	border-radius: 50%;
	background: #f59e0b;
	align-self: center;
	animation: dot-pulse 1.2s ease-in-out infinite;
}

.work-text-commanded {
	color: #92400e;
	font-weight: 500;
	text-shadow: 0 0 10px rgba(245, 158, 11, 0.18);
}

/* 空闲 / 已完成：静态灰 */
.work-text-idle {
	color: #94a3b8;
}


/* ====== 文件动作芯片（工具 / 读取 / 写入 / 输出四色） ====== */
.file-action-chip {
	padding: 0 5px;
	border-radius: 4px;
	font-family: "Cascadia Code", "Fira Code", "JetBrains Mono", ui-monospace, monospace;
	font-size: 10px;
	white-space: nowrap;
	border: 1px solid;
	text-decoration-line: underline;
	text-underline-offset: 2px;
}

.chip-violet {
	background: #f5f3ff;
	color: #7c3aed;
	border-color: #ddd6fe;
}

.chip-blue {
	background: #eff6ff;
	color: #2563eb;
	border-color: #bfdbfe;
}

.chip-amber {
	background: #fffbeb;
	color: #d97706;
	border-color: #fde68a;
}

.chip-green {
	background: #ecfdf5;
	color: #059669;
	border-color: #a7f3d0;
}

/* ====== 文件动作动词标签 ====== */
.action-verb-chip {
	display: inline-block;
	padding: 0 5px;
	border-radius: 4px;
	background: #f8fafc;
	color: #64748b;
	font-size: 10px;
	border: 1px solid #e2e8f0;
	white-space: nowrap;
}

.action-verb-tool {
	background: #f5f3ff;
	color: #6d28d9;
	border-color: #ddd6fe;
}

.action-verb-file {
	background: #f8fafc;
	color: #475569;
	border-color: #dbe3ef;
}

.action-verb-output {
	background: #ecfdf5;
	color: #047857;
	border-color: #a7f3d0;
}

.action-verb-user {
	background: #eef2ff;
	color: #4338ca;
	border-color: #c7d2fe;
}

.action-verb-system {
	background: #eff6ff;
	color: #1d4ed8;
	border-color: #bfdbfe;
}

.action-verb-coordinator {
	background: #ecfeff;
	color: #0e7490;
	border-color: #a5f3fc;
}

.action-verb-sub-coordinator {
	background: #f0fdf4;
	color: #15803d;
	border-color: #bbf7d0;
}

.action-verb-coder {
	background: #f1f5f9;
	color: #334155;
	border-color: #cbd5e1;
}

.action-verb-writer {
	background: #fffbeb;
	color: #b45309;
	border-color: #fed7aa;
}

.action-verb-modeler {
	background: #eff6ff;
	color: #1d4ed8;
	border-color: #bfdbfe;
}

.action-verb-default {
	background: #f8fafc;
	color: #64748b;
	border-color: #e2e8f0;
}

.action-file-chip {
	padding: 0 7px;
	border-radius: 999px;
	font-family: "Cascadia Code", "Fira Code", "JetBrains Mono", ui-monospace, monospace;
	font-size: 10px;
	font-weight: 600;
	line-height: 1.25rem;
	white-space: nowrap;
	border: 1px solid;
	text-decoration-line: underline;
	text-underline-offset: 2px;
	box-shadow: 0 1px 6px rgba(15, 23, 42, 0.04);
}

.action-title-chip {
	display: inline-flex;
	min-width: 0;
	max-width: 22rem;
	align-items: center;
	border: 1px solid;
	border-radius: 999px;
	padding: 0.12rem 0.58rem;
	font-size: 0.78rem;
	font-weight: 650;
	line-height: 1.15rem;
	white-space: nowrap;
	box-shadow: 0 1px 8px rgba(15, 23, 42, 0.04);
}

.action-title-flow {
	background: linear-gradient(90deg, rgba(253, 242, 248, 0.98), rgba(245, 243, 255, 0.96), rgba(236, 252, 255, 0.9));
	color: #a21caf;
	border-color: rgba(217, 70, 239, 0.42);
	box-shadow: 0 0 14px rgba(217, 70, 239, 0.12);
}

.action-title-tool {
	background: linear-gradient(90deg, rgba(245, 243, 255, 0.98), rgba(250, 245, 255, 0.92));
	color: #6d28d9;
	border-color: #ddd6fe;
}

.action-title-output {
	background: linear-gradient(90deg, rgba(236, 253, 245, 0.98), rgba(240, 253, 250, 0.92));
	color: #047857;
	border-color: #a7f3d0;
}

.action-title-file {
	background: linear-gradient(90deg, rgba(236, 254, 255, 0.98), rgba(239, 246, 255, 0.92));
	color: #0e7490;
	border-color: #a5f3fc;
}

.action-title-progress {
	background: linear-gradient(90deg, rgba(239, 246, 255, 0.98), rgba(224, 242, 254, 0.92));
	color: #1d4ed8;
	border-color: #bfdbfe;
}

.action-title-user {
	background: linear-gradient(90deg, rgba(238, 242, 255, 0.98), rgba(245, 243, 255, 0.92));
	color: #4338ca;
	border-color: #c7d2fe;
}

.action-title-writer {
	background: linear-gradient(90deg, rgba(255, 247, 237, 0.98), rgba(254, 243, 199, 0.82));
	color: #b45309;
	border-color: #fed7aa;
}

.action-title-coder {
	background: linear-gradient(90deg, rgba(241, 245, 249, 0.98), rgba(226, 232, 240, 0.8));
	color: #334155;
	border-color: #cbd5e1;
}

.action-title-modeler {
	background: linear-gradient(90deg, rgba(239, 246, 255, 0.98), rgba(238, 242, 255, 0.86));
	color: #1d4ed8;
	border-color: #bfdbfe;
}

.action-title-coordinator {
	background: linear-gradient(90deg, rgba(236, 254, 255, 0.98), rgba(240, 253, 250, 0.86));
	color: #0e7490;
	border-color: #a5f3fc;
}

.action-title-sub-coordinator {
	background: linear-gradient(90deg, rgba(240, 253, 244, 0.98), rgba(236, 254, 255, 0.86));
	color: #15803d;
	border-color: #bbf7d0;
}

.action-title-default {
	background: rgba(248, 250, 252, 0.95);
	color: #334155;
	border-color: #e2e8f0;
}

.coordination-chip {
	display: inline-flex;
	align-items: center;
	gap: 0.2rem;
	border-radius: 999px;
	border: 1px solid rgba(251, 146, 60, 0.38);
	background: linear-gradient(90deg, rgba(255, 247, 237, 0.98), rgba(236, 253, 245, 0.92));
	padding: 0.12rem 0.55rem;
	font-size: 10px;
	font-weight: 650;
	line-height: 1.1rem;
	color: #c2410c;
	box-shadow: 0 1px 8px rgba(251, 146, 60, 0.08);
}

.workflow-chip {
	position: relative;
	display: inline-flex;
	align-items: center;
	gap: 0.25rem;
	max-width: min(24rem, 48vw);
	overflow: hidden;
	border-radius: 999px;
	border: 1px solid rgba(99, 102, 241, 0.28);
	background:
		linear-gradient(90deg, rgba(238, 242, 255, 0.96), rgba(236, 253, 245, 0.94), rgba(255, 247, 237, 0.96)),
		repeating-linear-gradient(135deg, rgba(99, 102, 241, 0.12) 0 6px, rgba(20, 184, 166, 0.1) 6px 12px, rgba(251, 146, 60, 0.1) 12px 18px);
	background-blend-mode: screen;
	padding: 0.12rem 0.55rem;
	font-size: 10px;
	font-weight: 700;
	line-height: 1.1rem;
	color: #334155;
	box-shadow: 0 1px 10px rgba(99, 102, 241, 0.1);
}

.workflow-chip::before {
	content: "";
	position: absolute;
	inset: 0;
	background: linear-gradient(110deg, transparent 0%, rgba(255, 255, 255, 0.75) 45%, transparent 70%);
	transform: translateX(-120%);
	animation: workflow-shimmer 2.8s ease-in-out infinite;
	pointer-events: none;
}

@keyframes workflow-shimmer {
	0%, 45% { transform: translateX(-120%); }
	75%, 100% { transform: translateX(120%); }
}

.workflow-party,
.workflow-label,
.workflow-arrow {
	position: relative;
	z-index: 1;
	white-space: nowrap;
}

.workflow-party {
	color: #4338ca;
}

.workflow-arrow {
	color: #0f766e;
}

.workflow-label {
	min-width: 0;
	overflow: hidden;
	text-overflow: ellipsis;
	color: #c2410c;
}

/* ====== 子问题流水线视图 ====== */
.pipeline-section {
	background: rgba(255, 255, 255, 0.3);
	backdrop-filter: blur(8px);
	-webkit-backdrop-filter: blur(8px);
}

.pipeline-row {
	display: flex;
	align-items: center;
	gap: 0.5rem;
	padding: 0.18rem 0;
}

.pipeline-label {
	font-size: 0.67rem;
	font-weight: 700;
	color: #f59e0b;
	min-width: 1.6rem;
	font-family: ui-monospace, "Cascadia Code", monospace;
	flex-shrink: 0;
}

.pipeline-nodes {
	display: flex;
	align-items: center;
	gap: 0.28rem;
	overflow-x: auto;
}

.pipeline-node {
	display: inline-flex;
	align-items: center;
	gap: 0.18rem;
	border-radius: 999px;
	border: 1px solid;
	padding: 0.06rem 0.45rem;
	font-size: 0.67rem;
	font-weight: 600;
	line-height: 1.4;
	white-space: nowrap;
	transition: box-shadow 0.3s ease, border-color 0.3s ease;
}

.pipeline-node-pending {
	border-color: #e2e8f0;
	color: #94a3b8;
	background: rgba(248, 250, 252, 0.75);
}

.pipeline-node-running {
	border-color: rgba(96, 165, 250, 0.65);
	background: linear-gradient(90deg, rgba(239, 246, 255, 0.95), rgba(238, 242, 255, 0.85));
	color: #2563eb;
	animation: node-glow 2s ease-in-out infinite alternate;
}

@keyframes node-glow {
	from { box-shadow: 0 0 6px rgba(59, 130, 246, 0.14); }
	to   { box-shadow: 0 0 14px rgba(59, 130, 246, 0.3); }
}

.pipeline-node-done {
	border-color: rgba(134, 239, 172, 0.65);
	background: rgba(240, 253, 244, 0.85);
	color: #16a34a;
}

.pipeline-node-error {
	border-color: rgba(252, 165, 165, 0.65);
	background: rgba(254, 242, 242, 0.85);
	color: #dc2626;
}

.pipeline-node-warning {
	border-color: rgba(251, 191, 36, 0.65);
	background: rgba(255, 251, 235, 0.85);
	color: #d97706;
}

.pipeline-arrow {
	font-size: 0.65rem;
	color: #cbd5e1;
	flex-shrink: 0;
	line-height: 1;
}

/* ====== 最近通信记录 ====== */
.comms-section {
	background: linear-gradient(
		135deg,
		rgba(255, 255, 255, 0.18) 0%,
		rgba(255, 255, 255, 0.10) 40%,
		rgba(255, 255, 255, 0.16) 100%
	);
	backdrop-filter: blur(18px);
	-webkit-backdrop-filter: blur(18px);
	border-radius: 14px;
	margin: 0 10px;
	box-shadow:
		0 4px 24px rgba(0, 0, 0, 0.03),
		inset 0 1px 0 rgba(255, 255, 255, 0.5),
		inset 0 -1px 0 rgba(255, 255, 255, 0.08);
}

.comms-header {
	font-size: 0.62rem;
	font-weight: 700;
	text-transform: uppercase;
	letter-spacing: 0.05em;
	color: #94a3b8;
	margin-bottom: 0.3rem;
}

/* Grid 对齐：4列 = 发出者 | 箭头 | 接收者 | 任务，每行对齐 */
.comms-list {
	display: grid;
	grid-template-columns: auto 1.2rem auto auto;
	row-gap: 0.3rem;
	column-gap: 0.3rem;
	align-items: center;
	/* 最多露出 3 行，多了滚动 */
	max-height: calc(1.65rem * 3 + 0.3rem * 2);
	overflow-y: auto;
	overflow-x: hidden;
	padding-right: 2px;
}

.comms-list::-webkit-scrollbar {
	width: 3px;
}

.comms-list::-webkit-scrollbar-track {
	background: transparent;
}

.comms-list::-webkit-scrollbar-thumb {
	border-radius: 999px;
	background: rgba(148, 163, 184, 0.3);
}

/* 发出者 / 接收者共用基础胶囊 */
.comms-party-pill {
	position: relative;        /* 给 ::before 光束定位用 */
	display: inline-flex;
	align-items: center;
	justify-content: center;
	height: 1.65rem;
	border-radius: 999px;
	border: 1px solid;
	padding: 0 0.55rem;
	font-size: 0.67rem;
	font-weight: 700;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
	max-width: 8rem;
	backdrop-filter: blur(8px);
	-webkit-backdrop-filter: blur(8px);
	transition: box-shadow 0.3s ease, border-color 0.3s ease;
}

/* 发出者：蓝紫色玻璃 */
.comms-from-pill {
	border-color: rgba(99, 102, 241, 0.25);
	background: linear-gradient(135deg, rgba(238, 242, 255, 0.65), rgba(224, 231, 255, 0.50));
	color: #4338ca;
	box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.5);
}

.comms-from-pill:hover {
	border-color: rgba(99, 102, 241, 0.4);
	box-shadow: 0 0 12px rgba(99, 102, 241, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.5);
}

/* 接收者：青绿色玻璃 */
.comms-to-pill {
	border-color: rgba(20, 184, 166, 0.25);
	background: linear-gradient(135deg, rgba(240, 253, 250, 0.65), rgba(209, 250, 229, 0.50));
	color: #0f766e;
	box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.5);
}

.comms-to-pill:hover {
	border-color: rgba(20, 184, 166, 0.4);
	box-shadow: 0 0 12px rgba(20, 184, 166, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.5);
}

/* 中间箭头 */
.comms-grid-arrow {
	display: inline-block; /* transform 需要 block 级 */
	text-align: center;
	color: #94a3b8;
	font-size: 0.65rem;
	font-weight: 500;
	line-height: 1;
	transform-origin: center;
}

/* 任务胶囊 — 玻璃材质，::before 环绕光点柔和照亮边框 */
.comms-label-pill {
	position: relative;
	display: inline-flex;
	align-items: center;
	height: 1.65rem;
	border-radius: 999px;
	border: 1px solid rgba(203, 213, 225, 0.30);
	background: rgba(248, 250, 252, 0.55);
	backdrop-filter: blur(10px);
	-webkit-backdrop-filter: blur(10px);
	padding: 0 0.6rem;
	font-size: 0.66rem;
	color: #64748b;
	font-style: italic;
	white-space: nowrap;
	max-width: 14rem;
	box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.45);
	transition: box-shadow 0.35s ease, border-color 0.35s ease;
}

.comms-label-pill:hover {
	border-color: rgba(167, 139, 250, 0.25);
	box-shadow: 0 0 12px rgba(167, 139, 250, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.5);
}

.comms-label-empty {
	color: #cbd5e1;
	font-style: normal;
	border-color: rgba(226, 232, 240, 0.4);
}

/* ======================================================
   通信流光三段特效（浅色版）
   同一个 3.6s 循环：
     ① 0%–50%   发出者：淡光束从左扫向右
     ② 35%–65%  箭头：  轻柔中继闪光
     ③ 50%–88%  接收者：淡光束涌入 + 微弱外发光
   + ④ 任务胶囊：持续慢速旋转光晕
   ====================================================== */

/* ① 发出者光束（柔和版） */
.comms-from-pill::before {
	content: "";
	position: absolute;
	inset: 0;
	border-radius: inherit;
	background: linear-gradient(
		90deg,
		transparent            0%,
		rgba(129,140,248,0.00) 20%,
		rgba(129,140,248,0.12) 45%,
		rgba(99, 102,241,0.14) 55%,
		transparent            80%
	);
	transform: translateX(-130%);
	animation: comms-send-beam 3.6s ease-in-out infinite;
	pointer-events: none;
}

@keyframes comms-send-beam {
	0%, 4%    { transform: translateX(-130%); opacity: 0; }
	14%       { opacity: 0.8; }
	48%       { transform: translateX(130%);  opacity: 0.55; }
	58%, 100% { transform: translateX(130%);  opacity: 0; }
}

/* ② 箭头中继闪光（减淡） */
.comms-grid-arrow {
	animation: comms-arrow-relay 3.6s ease-in-out infinite;
}

@keyframes comms-arrow-relay {
	0%, 32%   { color: #cbd5e1; filter: none;                                                                    transform: scaleX(1); }
	44%       { color: #a5b4fc; filter: drop-shadow(0 0 2px rgba(99,102,241,0.30)) drop-shadow(0 0 5px rgba(99,102,241,0.10)); transform: scaleX(1.12); }
	56%       { color: #5eead4; filter: drop-shadow(0 0 2px rgba(45,212,191,0.30)) drop-shadow(0 0 5px rgba(20,184,166,0.10)); transform: scaleX(1.06); }
	68%, 100% { color: #cbd5e1; filter: none;                                                                    transform: scaleX(1); }
}

/* ③ 接收者：涌入光束（柔和版） */
.comms-to-pill::before {
	content: "";
	position: absolute;
	inset: 0;
	border-radius: inherit;
	background: linear-gradient(
		90deg,
		rgba(45,212,191,0.12) 0%,
		rgba(20,184,166,0.08) 40%,
		rgba(20,184,166,0.02) 75%,
		transparent           100%
	);
	transform: translateX(-120%);
	animation: comms-recv-beam 3.6s ease-in-out infinite;
	pointer-events: none;
}

@keyframes comms-recv-beam {
	0%, 48%  { transform: translateX(-120%); opacity: 0; }
	58%      { opacity: 0.7; }
	68%      { transform: translateX(0%);    opacity: 0.5; }
	85%      { transform: translateX(120%);  opacity: 0; }
	100%     { transform: translateX(120%);  opacity: 0; }
}

/* ③ 接收者：消化脉冲（柔和版） */
.comms-to-pill {
	animation: comms-recv-glow 3.6s ease-in-out infinite;
}

@keyframes comms-recv-glow {
	0%,  60%  { box-shadow: inset 0 1px 0 rgba(255,255,255,0.5); }
	72%       { box-shadow: 0 0 6px 1px rgba(20,184,166,0.12), 0 0 0 2px rgba(20,184,166,0.03), inset 0 1px 0 rgba(255,255,255,0.5); }
	84%       { box-shadow: 0 0 8px 2px rgba(20,184,166,0.05), 0 0 0 4px rgba(20,184,166,0), inset 0 1px 0 rgba(255,255,255,0.5); }
	95%, 100% { box-shadow: inset 0 1px 0 rgba(255,255,255,0.5); }
}

/* ④ 任务胶囊：边框段发光 — 一段柔和光弧沿胶囊边框环绕
   原理：锥形渐变产生扇形光段 → 环形遮罩仅暴露边框区域 → 旋转实现环绕 */
.comms-label-pill::before {
	content: "";
	position: absolute;
	inset: -3px;
	border-radius: 999px;
	/* 锥形渐变：约 55° 宽的柔和光段，强度提升 */
	background: conic-gradient(
		from 0deg,
		transparent 0deg,
		rgba(167, 139, 250, 0.32) 10deg,
		rgba(167, 139, 250, 0.40) 22deg,
		rgba(129, 140, 248, 0.25) 38deg,
		rgba(99,  102, 241, 0.10) 50deg,
		transparent 58deg,
		transparent 360deg
	);
	/* 环形遮罩：只让边框圈区域露出，中心镂空 */
	-webkit-mask: radial-gradient(circle farthest-side, transparent 48%, black 52%, black 82%, transparent 86%);
	mask: radial-gradient(circle farthest-side, transparent 48%, black 52%, black 82%, transparent 86%);
	/* 轻微模糊保持柔和但更清晰 */
	filter: blur(1.2px);
	animation: comms-border-sweep 3.2s linear infinite;
	pointer-events: none;
	z-index: 0;
}

@keyframes comms-border-sweep {
	from { transform: rotate(0deg); }
	to   { transform: rotate(360deg); }
}


</style>
