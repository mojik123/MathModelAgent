"""Small file-backed store for Codex workflow run metadata."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_PERSISTED_KEYS = (
    "run_id",
    "task_id",
    "stage_id",
    "status",
    "model",
    "reasoning",
    "output",
    "error",
    "thread_id",
    "usage",
    "log_path",
    "created_at",
    "updated_at",
    "stop_requested",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_run_id(run_id: str) -> str:
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("非法 run_id")
    return run_id


def run_record_path(task_dir: Path, run_id: str) -> Path:
    return task_dir / "logs" / "codex" / "runs" / f"{_safe_run_id(run_id)}.json"


def _record_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    record = {
        key: entry.get(key)
        for key in _PERSISTED_KEYS
        if entry.get(key) is not None
    }
    record.setdefault("created_at", _now())
    record["updated_at"] = _now()
    return record


def persist_run(entry: dict[str, Any]) -> dict[str, Any]:
    """Atomically persist serializable fields from a live run entry."""

    task_dir = Path(entry["task_dir"])
    record = _record_from_entry(entry)
    path = run_record_path(task_dir, str(record["run_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    entry.update(record)
    return record


def _load_record(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("run_id"), str):
        return None
    try:
        _safe_run_id(value["run_id"])
    except ValueError:
        return None
    return value


def restore_run(task_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    """Attach non-persisted paths to a record loaded after a restart."""

    log_path = record.get("log_path")
    if not isinstance(log_path, str) or log_path.startswith("/") or ".." in Path(log_path).parts:
        log_path = f"logs/codex/{record['run_id']}.json"
    return {
        **record,
        "task_dir": task_dir,
        "log_file": task_dir / log_path,
        "prompt": "",
        "runner": None,
    }


def load_task_runs(task_dir: Path) -> list[dict[str, Any]]:
    """Load one task's records and mark non-terminal runs interrupted."""

    run_dir = task_dir / "logs" / "codex" / "runs"
    if not run_dir.is_dir():
        return []
    loaded: list[dict[str, Any]] = []
    for path in sorted(run_dir.glob("*.json")):
        record = _load_record(path)
        if record is None:
            continue
        if record.get("status") in {"running", "stopping"}:
            record["status"] = "interrupted"
            record["error"] = record.get("error") or "后端重启时未能恢复运行进程"
            record["updated_at"] = _now()
            temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(path)
        loaded.append(restore_run(task_dir, record))
    return loaded


def load_all_runs(work_root: Path) -> Iterable[dict[str, Any]]:
    if not work_root.is_dir():
        return []
    runs: list[dict[str, Any]] = []
    for task_dir in work_root.iterdir():
        if task_dir.is_dir() and not task_dir.is_symlink():
            runs.extend(load_task_runs(task_dir))
    return runs
