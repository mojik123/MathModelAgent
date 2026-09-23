import { describe, expect, it } from "vitest";
import { deriveStageStatus } from "./stageState";
import { WORKFLOW_STAGES } from "./stages";

describe("deriveStageStatus", () => {
  it("normalizes known statuses regardless of case and surrounding whitespace", () => {
    expect(deriveStageStatus(" pass ", 1, "PASS")).toBe("PASS");
    expect(deriveStageStatus("running", 0, undefined)).toBe("RUNNING");
  });

  it("falls back deterministically when the stored status is unknown", () => {
    expect(deriveStageStatus("IN_PROGRESS", 0, undefined)).toBe("READY");
    expect(deriveStageStatus("unknown", 1, "PASS")).toBe("READY");
    expect(deriveStageStatus("unknown", 1, "READY")).toBe("LOCKED");
  });

  it("keeps later stages locked until the previous stage passes", () => {
    expect(deriveStageStatus("RUNNING", 1, "READY")).toBe("LOCKED");
    expect(deriveStageStatus("PASS", 2, "FAIL")).toBe("LOCKED");
    expect(deriveStageStatus("blocked", 1, "PASS")).toBe("BLOCKED");
  });
});

describe("WORKFLOW_STAGES", () => {
  it("exposes the nine stable stage IDs in order with Chinese labels", () => {
    expect(WORKFLOW_STAGES.map((stage) => stage.id)).toEqual([
      "00-intake",
      "01-analysis",
      "02-modeling",
      "03-code",
      "04-validation",
      "05-figures",
      "06-paper",
      "07-compile",
      "08-final-audit",
    ]);
    expect(WORKFLOW_STAGES.every((stage) => /[\u4e00-\u9fff]/.test(stage.title))).toBe(true);
  });
});
