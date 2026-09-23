import { STAGE_STATUSES, type StageStatus } from "./types";

const validStatuses: ReadonlySet<string> = new Set(STAGE_STATUSES);

export function deriveStageStatus(
  raw: unknown,
  index: number,
  previous: StageStatus | undefined,
): StageStatus {
  if (index > 0 && previous !== "PASS") {
    return "LOCKED";
  }

  if (typeof raw === "string") {
    const normalized = raw.trim().toUpperCase();
    if (validStatuses.has(normalized)) {
      return normalized as StageStatus;
    }
  }

  return index === 0 || previous === "PASS" ? "READY" : "LOCKED";
}
