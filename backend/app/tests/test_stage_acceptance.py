from __future__ import annotations

import json

from app.services.stage_acceptance import BLOCKED, FAIL, PASS, validate_stage


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_stage_state(workspace, status="PASS", outputs=None):
    _write_json(
        workspace / "STAGE_STATE.json",
        {
            "current_stage": "00-intake",
            "status": status,
            "stages": [
                {
                    "stage": "00-intake",
                    "status": status,
                    "outputs": outputs or [
                        "RUN_CONTEXT.json",
                        "INPUT_INVENTORY.json",
                        "CAPABILITY_REPORT.json",
                        "TASK_CHECKLIST.md",
                    ],
                }
            ],
        },
    )


def test_intake_pass_requires_real_outputs_and_evidence(tmp_path):
    for name in (
        "RUN_CONTEXT.json",
        "INPUT_INVENTORY.json",
        "CAPABILITY_REPORT.json",
    ):
        _write_json(tmp_path / name, {"ok": True})
    (tmp_path / "TASK_CHECKLIST.md").write_text("# checklist\n", encoding="utf-8")
    _write_stage_state(tmp_path)

    result = validate_stage(tmp_path, "00-intake")

    assert result["verdict"] == PASS
    assert result["missing"] == []
    assert result["evidence"]


def test_model_pass_with_missing_artifact_is_not_accepted(tmp_path):
    (tmp_path / "STAGE_STATE.json").write_text(
        json.dumps(
            {
                "stages": [
                    {
                        "stage": "01-analysis",
                        "status": "PASS",
                        "outputs": ["PROBLEM_ANALYSIS.md"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "PROBLEM_ANALYSIS.md").write_text("analysis", encoding="utf-8")

    result = validate_stage(tmp_path, "01-analysis")

    assert result["verdict"] == FAIL
    assert any("PROBLEM_FACTS" in item for item in result["invalid"] + result["missing"])


def test_missing_state_is_blocked(tmp_path):
    result = validate_stage(tmp_path, "00-intake")

    assert result["verdict"] == BLOCKED
    assert result["missing"] == ["STAGE_STATE.json"]
