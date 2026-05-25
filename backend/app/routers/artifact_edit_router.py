"""Artifact edit routes with patch persistence.

These routes intentionally shadow the legacy endpoints in files_router when registered
before files_router. The legacy implementation still performs the actual AI revision;
this wrapper records successful local edits as patches, so later paper rebuild/final
merge can re-apply them even if the main workflow continues writing sections.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers.files_router import (
    ImageRevisionChatRequest,
    TextRevisionChatRequest,
    revise_image_chat as legacy_revise_image_chat,
    revise_text_chat as legacy_revise_text_chat,
)
from app.utils.artifact_edits import artifact_edit_summary, record_image_patch, record_text_patch
from app.utils.common_utils import get_work_dir
from app.utils.log_util import logger

router = APIRouter()


@router.get("/artifact_edits")
async def get_artifact_edits(task_id: str):
    work_dir = get_work_dir(task_id)
    return artifact_edit_summary(work_dir)


@router.post("/revise_image_chat")
async def revise_image_chat(payload: ImageRevisionChatRequest):
    response = await legacy_revise_image_chat(payload)
    work_dir = get_work_dir(payload.task_id)
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
