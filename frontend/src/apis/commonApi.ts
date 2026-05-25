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

export interface ModelingReferencePreference {
	reference_search_enabled?: boolean;
	reference_tools?: string[];
}

/** 健康检查 */
export function getHelloWorld() {
	return request.get<{ message: string }>("/");
}

export interface ArtifactCheckRecord {
	attempt_name?: string;
	passed: boolean;
	issues: string[];
	images: string[];
	code_files: string[];
}

export interface TaskDiagnostics {
	task_id: string;
	status?: TaskRuntimeStatus;
	completed?: boolean;
	files?: {
		res_md?: boolean;
		res_json?: boolean;
		docx?: boolean;
		images?: number;
		code_files?: number;
		notebooks?: number;
	};
	artifact_checks?: Record<string, Record<string, ArtifactCheckRecord>>;
	final_audit?: unknown;
	final_image_ref_issues?: string[];
	final_paper_issues?: string[];
	final_file_issues?: string[];
}

export function getWriterSeque() {
	return request.get<{ writer_seque: string[] }>("/writer_seque");
}

export function getTaskMessages(task_id: string) {
	return request.get<Message[]>("/messages", { params: { task_id } });
}

export function getTaskHistory() {
	return request.get<TaskHistoryItem[]>("/tasks");
}

export function deleteTaskHistory(task_id: string) {
	return request.delete<{ success: boolean }>(`/tasks/${task_id}`);
}

export function startTask(task_id: string) {
	return request.post<{ success: boolean; status: string; message: string }>(`/modeling/${task_id}/start`);
}

export function getTaskState(task_id: string) {
	return request.get<TaskRuntimeState>(`/modeling/${task_id}/state`);
}

export function getTaskDiagnostics(task_id: string) {
	return request.get<TaskDiagnostics>(`/modeling/${task_id}/diagnostics`);
}

export function openFolderAPI(task_id: string) {
	return request.get<{ message: string }>("/open_folder", { params: { task_id } });
}

export function exampleAPI(example_id: string, source: string) {
	return request.post<{ task_id: string; status: string }>("/example", { example_id, source });
}

export function getServiceStatus() {
	return request.get<{
		backend: { status: string; message: string };
		redis: { status: string; message: string };
		active_tasks?: { status: string; message: string; count: number; ids: string[] };
	}>("/status");
}

export function cancelTask(task_id: string) {
	return request.post<{ success: boolean; message: string }>(`/modeling/${task_id}/cancel`);
}

export function confirmModeling(
	task_id: string,
	selections: Array<{
		index: number;
		model: string;
		chatHistory: Array<{ role: string; content: string }>;
	}>,
) {
	return request.post<{ success: boolean; message: string }>(`/modeling/${task_id}/confirm-modeling`, { selections });
}

export function modelingDiscussionChat(
	task_id: string,
	payload: {
		question_index: number;
		message: string;
		questions: Array<Record<string, unknown>>;
	} & ModelingReferencePreference,
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
	} & ModelingReferencePreference,
) {
	return request.post<{
		success: boolean;
		message: string;
		questions: Array<{
			questionIndex: number;
			researchSummary: string;
			recommendedOptionId: string;
			options: Array<Record<string, unknown>>;
			references?: Array<Record<string, unknown>>;
			referenceCount?: number;
			referenceSearchEnabled?: boolean;
			referenceTools?: string[];
		}>;
	}>(`/modeling/${task_id}/model-options`, payload, { timeout: 600000 });
}

export function getOriginalProblem(task_id: string) {
	return request.get<{ task_id: string; ques_all: string; files?: string[] }>(`/modeling/${task_id}/problem`);
}

export function confirmQuestions(
	task_id: string,
	questions: Array<{
		questionIndex: number;
		questionTitle: string;
		questionText: string;
		chatHistory?: Array<{ role: string; content: string }>;
	}>,
) {
	return request.post<{ success: boolean; message: string }>(`/modeling/${task_id}/confirm-questions`, { questions });
}

export function questionDiscussionChat(
	task_id: string,
	payload: {
		message: string;
		questions: Array<Record<string, unknown>>;
		original_problem?: string;
	},
) {
	return request.post<{ success: boolean; message: string; content: string }>(`/modeling/${task_id}/question-discussion-chat`, payload, { timeout: 600000 });
}

export function regenerateQuestions(
	task_id: string,
	payload: {
		message?: string;
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
	}>(`/modeling/${task_id}/regenerate-questions`, payload, { timeout: 600000 });
}
