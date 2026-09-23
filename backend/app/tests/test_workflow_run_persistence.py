from __future__ import annotations

import json

from app.services.workflow_run_store import load_task_runs, persist_run, run_record_path


def test_running_run_is_recovered_as_interrupted(tmp_path):
    task_dir = tmp_path / "task"
    entry = {
        "run_id": "20260924T000000Z-deadbeef",
        "task_id": "task",
        "stage_id": "00-intake",
        "status": "running",
        "model": "gpt-6-sol",
        "reasoning": "medium",
        "task_dir": task_dir,
        "log_file": task_dir / "logs" / "codex" / "run.json",
        "log_path": "logs/codex/run.json",
    }

    persist_run(entry)
    loaded = load_task_runs(task_dir)

    assert len(loaded) == 1
    assert loaded[0]["status"] == "interrupted"
    assert "重启" in loaded[0]["error"]
    saved = json.loads(
        run_record_path(task_dir, entry["run_id"]).read_text(encoding="utf-8")
    )
    assert saved["status"] == "interrupted"


def test_terminal_run_round_trips_without_runner_object(tmp_path):
    task_dir = tmp_path / "task"
    entry = {
        "run_id": "20260924T000001Z-cafebabe",
        "task_id": "task",
        "stage_id": "01-analysis",
        "status": "completed",
        "model": "gpt-6-sol",
        "reasoning": "high",
        "output": "done",
        "task_dir": task_dir,
        "log_file": task_dir / "logs" / "codex" / "run.json",
        "log_path": "logs/codex/run.json",
    }

    persist_run(entry)
    loaded = load_task_runs(task_dir)

    assert loaded[0]["status"] == "completed"
    assert loaded[0]["output"] == "done"
    assert loaded[0]["runner"] is None
