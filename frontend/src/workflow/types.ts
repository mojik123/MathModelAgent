export const STAGE_STATUSES = [
  "LOCKED",
  "READY",
  "RUNNING",
  "PASS",
  "FAIL",
  "BLOCKED",
] as const;

export type StageStatus = (typeof STAGE_STATUSES)[number];

export interface WorkflowStage {
  id: string;
  index: number;
  title: string;
  shortTitle: string;
  status: StageStatus;
  summary: string;
  inputs: string[];
  outputs: string[];
  acceptance: string[];
}
