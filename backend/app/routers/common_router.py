"""通用路由模块，提供配置查询、消息获取和健康检查等接口。"""

import json
import shutil
import datetime
import asyncio
from copy import deepcopy
from pathlib import Path

from aiofile import async_open
from fastapi import APIRouter, HTTPException
from app.config.setting import settings
from app.utils.common_utils import ensure_safe_task_id, get_config_template
from app.schemas.enums import CompTemplate
from app.services.redis_manager import redis_manager
from app.services.task_state import get_task_state
from app.utils.log_util import logger

router = APIRouter()
MESSAGES_DIR = Path("logs/messages")
WORK_DIR_ROOT = Path("project/work_dir")
ACTIVE_TASK_TTL_SECONDS = 3600 * 6


def _require_safe_task_id(task_id: str) -> str:
    """验证并返回安全的任务 ID。

    Args:
        task_id: 待验证的任务 ID。

    Returns:
        验证通过的任务 ID。

    Raises:
        HTTPException: 任务 ID 非法时返回 400。
    """
    try:
        return ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc


def _salvage_json_array(raw: str) -> list:
    """从损坏的 JSON 文件中尽力恢复消息数组。"""
    import re
    items = []
    # 尝试匹配每个顶层 JSON 对象
    depth = 0
    start = -1
    for i, ch in enumerate(raw):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    obj = json.loads(raw[start:i+1])
                    items.append(obj)
                except json.JSONDecodeError:
                    pass
                start = -1
    return items

async def _load_task_messages_from_file(task_id: str) -> list[dict]:
    """从文件加载指定任务的历史消息。

    Args:
        task_id: 任务 ID。

    Returns:
        消息列表，文件不存在时返回空列表。
    """
    safe_task_id = _require_safe_task_id(task_id)
    message_file = MESSAGES_DIR / f"{safe_task_id}.json"
    if not message_file.exists():
        return []

    try:
        async with async_open(message_file, "r", encoding="utf-8") as f:
            content = await f.read()
        # 尝试多种解析方式应对文件损坏
        data = None
        for parser in [
            lambda c: json.loads(c),
            lambda c: json.loads(c + "]"),  # 缺少结尾
            lambda c: _salvage_json_array(c),  # 逐行恢复
        ]:
            try:
                data = parser(content)
                if isinstance(data, list):
                    break
            except Exception:
                continue
        messages = data if isinstance(data, list) else []
        if messages:
            # 修复后写回
            async with async_open(message_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(messages, ensure_ascii=False, indent=2))
        return _hydrate_checkpoint_agent_messages(safe_task_id, messages)
    except Exception as e:
        logger.error(f"读取任务消息文件失败: {str(e)}")
        return []


def _message_created_at_from_path(path: Path) -> str:
    try:
        return datetime.datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    except Exception:
        return datetime.datetime.now().isoformat()


def _has_agent_message(messages: list[dict], agent_type: str) -> bool:
    return any(
        message.get("msg_type") == "agent"
        and message.get("agent_type") == agent_type
        and str(message.get("content") or "").strip()
        for message in messages
    )


def _has_modeling_confirmation_message(messages: list[dict]) -> bool:
    return any(
        message.get("msg_type") == "system"
        and (
            "建模方案已确认" in str(message.get("content") or "")
            or "已复用建模方案选择" in str(message.get("content") or "")
        )
        for message in messages
    )


def _make_checkpoint_agent_message(
    task_id: str,
    agent_type: str,
    content: object,
    *,
    created_at: str,
    suffix: str,
    sub_title: str | None = None,
    as_json: bool = True,
) -> dict:
    payload = {
        "id": f"{task_id}-checkpoint-{suffix}",
        "created_at": created_at,
        "msg_type": "agent",
        "content": json.dumps(content, ensure_ascii=False) if as_json else str(content),
        "agent_type": agent_type,
        "stream_state": "complete",
    }
    if sub_title:
        payload["sub_title"] = sub_title
    return payload


