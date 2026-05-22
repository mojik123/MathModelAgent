"""Task runtime state helpers used by start/stop/reconnect flows."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from app.services.redis_manager import redis_manager

TaskStatus = Literal[
    "ready",
    "running",
    "stopping",
    "stopped",
    "completed",
    "failed",
    "interrupted",
]

TERMINAL_STATUSES = {"stopped", "completed", "failed", "interrupted"}
TASK_STATE_TTL_SECONDS = 3600 * 24


def _task_state_key(task_id: str) -> str:
    return f"task_state:{task_id}"


async def set_task_state(
    task_id: str,
    status: TaskStatus,
    *,
    message: str = "",
    current_step: str = "",
    progress: int | None = None,
) -> dict[str, Any]:
    client = await redis_manager.get_client()
    now = datetime.now(timezone.utc).isoformat()
    previous: dict[str, Any] = {}
    raw = await client.get(_task_state_key(task_id))
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                previous = parsed
        except Exception:
            previous = {}

    started_at = previous.get("started_at")
    if status == "running" and not started_at:
        started_at = now

    payload: dict[str, Any] = {
        "task_id": task_id,
        "status": status,
        "message": message,
        "current_step": current_step or str(previous.get("current_step") or ""),
        "updated_at": now,
    }
    if started_at:
        payload["started_at"] = started_at
    if status in TERMINAL_STATUSES:
        payload["finished_at"] = now
    elif previous.get("finished_at"):
        payload["finished_at"] = previous["finished_at"]

    next_progress = progress if progress is not None else previous.get("progress")
    if next_progress is not None:
        payload["progress"] = next_progress

    await client.set(_task_state_key(task_id), json.dumps(payload, ensure_ascii=False))
    await client.expire(_task_state_key(task_id), TASK_STATE_TTL_SECONDS)
    return payload


async def get_task_state(task_id: str) -> dict[str, Any] | None:
    client = await redis_manager.get_client()
    raw = await client.get(_task_state_key(task_id))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


async def mark_task_ready(task_id: str, message: str = "任务已创建，等待手动启动") -> dict[str, Any]:
    return await set_task_state(task_id, "ready", message=message)


async def mark_task_running(
    task_id: str,
    message: str,
    current_step: str = "",
    progress: int | None = None,
) -> dict[str, Any]:
    return await set_task_state(
        task_id,
        "running",
        message=message,
        current_step=current_step,
        progress=progress,
    )


async def mark_task_stopping(task_id: str, message: str = "正在停止当前任务") -> dict[str, Any]:
    return await set_task_state(task_id, "stopping", message=message)


async def mark_task_terminal(
    task_id: str,
    status: Literal["stopped", "completed", "failed", "interrupted"],
    message: str,
) -> dict[str, Any]:
    return await set_task_state(task_id, status, message=message)
