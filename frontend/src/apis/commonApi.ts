import request from "@/utils/request";
import type { Message } from "@/utils/response";

export interface TaskHistoryItem {
	task_id: string;
	title: string;
	status: TaskRuntimeStatus;
	message_count: number;
	created_at: string;
	updated_at?: string | null;
	has_paper: boolean;
	has_pdf: boolean;
}

export type TaskRuntimeStatus =
	| "ready"
	| "running"
	| "stopping"
	| "completed"
	| "failed"
	| "stopped"
	| "interrupted";

export interface TaskRuntimeState {
	task_id: string;
	status: TaskRuntimeStatus;
	message: string;
	current_step?: string;
	progress?: number | null;
	started_at?: string;
	finished_at?: string;
	updated_at?: string;
	active: boolean;
}

/** 健康检查 */
export function getHelloWorld() {
	return request.get<{ message: string }>("/");
}

/** 获取论文写作顺序 */
export function getWriterSeque() {
	return request.get<{ writer_seque: string[] }>("/writer_seque");
}

/**
 * 获取任务的历史消息
 * @param task_id 任务ID
 */
export function getTaskMessages(task_id: string) {
	return request.get<Message[]>("/messages", {
		params: {
			task_id,
		},
	});
}

/** 获取历史建模任务列表 */
export function getTaskHistory() {
	return request.get<TaskHistoryItem[]>("/tasks");
}

/** 删除历史建模任务 */
export function deleteTaskHistory(task_id: string) {
	return request.delete<{ success: boolean }>(`/tasks/${task_id}`);
}

/** 手动启动或重新启动建模任务 */
export function startTask(task_id: string) {
	return request.post<{ success: boolean; status: string; message: string }>(
		`/modeling/${task_id}/start`,
	);
}

/** 获取单个任务的后端运行状态 */
export function getTaskState(task_id: string) {
	return request.get<TaskRuntimeState>(`/modeling/${task_id}/state`);
}

/**
 * 打开工作目录
 * @param task_id 任务ID
 */
export function openFolderAPI(task_id: string) {
	return request.get<{ message: string }>("/open_folder", {
		params: {
			task_id,
		},
	});
}

/**
 * 提交样例任务
 * @param example_id 样例ID
 * @param source 来源
 */
export function exampleAPI(example_id: string, source: string) {
	return request.post<{
		task_id: string;
		status: string;
	}>("/example", {
		example_id,
		source,
	});
}

/** 获取后端和 Redis 服务状态 */
export function getServiceStatus() {
	return request.get<{
		backend: { status: string; message: string };
		redis: { status: string; message: string };
		active_tasks?: {
			status: string;
			message: string;
			count: number;
			ids: string[];
		};
	}>("/status");
}

/**
 * 取消正在运行的任务
 * @param task_id 任务ID
 */
export function cancelTask(task_id: string) {
	return request.post<{ success: boolean; message: string }>(
		`/modeling/${task_id}/cancel`,
	);
}

export function confirmModeling(
	task_id: string,
	selections: Array<{
		index: number;
		model: string;
		chatHistory: Array<{ role: string; content: string }>;
	}>,
) {
	return request.post<{ success: boolean; message: string }>(
		`/modeling/${task_id}/confirm-modeling`,
		{ selections },
	);
}

export function modelingDiscussionChat(
	task_id: string,
	payload: {
		question_index: number;
		message: string;
		questions: Array<Record<string, unknown>>;
	},
) {
	return request.post<{ success: boolean; message: string; content: string }>(
		`/modeling/${task_id}/discussion-chat`,
		payload,
		{ timeout: 600000 },
	);
}

export function generateModelingOptions(
	task_id: string,
	payload: {
		title: string;
		background: string;
		questions: Array<{ index: number; text: string }>;
		force_refresh?: boolean;
	},
) {
	return request.post<{
		success: boolean;
		message: string;
		questions: Array<{
			questionIndex: number;
			researchSummary: string;
			recommendedOptionId: string;
			options: Array<Record<string, unknown>>;
		}>;
	}>(`/modeling/${task_id}/model-options`, payload, { timeout: 600000 });
}


// ── 问题划分讨论接口 ─────────────────────────────────────────────

/** 获取原始题目内容 */
export function getOriginalProblem(task_id: string) {
	return request.get<{
		task_id: string;
		ques_all: string;
		files?: string[];
	}>(`/modeling/${task_id}/problem`);
}

/** 确认问题划分 */
export function confirmQuestions(
	task_id: string,
	questions: Array<{
		questionIndex: number;
		questionTitle: string;
		questionText: string;
		chatHistory?: Array<{ role: string; content: string }>;
	}>,
) {
	return request.post<{ success: boolean; message: string }>(
		`/modeling/${task_id}/confirm-questions`,
		{ questions },
	);
}

/** 问题划分讨论对话 */
export function questionDiscussionChat(
	task_id: string,
	payload: {
		message: string;
		questions: Array<Record<string, unknown>>;
		original_problem?: string;
	},
) {
	return request.post<{
		success: boolean;
		message: string;
		content: string;
	}>(`/modeling/${task_id}/question-discussion-chat`, payload, {
		timeout: 600000,
	});
}

/** 让 Agent 重新生成问题划分 */
export function regenerateQuestions(
	task_id: string,
	payload: {
		message: string;
		questions: Array<Record<string, unknown>>;
		original_problem?: string;
	},
) {
	return request.post<{
		success: boolean;
		message: string;
		questions: Array<{
			questionIndex: number;
			questionTitle: string;
			questionText: string;
		}>;
	}>(`/modeling/${task_id}/regenerate-questions`, payload, {
		timeout: 600000,
	});
}