def _hydrate_checkpoint_agent_messages(task_id: str, messages: list[dict]) -> list[dict]:
    """用 workflow_checkpoint 补齐刷新后右侧 Agent 面板需要的最终内容。"""
    checkpoint_path = WORK_DIR_ROOT / task_id / "workflow_checkpoint.json"
    if not checkpoint_path.exists():
        return messages

    try:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if not isinstance(checkpoint, dict):
            return messages
    except Exception as e:
        logger.warning(f"读取任务断点失败 {task_id}: {e}")
        return messages

    hydrated = deepcopy(messages)
    created_at = _message_created_at_from_path(checkpoint_path)

    if checkpoint.get("modeling_selections") and not _has_modeling_confirmation_message(hydrated):
        hydrated.append(
            {
                "id": f"{task_id}-checkpoint-modeling-selections",
                "created_at": created_at,
                "msg_type": "system",
                "content": "从断点恢复：已复用建模方案选择",
                "type": "info",
            }
        )

    coordinator = checkpoint.get("coordinator")
    if isinstance(coordinator, dict) and not _has_agent_message(hydrated, "CoordinatorAgent"):
        questions = dict(coordinator.get("questions") or {})
        if "ques_count" not in questions:
            questions["ques_count"] = coordinator.get("ques_count", 0)
        hydrated.append(
            _make_checkpoint_agent_message(
                task_id,
                "CoordinatorAgent",
                questions,
                created_at=created_at,
                suffix="coordinator",
            )
        )

    modeler = checkpoint.get("modeler")
    if isinstance(modeler, dict) and not _has_agent_message(hydrated, "ModelerAgent"):
        questions_solution = modeler.get("questions_solution")
        if isinstance(questions_solution, dict):
            hydrated.append(
                _make_checkpoint_agent_message(
                    task_id,
                    "ModelerAgent",
                    questions_solution,
                    created_at=created_at,
                    suffix="modeler",
                )
            )

    user_output_res = checkpoint.get("user_output_res")
    if isinstance(user_output_res, dict):
        existing_writer_subtitles = {
            message.get("sub_title")
            for message in hydrated
            if message.get("msg_type") == "agent"
            and message.get("agent_type") == "WriterAgent"
            and str(message.get("content") or "").strip()
        }
        for key, value in user_output_res.items():
            if key in existing_writer_subtitles or not isinstance(value, dict):
                continue
            content = value.get("response_content")
            if not str(content or "").strip():
                continue
            hydrated.append(
                _make_checkpoint_agent_message(
                    task_id,
                    "WriterAgent",
                    content,
                    created_at=created_at,
                    suffix=f"writer-{key}",
                    sub_title=str(key),
                    as_json=False,
                )
            )

    return sorted(
        hydrated,
        key=lambda message: str(message.get("created_at") or ""),
    )


@router.get("/")
async def root():
    return {"message": "Hello World"}


@router.get("/config")
async def config():
    return {
        "environment": settings.ENV,
        "deepseek_model": settings.DEEPSEEK_MODEL,
        "deepseek_base_url": settings.DEEPSEEK_BASE_URL,
        "max_retries": settings.MAX_RETRIES,
        "CORS_ALLOW_ORIGINS": settings.CORS_ALLOW_ORIGINS,
    }


@router.get("/writer_seque")
async def get_writer_seque():
    # 返回论文顺序
    config_template: dict = get_config_template(CompTemplate.CHINA)
    return list(config_template.keys())


@router.get("/messages")
async def get_task_messages(task_id: str):
    return await _load_task_messages_from_file(task_id)


def _parse_task_title(messages: list[dict], task_id: str) -> str:
    for message in messages:
        if message.get("msg_type") == "agent" and message.get("agent_type") == "CoordinatorAgent":
            content = message.get("content") or ""
            try:
                clean_content = content.replace("```json", "").replace("```", "").strip()
                data = json.loads(clean_content)
                title = str(data.get("title") or "").strip()
                if title:
                    return title
            except Exception:
                pass
        if message.get("msg_type") == "user" and message.get("content"):
            content = str(message["content"]).strip().replace("\n", " ")
            if content:
                return content[:40]
    return f"历史任务 {task_id}"


def _parse_task_status(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("msg_type") != "system":
            continue
        message_type = message.get("type")
        content = str(message.get("content") or "")
        if "等待手动启动" in content:
            return "ready"
        if message_type == "success" and "任务处理完成" in content:
            return "completed"
        if message_type == "error":
            return "failed"
        if message_type == "warning" and "任务已停止" in content:
            return "stopped"
        if "任务处理完成" in content:
            return "completed"
        if "任务执行失败" in content:
            return "failed"
        if "任务已停止" in content:
            return "stopped"
    return "interrupted"


def _parse_task_created_at(task_id: str, fallback_timestamp: float) -> str:
    try:
        # task_id format: YYYYMMDD-HHMMSS-xxxxxxxx
        raw = task_id[:15]
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}T{raw[9:11]}:{raw[11:13]}:{raw[13:15]}"
    except Exception:
        return datetime.datetime.fromtimestamp(fallback_timestamp).isoformat()


def _is_recent_task_update(updated_timestamp: float) -> bool:
    if updated_timestamp <= 0:
        return False
    age_seconds = datetime.datetime.now().timestamp() - updated_timestamp
    return age_seconds < ACTIVE_TASK_TTL_SECONDS


