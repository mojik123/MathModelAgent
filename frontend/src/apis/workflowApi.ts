import request from "@/utils/request";
import type { WorkflowStage } from "@/workflow/types";

export const NO_REASONING_OPTION = "none" as const;

export interface WorkflowStateResponse {
  stages: WorkflowStage[];
  checklist: string | null;
}

export interface WorkflowArtifact {
  filename: string;
  path: string;
  kind: "image" | "code" | "notebook" | "markdown" | "pdf" | "data" | "file";
  stage_id: string;
  preview_url: string;
  source_path?: string;
}

export interface ModelRegistryEntry {
  id: string;
  label: string;
  provider: string;
  reasoning_options: string[];
}

export interface TaskModelConfig {
  task_id: string;
  task_key: string;
  model: string;
  reasoning: string;
}

export function getWorkflowState(taskId: string) {
  return request.get<WorkflowStateResponse>("/workflow_state", {
    params: { task_id: taskId },
  });
}

export function getArtifacts(taskId: string, stageId: string) {
  return request.get<WorkflowArtifact[]>("/artifacts", {
    params: { task_id: taskId, stage_id: stageId },
  });
}

export function getModelRegistry() {
  return request.get<ModelRegistryEntry[]>("/model_registry");
}

export function getTaskModelConfig(taskId: string, taskKey: string) {
  return request.get<TaskModelConfig>("/task_model_config", {
    params: { task_id: taskId, task_key: taskKey },
  });
}

export function saveTaskModelConfig(config: TaskModelConfig) {
  return request.put<TaskModelConfig>("/task_model_config", config);
}

export interface WorkflowRunResponse {
  run_id: string;
  task_id: string;
  stage_id: string;
  status: "running" | "stopping" | "completed" | "failed" | "cancelled";
  model: string;
  reasoning: string;
  output: string;
  error?: string | null;
  thread_id?: string | null;
  usage?: Record<string, unknown> | null;
  log_path: string;
}

export function runWorkflowStage(taskId: string, stageId: string) {
  return request.post<WorkflowRunResponse>("/workflow_run", {
    task_id: taskId,
    stage_id: stageId,
  });
}

export function startWorkflowStage(taskId: string, stageId: string) {
  return request.post<WorkflowRunResponse>("/workflow_start", {
    task_id: taskId,
    stage_id: stageId,
  });
}

export function getWorkflowRun(runId: string) {
  return request.get<WorkflowRunResponse>(`/workflow_run/${encodeURIComponent(runId)}`);
}

export function stopWorkflowRun(runId: string) {
  return request.post<WorkflowRunResponse>("/workflow_stop", { run_id: runId });
}
