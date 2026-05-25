"""Artifact edit routes with patch persistence.

These routes shadow legacy endpoints in files_router when registered before files_router.
The wrapper records successful local edits as patches and adds one guarded retry for
image-revision code failures caused by fabricated intermediate files.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from app.routers.files_router import (
    ImageRevisionChatRequest,
    TextRevisionChatRequest,
    revise_image_chat as legacy_revise_image_chat,
    revise_text_chat as legacy_revise_text_chat,
)
from app.utils.artifact_edits import artifact_edit_summary, record_image_patch, record_text_patch
from app.utils.common_utils import get_current_files, get_work_dir
from app.utils.log_util import logger

router = APIRouter()


@router.get("/artifact_edits")
async def get_artifact_edits(task_id: str):
    work_dir = get_work_dir(task_id)
    return artifact_edit_summary(work_dir)


def _should_retry_missing_file(response) -> bool:
    text = "\n".join(
        str(part or "")
        for part in [
            getattr(response, "message", ""),
            getattr(response, "render_message", ""),
            getattr(response, "analysis_text", ""),
        ]
    )
    return (
        not getattr(response, "render_success", False)
        and "FileNotFoundError" in text
        and any(ext in text for ext in [".pkl", ".pickle", ".joblib", ".npy", ".npz", ".feather", ".parquet"])
    )


def _file_list_for_retry(work_dir: str) -> str:
    try:
        files = get_current_files(work_dir, "all")
    except Exception:
        files = []
    keep = []
    for item in files:
        suffix = Path(item).suffix.lower()
        if suffix in {".xlsx", ".xls", ".csv", ".json", ".png", ".jpg", ".jpeg", ".py", ".ipynb", ".pkl", ".pickle", ".joblib", ".npy", ".npz"}:
            keep.append(item)
    return "\n".join(keep[:160]) or "(未读取到可用任务文件列表)"


def _enriched_image_retry_payload(payload: ImageRevisionChatRequest, response, work_dir: str) -> ImageRevisionChatRequest:
    files = _file_list_for_retry(work_dir)
    failure = "\n".join(
        str(part or "")
        for part in [getattr(response, "message", ""), getattr(response, "render_message", "")]
        if part
    )
    instruction = f"""{payload.instruction}

【上一轮图片重绘失败，需要重新生成可执行代码】
失败原因：
{failure}

【真实存在的任务文件列表】
{files}

【强制修复要求】
1. 你上一轮代码尝试读取了不存在的中间文件，导致 FileNotFoundError。
2. 本轮 revised_code 禁止再读取任何未出现在上方真实文件列表中的 .pkl、.pickle、.joblib、.npy、.npz、.feather、.parquet 文件。
3. 若原图依赖没有持久化的 Python 变量，优先从真实 Excel/CSV 重新构造绘图所需的最小数据。
4. 若无法从真实数据重算，就使用 PIL 或 matplotlib 读取当前目标图片，在现有图片上做用户要求的视觉层面修改，并覆盖保存到原图片文件名。
5. revised_code 必须完整可执行，必须覆盖保存原图片。"""
    history = list(payload.conversation_history or [])
    history.append({"role": "assistant", "content": f"上一轮失败：{failure}"})
    return ImageRevisionChatRequest(
        task_id=payload.task_id,
        filename=payload.filename,
        instruction=instruction,
        title=payload.title,
        description=payload.description,
        conversation_history=history,
    )


def _record_image_response(work_dir: str, payload: ImageRevisionChatRequest, response) -> None:
    try:
        if response.success or response.status == "partial_success":
            record_image_patch(
                work_dir,
                task_id=payload.task_id,
                filename=payload.filename,
                instruction=payload.instruction,
                updated_alt_text=response.updated_alt_text,
                updated_caption=response.updated_caption,
                revised_code=response.revised_code,
                render_success=response.render_success,
                message=response.message,
            )
    except Exception as exc:
        logger.warning(f"记录图片 AI 修改 patch 失败 {payload.task_id}/{payload.filename}: {exc}")


@router.post("/revise_image_chat")
async def revise_image_chat(payload: ImageRevisionChatRequest):
    response = await legacy_revise_image_chat(payload)
    work_dir = get_work_dir(payload.task_id)

    if _should_retry_missing_file(response):
        logger.warning(
            f"图片 AI 修改因虚构中间文件失败，执行一次带真实文件列表的重试: {payload.task_id}/{payload.filename}"
        )
        retry_payload = _enriched_image_retry_payload(payload, response, work_dir)
        retry_response = await legacy_revise_image_chat(retry_payload)
        if retry_response.success or retry_response.render_success or retry_response.status == "partial_success":
            response = retry_response
        else:
            response.message = (
                f"首次执行失败，已追加真实文件列表自动重试，但仍未成功。"
                f"首次错误：{response.message}；重试错误：{retry_response.message}"
            )
            response.render_message = retry_response.render_message or response.render_message
            response.analysis_text = retry_response.analysis_text or response.analysis_text

    _record_image_response(work_dir, payload, response)
    return response


@router.post("/revise_text_chat")
async def revise_text_chat(payload: TextRevisionChatRequest):
    response = await legacy_revise_text_chat(payload)
    work_dir = get_work_dir(payload.task_id)
    try:
        if response.revised_text and response.revision_scope == "selection":
            record_text_patch(
                work_dir,
                task_id=payload.task_id,
                selected_text=payload.selected_text,
                revised_text=response.revised_text,
                instruction=payload.instruction,
                scope=response.revision_scope,
                applied=response.applied or response.paper_updated,
                context=payload.context,
                message=response.message,
            )
    except Exception as exc:
        logger.warning(f"记录文本 AI 修改 patch 失败 {payload.task_id}: {exc}")
    return response