@router.get("/tasks")
async def list_tasks():
    """列出本机已经生成过的建模任务。"""
    tasks: list[dict] = []
    MESSAGES_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR_ROOT.mkdir(parents=True, exist_ok=True)
    client = None
    try:
        client = await redis_manager.get_client()
    except Exception:
        client = None

    task_ids = {path.stem for path in MESSAGES_DIR.glob("*.json")}
    task_ids.update(path.name for path in WORK_DIR_ROOT.iterdir() if path.is_dir())

    for task_id in sorted(task_ids, reverse=True):
        try:
            safe_task_id = _require_safe_task_id(task_id)
        except HTTPException:
            continue

        message_file = MESSAGES_DIR / f"{safe_task_id}.json"
        work_dir = WORK_DIR_ROOT / safe_task_id
        messages: list[dict] = []
        if message_file.exists():
            try:
                messages = json.loads(message_file.read_text(encoding="utf-8"))
                if not isinstance(messages, list):
                    messages = []
            except Exception as e:
                logger.warning(f"读取历史任务 {safe_task_id} 失败: {e}")

        updated_timestamp = max(
            message_file.stat().st_mtime if message_file.exists() else 0,
            work_dir.stat().st_mtime if work_dir.exists() else 0,
        )
        status = _parse_task_status(messages)
        state = None
        try:
            state = await get_task_state(safe_task_id)
        except Exception:
            state = None
        if state and state.get("status"):
            status = str(state["status"])
        if client is not None:
            try:
                if await client.exists(f"task_id:{safe_task_id}"):
                    if status == "interrupted" and _is_recent_task_update(updated_timestamp):
                        status = "running"
                    elif status not in {"running", "stopping"}:
                        await client.delete(f"task_id:{safe_task_id}")
            except Exception:
                pass

        tasks.append(
            {
                "task_id": safe_task_id,
                "title": _parse_task_title(messages, safe_task_id),
                "status": status,
                "message_count": len(messages),
                "created_at": _parse_task_created_at(safe_task_id, updated_timestamp),
                "updated_at": datetime.datetime.fromtimestamp(updated_timestamp).isoformat()
                if updated_timestamp
                else None,
                "has_paper": (work_dir / "res.md").exists(),
                "has_pdf": (work_dir / "res.pdf").exists(),
            }
        )

    return tasks


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """删除历史任务的消息记录和工作目录。"""
    safe_task_id = _require_safe_task_id(task_id)
    message_file = MESSAGES_DIR / f"{safe_task_id}.json"
    work_dir = WORK_DIR_ROOT / safe_task_id

    if message_file.exists():
        message_file.unlink()
    if work_dir.exists():
        shutil.rmtree(work_dir)

    try:
        client = await redis_manager.get_client()
        await client.delete(f"task_id:{safe_task_id}")
        await client.delete(f"task_state:{safe_task_id}")
    except Exception:
        pass

    return {"success": True}


@router.get("/track")
async def track(task_id: str):
    # 获取任务的token使用情况

    pass


@router.get("/healthz")
async def healthz():
    """Lightweight liveness probe that does not touch Redis or task files."""
    return {
        "status": "ok",
        "message": "FastAPI event loop is responsive",
        "checked_at": datetime.datetime.now().isoformat(),
    }


@router.get("/status")
async def get_service_status():
    """获取后端和 Redis 的运行状态。"""
    status = {
        "backend": {"status": "running", "message": "Backend service is running"},
        "redis": {"status": "unknown", "message": "Redis connection status unknown"},
        "active_tasks": {
            "status": "unknown",
            "message": "Active task status unknown",
            "count": 0,
            "ids": [],
        },
    }

    # 检查Redis连接状态
    try:
        redis_client = await asyncio.wait_for(redis_manager.get_client(), timeout=1.5)
        await asyncio.wait_for(redis_client.ping(), timeout=1.5)  # type: ignore[reportGeneralTypeIssues]
        status["redis"] = {"status": "running", "message": "Redis connection is healthy"}

        active_task_ids: list[str] = []
        async for key in redis_client.scan_iter(match="task_id:*", count=100):
            key_text = key.decode("utf-8", errors="ignore") if isinstance(key, bytes) else str(key)
            active_task_id = key_text.split(":", 1)[1] if ":" in key_text else key_text
            if active_task_id:
                active_task_ids.append(active_task_id)

        active_task_ids = sorted(set(active_task_ids))
        if active_task_ids:
            status["backend"] = {
                "status": "busy",
                "message": f"{len(active_task_ids)} modeling task(s) are running",
            }
            status["active_tasks"] = {
                "status": "busy",
                "message": "Modeling task is running",
                "count": len(active_task_ids),
                "ids": active_task_ids,
            }
        else:
            status["active_tasks"] = {
                "status": "idle",
                "message": "No active modeling task",
                "count": 0,
                "ids": [],
            }
    except Exception as e:
        logger.error(f"Redis connection failed: {str(e)}")
        status["redis"] = {"status": "error", "message": f"Redis connection failed: {str(e)}"}

    return status
