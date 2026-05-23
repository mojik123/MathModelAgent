import {
	cancelTask as cancelTaskAPI,
	getTaskDiagnostics,
	getTaskMessages,
	getTaskState,
	startTask as startTaskAPI,
} from "@/apis/commonApi";
import type {
	TaskDiagnostics,
	TaskRuntimeState,
	TaskRuntimeStatus,
} from "@/apis/commonApi";
import { AgentType } from "@/utils/enum";
import type {
	AgentMessage,
	CoderMessage,
	CoordinatorMessage,
	InterpreterMessage,
	Message,
	MessageAction,
	MessageFlow,
	ModelerMessage,
	ProgressMessage,
	SystemMessage,
	SystemMessageType,
	UserMessage,
	WriterMessage,
} from "@/utils/response";
import { TaskWebSocket } from "@/utils/websocket";
import { defineStore } from "pinia";
import { computed, ref } from "vue";

export const useTaskStore = defineStore("task", () => {
	const messagesByTask = ref<Record<string, Message[]>>({});
	const currentTaskId = ref<string | null>(null);
	const seenMessageIdsByTask = new Map<string, Set<string>>();

	let ws: TaskWebSocket | null = null;
	let snapshotPollingTimer: ReturnType<typeof setInterval> | null = null;
	let snapshotSyncing = false;

	const wsStatus = ref<
		"connecting" | "connected" | "disconnected" | "reconnecting"
	>("disconnected");
	const isRunning = ref(false);
	const taskRuntimeState = ref<TaskRuntimeState | null>(null);
	const taskDiagnostics = ref<TaskDiagnostics | null>(null);

	// 建模讨论同步状态
	// 问题划分讨论同步状态
	const activeQuestionIndex = ref(-1);
	const questionCards = ref<
		Array<{
			questionIndex: number;
			questionTitle: string;
			questionText: string;
			chatHistory: Array<{ role: "user" | "assistant"; content: string }>;
		}>
	>([]);
	const originalProblemText = ref("");

	const activeDiscussionIndex = ref(-1);
	const discussionQuestions = ref<
		Array<{
			questionIndex: number;
			questionTitle: string;
			questionText: string;
			selectedOptionId: string;
			researchSummary?: string;
			presetOptions: Array<{
				id: string;
				label: string;
				description: string;
				pros?: string;
				cons?: string;
				reason?: string;
				score?: number | null;
				isRecommended?: boolean;
				sources?: string[];
			}>;
		}>
	>([]);
	const taskStatus = computed<TaskRuntimeStatus>(
		() => taskRuntimeState.value?.status ?? "ready",
	);

	const currentProgress = ref<{
		current: number;
		total: number;
		percentage: number;
		description: string;
	} | null>(null);

	const messages = computed<Message[]>(() => {
		if (!currentTaskId.value) return [];
		return messagesByTask.value[currentTaskId.value] ?? [];
	});

	function isActiveStatus(status: TaskRuntimeStatus | string | undefined) {
		return status === "running" || status === "stopping";
	}

	function terminalStatusFromSystemMessage(
		message: Message,
	): TaskRuntimeStatus | null {
		if (message.msg_type !== "system") return null;
		const content = message.content ?? "";
		if (message.type === "success" && content.includes("任务处理完成")) {
			return "completed";
		}
		if (message.type === "warning" && content.includes("任务已停止")) {
			return "stopped";
		}
		if (message.type === "error") return "failed";
		return null;
	}

	function getMessageTimestamp(message: Message): number | null {
		if (!message.created_at) return null;
		const timestamp = Date.parse(message.created_at);
		return Number.isNaN(timestamp) ? null : timestamp;
	}

	function sortMessages(items: Message[]) {
		return [...items].sort((left, right) => {
			const leftTs = getMessageTimestamp(left);
			const rightTs = getMessageTimestamp(right);
			if (leftTs == null || rightTs == null || leftTs === rightTs) return 0;
			return leftTs - rightTs;
		});
	}

	function isMessagePayload(payload: unknown): payload is Message {
		if (!payload || typeof payload !== "object") return false;
		const msgType = Reflect.get(payload, "msg_type");
		return (
			typeof Reflect.get(payload, "id") === "string" &&
			typeof msgType === "string" &&
			["system", "agent", "user", "tool", "progress"].includes(msgType)
		);
	}

	function setCurrentTask(taskId: string) {
		currentTaskId.value = taskId;
		if (typeof window !== "undefined") {
			window.localStorage.setItem("currentTaskId", taskId);
		}
	}

	function ensureTaskBucket(taskId: string) {
		if (!messagesByTask.value[taskId]) {
			messagesByTask.value[taskId] = [];
		}
		if (!seenMessageIdsByTask.has(taskId)) {
			seenMessageIdsByTask.set(taskId, new Set());
		}
	}

	function getLatestProgress(taskId: string) {
		const bucket = messagesByTask.value[taskId] ?? [];
		for (let i = bucket.length - 1; i >= 0; i--) {
			const message = bucket[i];
			if (message.msg_type === "progress") return message as ProgressMessage;
		}
		return null;
	}

	function updateProgressFromMessages(taskId: string) {
		const latestProgress = getLatestProgress(taskId);
		if (!latestProgress) {
			if (currentTaskId.value === taskId) currentProgress.value = null;
			return;
		}
		if (currentTaskId.value === taskId) {
			currentProgress.value = {
				current: latestProgress.current,
				total: latestProgress.total,
				percentage: latestProgress.percentage,
				description: latestProgress.description,
			};
		}
	}

	function hasTerminalMessage(taskId: string) {
		return (messagesByTask.value[taskId] ?? []).some(
			(message) => terminalStatusFromSystemMessage(message) != null,
		);
	}

	function hasBeenStarted(taskId: string) {
		return (messagesByTask.value[taskId] ?? []).some((msg) => {
			if (msg.msg_type === "agent" || msg.msg_type === "tool") return true;
			if (msg.msg_type === "progress") return true;
			if (msg.msg_type === "system") {
				return (msg.content ?? "").includes("任务开始处理");
			}
			return false;
		});
	}

	function deriveStatusFromMessages(taskId: string): TaskRuntimeStatus {
		const bucket = messagesByTask.value[taskId] ?? [];
		for (let i = bucket.length - 1; i >= 0; i--) {
			const message = bucket[i];
			const status = terminalStatusFromSystemMessage(message);
			if (status) return status;
		}
		return hasBeenStarted(taskId) ? "running" : "ready";
	}

	function latestStateMessage(taskId: string) {
		const progress = getLatestProgress(taskId);
		if (progress?.description) return progress.description;
		const bucket = messagesByTask.value[taskId] ?? [];
		for (let i = bucket.length - 1; i >= 0; i--) {
			const message = bucket[i];
			if (message.msg_type === "system" && message.content) {
				return message.content;
			}
		}
		return "";
	}

	function applyRuntimeState(state: TaskRuntimeState) {
		taskRuntimeState.value = state;
		if (
			currentTaskId.value === state.task_id &&
			typeof state.progress === "number" &&
			!Number.isNaN(state.progress)
		) {
			const description = state.current_step || state.message || "";
			currentProgress.value = {
				current: state.progress,
				total: 100,
				percentage: Math.max(0, Math.min(100, Math.round(state.progress))),
				description,
			};
		}
		isRunning.value = isActiveStatus(state.status);
		if (!isActiveStatus(state.status)) {
			stopSnapshotPolling();
		}
	}

	function applyTerminalSystemMessage(taskId: string, message: Message) {
		const status = terminalStatusFromSystemMessage(message);
		if (!status) return;
		taskRuntimeState.value = {
			task_id: taskId,
			status,
			message: message.content ?? "",
			current_step: taskRuntimeState.value?.current_step ?? "",
			updated_at: message.created_at,
			active: false,
		};
		isRunning.value = false;
		stopSnapshotPolling();
		if (ws) {
			ws.close();
			ws = null;
		}
	}

	async function refreshTaskDiagnostics(taskId?: string) {
		const id = taskId || currentTaskId.value;
		if (!id) return null;

		try {
			const res = await getTaskDiagnostics(id);
			taskDiagnostics.value = res.data;
			return res.data;
		} catch (error) {
			console.warn("获取任务诊断信息失败", error);
			taskDiagnostics.value = null;
			return null;
		}
	}

	async function refreshTaskState(taskId: string) {
		setCurrentTask(taskId);
		ensureTaskBucket(taskId);
		try {
			const response = await getTaskState(taskId);
			applyRuntimeState(response.data);
			const state = response.data;
			if (
				state.status === "completed" ||
				state.status === "failed" ||
				state.status === "stopped" ||
				state.status === "interrupted"
			) {
				await refreshTaskDiagnostics(taskId);
			}
			return state;
		} catch (error) {
			console.error("刷新任务状态失败:", error);
			const status = deriveStatusFromMessages(taskId);
			const fallback: TaskRuntimeState = {
				task_id: taskId,
				status,
				message: latestStateMessage(taskId),
				current_step: currentProgress.value?.description ?? "",
				active: isActiveStatus(status),
			};
			applyRuntimeState(fallback);
			return fallback;
		}
	}

	async function syncTaskSnapshot(taskId: string) {
		if (snapshotSyncing) {
			return taskRuntimeState.value;
		}
		snapshotSyncing = true;
		try {
			// 并行拉取消息和状态，减少串行等待
			const [messagesResult, stateResult] = await Promise.allSettled([
				getTaskMessages(taskId),
				getTaskState(taskId),
			]);

			if (messagesResult.status === "fulfilled") {
				const validMessages = (messagesResult.value.data ?? []).filter(
					isMessagePayload,
				);
				mergeMessages(taskId, validMessages);
			} else {
				console.error("同步任务历史消息失败:", messagesResult.reason);
			}

			if (stateResult.status === "fulfilled") {
				applyRuntimeState(stateResult.value.data);
				return stateResult.value.data;
			}

			// 兜底：从消息推导状态
			const status = deriveStatusFromMessages(taskId);
			const fallback: TaskRuntimeState = {
				task_id: taskId,
				status,
				message: latestStateMessage(taskId),
				current_step: currentProgress.value?.description ?? "",
				active: isActiveStatus(status),
			};
			applyRuntimeState(fallback);
			return fallback;
		} finally {
			snapshotSyncing = false;
		}
	}

	function stopSnapshotPolling() {
		if (snapshotPollingTimer) {
			clearInterval(snapshotPollingTimer);
			snapshotPollingTimer = null;
		}
	}

	function startSnapshotPolling(taskId: string) {
		stopSnapshotPolling();
		snapshotPollingTimer = setInterval(() => {
			void syncTaskSnapshot(taskId).then((state) => {
				if (!state || !isActiveStatus(state.status)) {
					stopSnapshotPolling();
				}
			});
		}, 1000);
	}

	function getAgentStreamKey(msg: AgentMessage): string {
		const m = msg as any;
		return (
			m.agent_instance_id ??
			[
				m.agent_type,
				m.question_index ?? "",
				m.race_index ?? "",
				m.agent_index ?? "",
			].join(":")
		);
	}

	function appendMessage(taskId: string, message: Message) {
		ensureTaskBucket(taskId);

		if (message.msg_type === "agent" && "stream_state" in message) {
			const agentMsg = message as AgentMessage;
			if (agentMsg.stream_state === "streaming") {
				const bucket = messagesByTask.value[taskId];
				for (let i = bucket.length - 1; i >= 0; i--) {
					const existing = bucket[i];
					if (
						existing.msg_type === "agent" &&
						(existing as AgentMessage).stream_state === "streaming" &&
						getAgentStreamKey(existing as AgentMessage) ===
							getAgentStreamKey(agentMsg)
					) {
						bucket[i] = { ...existing, content: agentMsg.content };
						messagesByTask.value[taskId] = [...bucket];
						return;
					}
				}
				if (message.id) seenMessageIdsByTask.get(taskId)?.add(message.id);
				messagesByTask.value[taskId] = sortMessages([...bucket, message]);
				applyTerminalSystemMessage(taskId, message);
				return;
			}
		}

		const seenIds = seenMessageIdsByTask.get(taskId);
		if (message.id && seenIds?.has(message.id)) {
			messagesByTask.value[taskId] = sortMessages(
				messagesByTask.value[taskId].map((existing) =>
					existing.id === message.id ? message : existing,
				),
			);
			if (message.msg_type === "progress") updateProgressFromMessages(taskId);
			applyTerminalSystemMessage(taskId, message);
			return;
		}

		if (message.id) seenIds?.add(message.id);
		messagesByTask.value[taskId] = sortMessages([
			...messagesByTask.value[taskId],
			message,
		]);

		if (message.msg_type === "progress") updateProgressFromMessages(taskId);
		applyTerminalSystemMessage(taskId, message);
	}

	function mergeMessages(taskId: string, incomingMessages: Message[]) {
		ensureTaskBucket(taskId);
		const existingMessages = messagesByTask.value[taskId];
		const mergedById = new Map<string, Message>();

		for (const message of [...existingMessages, ...incomingMessages]) {
			if (!message.id) continue;
			mergedById.set(message.id, message);
		}

		const mergedMessages = Array.from(mergedById.values());
		messagesByTask.value[taskId] = sortMessages(mergedMessages);
		seenMessageIdsByTask.set(
			taskId,
			new Set(mergedMessages.map((message) => message.id)),
		);
		updateProgressFromMessages(taskId);
	}

	function connectWebSocket(taskId: string) {
		if (ws) {
			ws.close();
			ws = null;
		}
		setCurrentTask(taskId);
		ensureTaskBucket(taskId);

		const status =
			taskRuntimeState.value?.task_id === taskId
				? taskRuntimeState.value.status
				: deriveStatusFromMessages(taskId);
		isRunning.value = isActiveStatus(status);

		const baseUrl = import.meta.env.VITE_WS_URL;
		const wsUrl = `${baseUrl}/task/${taskId}`;

		ws = new TaskWebSocket(
			wsUrl,
			(data) => {
				if (!isMessagePayload(data)) {
					console.warn("忽略非标准任务消息:", data);
					return;
				}
				appendMessage(taskId, data);
			},
			(status) => {
				wsStatus.value = status;
				if (status === "connected") void syncTaskSnapshot(taskId);
				if (
					(status === "reconnecting" || status === "disconnected") &&
					isRunning.value
				) {
					startSnapshotPolling(taskId);
				}
			},
		);
		ws.connect();
		if (isRunning.value) {
			startSnapshotPolling(taskId);
		}
	}

	async function loadTaskMessages(taskId: string): Promise<boolean> {
		setCurrentTask(taskId);
		ensureTaskBucket(taskId);
		isRunning.value = false;
		wsStatus.value = "disconnected";
		try {
			const state = await syncTaskSnapshot(taskId);
			if (!state) return false;
			if (
				!state.active &&
				!isActiveStatus(state.status) &&
				hasTerminalMessage(taskId)
			) {
				isRunning.value = false;
			}
			const shouldReconnect = state.active || isActiveStatus(state.status);
			if (shouldReconnect) startSnapshotPolling(taskId);
			return shouldReconnect;
		} catch (error) {
			console.error("加载任务历史消息失败:", error);
			return false;
		}
	}

	function closeWebSocket() {
		ws?.close();
		ws = null;
		wsStatus.value = "disconnected";
		stopSnapshotPolling();
	}

	async function startTask(taskId: string) {
		try {
			const res = await startTaskAPI(taskId);
			if (res.data.success) {
				await refreshTaskState(taskId);
				connectWebSocket(taskId);
				isRunning.value = true;
			} else {
				await refreshTaskState(taskId);
			}
			return res.data;
		} catch (error) {
			console.error("启动任务失败:", error);
			return { success: false, status: "error", message: "启动请求失败" };
		}
	}

	async function stopTask(taskId: string) {
		try {
			const res = await cancelTaskAPI(taskId);
			if (res.data.success) {
				taskRuntimeState.value = {
					task_id: taskId,
					status: "stopping",
					message: res.data.message,
					current_step:
						taskRuntimeState.value?.current_step ??
						currentProgress.value?.description ??
						"",
					active: true,
				};
				isRunning.value = true;
				if (wsStatus.value === "disconnected") connectWebSocket(taskId);
			} else {
				await refreshTaskState(taskId);
			}
			return res.data;
		} catch (error) {
			console.error("取消任务失败:", error);
			await refreshTaskState(taskId);
			return { success: false, message: "取消请求失败" };
		}
	}

	const localActionId = (prefix: string) =>
		`${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

	function activeTaskId() {
		if (currentTaskId.value) return currentTaskId.value;
		if (typeof window !== "undefined") {
			return window.localStorage.getItem("currentTaskId") ?? "local";
		}
		return "local";
	}

	function addUserMessage(content: string) {
		const taskId = activeTaskId();
		appendMessage(taskId, {
			id: localActionId("user"),
			created_at: new Date().toISOString(),
			msg_type: "user",
			content,
		} as UserMessage);
	}

	function addUserAction(
		verb: string,
		object: string,
		detail = "",
		flow?: MessageFlow,
	) {
		const taskId = activeTaskId();
		const action: MessageAction = { verb, object, detail, flow };
		appendMessage(taskId, {
			id: localActionId("user-action"),
			created_at: new Date().toISOString(),
			msg_type: "user",
			content: detail || `${verb}：${object}`,
			action,
			local_action: true,
		} as UserMessage);
	}

	function addSystemAction(
		verb: string,
		object: string,
		detail = "",
		flow?: MessageFlow,
		type: SystemMessageType = "info",
	) {
		const taskId = activeTaskId();
		const action: MessageAction = { verb, object, detail, flow };
		appendMessage(taskId, {
			id: localActionId("system-action"),
			created_at: new Date().toISOString(),
			msg_type: "system",
			type,
			content: detail || `${verb}：${object}`,
			action,
			local_action: true,
		} as SystemMessage);
	}

	function addAgentAction(
		agentType: AgentType,
		verb: string,
		object: string,
		detail = "",
		flow?: MessageFlow,
	) {
		const taskId = activeTaskId();
		const action: MessageAction = { verb, object, detail, flow };
		appendMessage(taskId, {
			id: localActionId("agent-action"),
			created_at: new Date().toISOString(),
			msg_type: "agent",
			agent_type: agentType,
			content: detail || `${verb}：${object}`,
			action,
			local_action: true,
		} as AgentMessage);
	}

	function downloadMessages() {
		const dataStr = `data:text/json;charset=utf-8,${encodeURIComponent(JSON.stringify(messages.value, null, 2))}`;
		const downloadAnchorNode = document.createElement("a");
		downloadAnchorNode.setAttribute("href", dataStr);
		downloadAnchorNode.setAttribute(
			"download",
			`${currentTaskId.value ?? "task"}-messages.json`,
		);
		document.body.appendChild(downloadAnchorNode);
		downloadAnchorNode.click();
		downloadAnchorNode.remove();
	}

	const chatMessages = computed(() =>
		messages.value.filter((msg) => {
			if (
				msg.msg_type === "agent" &&
				msg.agent_type === AgentType.CODER &&
				msg.content != null &&
				msg.content !== ""
			) {
				return true;
			}
			if (msg.msg_type === "user") return true;
			if (msg.msg_type === "system") return true;
			return false;
		}),
	);

	const isLocalActionMessage = (msg: Message) => Boolean(msg.local_action);

	const coordinatorMessages = computed(() =>
		messages.value.filter(
			(msg): msg is CoordinatorMessage =>
				msg.msg_type === "agent" &&
				msg.agent_type === AgentType.COORDINATOR &&
				msg.content != null &&
				!isLocalActionMessage(msg),
		),
	);

	const modelerMessages = computed(() =>
		messages.value.filter(
			(msg): msg is ModelerMessage =>
				msg.msg_type === "agent" &&
				msg.agent_type === AgentType.MODELER &&
				msg.content != null &&
				!isLocalActionMessage(msg),
		),
	);

	const coderMessages = computed(() =>
		messages.value.filter(
			(msg): msg is CoderMessage =>
				msg.msg_type === "agent" &&
				msg.agent_type === AgentType.CODER &&
				msg.content != null &&
				!isLocalActionMessage(msg),
		),
	);

	const writerMessages = computed(() =>
		messages.value.filter(
			(msg): msg is WriterMessage =>
				msg.msg_type === "agent" &&
				msg.agent_type === AgentType.WRITER &&
				msg.content != null &&
				!isLocalActionMessage(msg),
		),
	);

	const interpreterMessage = computed(() =>
		messages.value.filter(
			(msg): msg is InterpreterMessage =>
				msg.msg_type === "tool" &&
				"tool_name" in msg &&
				msg.tool_name === "execute_code",
		),
	);

	const files = computed(() => {
		for (let i = coderMessages.value.length - 1; i >= 0; i--) {
			const msg = coderMessages.value[i];
			if (
				"files" in msg &&
				msg.files &&
				Array.isArray(msg.files) &&
				msg.files.length > 0
			) {
				return msg.files;
			}
		}
		return [];
	});

	return {
		currentTaskId,
		messages,
		wsStatus,
		isRunning,
		taskRuntimeState,
		taskDiagnostics,
		taskStatus,
		currentProgress,
		activeQuestionIndex,
		questionCards,
		originalProblemText,
		activeDiscussionIndex,
		discussionQuestions,
		chatMessages,
		coordinatorMessages,
		modelerMessages,
		coderMessages,
		writerMessages,
		interpreterMessage,
		files,
		refreshTaskState,
		refreshTaskDiagnostics,
		loadTaskMessages,
		setCurrentTask,
		startTask,
		connectWebSocket,
		closeWebSocket,
		stopTask,
		downloadMessages,
		addUserMessage,
		addUserAction,
		addSystemAction,
		addAgentAction,
	};
});
