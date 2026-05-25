"""Enhanced modeling discussion endpoints with traceable literature references.

This router intentionally shadows the legacy model-options and discussion-chat
endpoints. Register it before modeling_router in app.main.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.config.setting import settings
from app.core.llm.llm import LLM, simple_chat
from app.routers import modeling_router as legacy
from app.schemas.response import SystemMessage
from app.services.modeling_reference_selector import (
    DEFAULT_REFERENCE_TOOLS,
    normalize_reference_tools,
    search_modeling_references_with_tools,
)
from app.services.modeling_reference_service import format_references_for_prompt
from app.services.redis_manager import redis_manager
from app.utils.common_utils import ensure_safe_task_id, get_work_dir
from app.utils.log_util import logger

router = APIRouter()


class ModelingOptionsRequest(BaseModel):
    title: str = ""
    background: str = ""
    questions: list[dict]
    force_refresh: bool = False
    reference_search_enabled: bool = True
    reference_tools: list[str] | None = None


class ModelingOptionsResponse(BaseModel):
    success: bool
    message: str
    questions: list[dict]


class ModelingDiscussionChatRequest(BaseModel):
    question_index: int
    message: str
    questions: list[dict]
    reference_search_enabled: bool = True
    reference_tools: list[str] | None = None


class ModelingDiscussionChatResponse(BaseModel):
    success: bool
    message: str = ""
    content: str = ""


def _question_index(q: dict[str, Any], fallback: int) -> int:
    try:
        return int(q.get("index") or q.get("questionIndex") or fallback)
    except Exception:
        return fallback


def _question_text(q: dict[str, Any]) -> str:
    return str(q.get("text") or q.get("questionText") or "").strip()


def _valid_source_ids(refs: list[dict[str, Any]]) -> set[str]:
    return {str(ref.get("source_id")) for ref in refs if ref.get("source_id")}


def _source_details(refs: list[dict[str, Any]], ids: list[str]) -> list[dict[str, Any]]:
    lookup = {str(ref.get("source_id")): ref for ref in refs}
    return [lookup[i] for i in ids if i in lookup]


def _sanitize_candidate_sources(candidate: dict[str, Any], references: list[dict[str, Any]]) -> dict[str, Any]:
    valid_ids = _valid_source_ids(references)
    for option in candidate.get("options") or []:
        raw = option.get("sources") if isinstance(option, dict) else []
        ids = [str(item) for item in raw if str(item) in valid_ids] if isinstance(raw, list) else []
        option["sources"] = ids
        option["sourceDetails"] = _source_details(references, ids)
    candidate["references"] = references
    candidate["referenceCount"] = len(references)
    return candidate


def _reference_status(enabled_tools: list[str]) -> str:
    if not enabled_tools:
        return "未使用参考文献检索工具"
    return "使用参考文献检索工具：" + "、".join(enabled_tools)


async def _search_refs_async(
    *,
    title: str,
    question_text: str,
    work_dir: str,
    question_index: int,
    user_message: str = "",
    limit: int = 8,
    reference_search_enabled: bool = True,
    reference_tools: list[str] | None = None,
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(
        search_modeling_references_with_tools,
        title,
        question_text,
        user_message,
        limit=limit,
        work_dir=work_dir,
        question_index=question_index,
        reference_search_enabled=reference_search_enabled,
        reference_tools=reference_tools,
    )


@router.get("/modeling/reference/openalex-test")
async def openalex_test(
    query: str = Query("mathematical modeling optimization", min_length=1),
    limit: int = Query(5, ge=1, le=10),
):
    """Test whether OpenAlex search is reachable and returns usable records.

    This endpoint is placed on modeling_reference_router because this router is
    already registered by existing deployments. It avoids the extra-router
    registration problem that caused 404 on some local images.
    """
    refs = await asyncio.to_thread(
        search_modeling_references_with_tools,
        query,
        query,
        "",
        limit=limit,
        work_dir=None,
        question_index=1,
        reference_search_enabled=True,
        reference_tools=["openalex"],
    )
    return {
        "success": bool(refs),
        "source": "OpenAlex",
        "query": query,
        "count": len(refs),
        "results": refs,
        "message": "OpenAlex 可用，已返回论文结果" if refs else "OpenAlex 请求成功但没有返回结果，请换一个 query 测试",
    }


@router.get("/modeling/reference-test/openalex")
async def openalex_test_alias(
    query: str = Query("mathematical modeling optimization", min_length=1),
    limit: int = Query(5, ge=1, le=10),
):
    """Alias endpoint for easier manual testing."""
    return await openalex_test(query=query, limit=limit)


@router.post("/modeling/{task_id}/model-options", response_model=ModelingOptionsResponse)
async def generate_model_options(task_id: str, body: ModelingOptionsRequest):
    """Generate model candidates with user-selected reference retrieval tools."""
    try:
        safe_task_id = ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc

    enabled_tools = normalize_reference_tools(
        body.reference_tools if body.reference_tools is not None else DEFAULT_REFERENCE_TOOLS,
        body.reference_search_enabled,
    )
    questions = [
        {
            "questionIndex": _question_index(q, idx + 1),
            "questionText": _question_text(q),
            "systemHints": legacy._infer_problem_traits(_question_text(q)),
            "candidateHints": legacy._seed_model_guidance(_question_text(q)),
        }
        for idx, q in enumerate(body.questions)
        if isinstance(q, dict) and _question_text(q)
    ]
    if not questions:
        raise HTTPException(status_code=400, detail="缺少问题列表，无法生成模型候选")

    cache_key = legacy._model_options_cache_key(
        body.title,
        body.background,
        questions + [{"questionIndex": 0, "questionText": f"reference:{','.join(enabled_tools) or 'off'}"}],
    )
    if not body.force_refresh:
        cached_questions = legacy._load_model_options_cache(safe_task_id, cache_key)
        if cached_questions:
            return ModelingOptionsResponse(
                success=True,
                message="已复用本题已有模型候选结果",
                questions=cached_questions,
            )

    total_q = len(questions)
    work_dir = get_work_dir(safe_task_id)
    await redis_manager.publish_message(
        safe_task_id,
        SystemMessage(content=f"ModelerAgent 正在为 {total_q} 个问题并行生成候选模型方案；{_reference_status(enabled_tools)}。"),
    )

    progress: dict[int, str] = {}
    progress_lock = asyncio.Lock()

    async def _publish_progress() -> None:
        searching = sorted([k for k, v in progress.items() if v == "searching"])
        generating = sorted([k for k, v in progress.items() if v == "generating"])
        done = sorted([k for k, v in progress.items() if v == "done"])
        failed = sorted([k for k, v in progress.items() if v == "failed"])
        parts: list[str] = []
        if searching:
            parts.append(f"第 {'、'.join(str(i) for i in searching)} 问正在检索文献依据")
        if generating:
            parts.append(f"第 {'、'.join(str(i) for i in generating)} 问正在生成模型方案")
        if done:
            parts.append(f"第 {'、'.join(str(i) for i in done)} 问候选方案生成完成")
        if failed:
            parts.append(f"第 {'、'.join(str(i) for i in failed)} 问生成失败")
        await redis_manager.publish_message(
            safe_task_id,
            SystemMessage(content="；".join(parts) if parts else "正在准备...", type="error" if failed else "info"),
        )

    async def _generate_for_question(q: dict[str, Any]) -> dict[str, Any]:
        q_idx = int(q["questionIndex"])
        q_text = str(q["questionText"])
        llm = LLM(
            api_type=settings.MODELER_API_TYPE,
            api_key=settings.MODELER_API_KEY,
            model=settings.MODELER_MODEL,
            base_url=settings.MODELER_BASE_URL,
            task_id=safe_task_id,
            max_tokens=settings.MODELER_MAX_TOKENS,
        )

        references: list[dict[str, Any]] = []
        if enabled_tools:
            async with progress_lock:
                progress[q_idx] = "searching"
                await _publish_progress()
            references = await _search_refs_async(
                title=body.title,
                question_text=q_text,
                work_dir=work_dir,
                question_index=q_idx,
                limit=10,
                reference_search_enabled=True,
                reference_tools=enabled_tools,
            )

        async with progress_lock:
            progress[q_idx] = "generating"
            await _publish_progress()

        question_map = {q_idx: q}
        quality_issues: list[str] = []
        refs_prompt = format_references_for_prompt(references, max_items=6)
        reference_rule = (
            "3. sources 只能填写下方【已验证文献 sources】中的 source_id，不允许编造 DOI、作者、年份或 source_id。\n"
            "4. 每个候选尽量关联 1-2 条 sources；如果检索依据不足，sources 可为空，但 reason 中要说明“该方案主要基于题面数据结构与建模经验”。\n"
            if enabled_tools
            else "3. 本次用户选择不使用参考文献检索工具，sources 必须输出空数组；reason 只基于题面目标、数据结构和建模经验说明。\n"
        )

        for attempt in range(3):
            if attempt > 0:
                await redis_manager.publish_message(
                    safe_task_id,
                    SystemMessage(content=f"第 {q_idx} 问自动质检未通过（第{attempt}次），正在重试...", type="warning"),
                )
            feedback_text = "\n".join(f"- {item}" for item in quality_issues)
            prompt = f"""
请只针对下面这一问生成经过筛选的候选模型方案。

【输出硬性要求】
1. 生成 3-4 个候选模型，有且仅有一个 isRecommended=true。
2. 每个候选包含 id、label、description、pros、cons、reason、score、sources。
{reference_rule}5. researchSummary 要概括本次依据来源；没有检索时说明“未启用文献检索，依据来自题面与建模经验”。
6. 禁止改写题目场景、禁止泛化理由、候选必须互有区分度。
7. 输出纯 JSON，不要 Markdown。

【上一轮质检反馈】
{feedback_text or "无"}

【JSON 结构】
{{"questions":[{{"questionIndex":{q_idx},"researchSummary":"...","recommendedOptionId":"...","options":[{{"id":"...","label":"...","description":"...","pros":"...","cons":"...","reason":"...","score":92,"isRecommended":true,"sources":[]}}]}}]}}

【题目标题】
{body.title}

【题目背景】
{body.background[:5000]}

【当前问题】
{json.dumps(q, ensure_ascii=False, indent=2)}

【参考文献检索状态】
{_reference_status(enabled_tools)}

【已验证文献 sources】
{refs_prompt}
"""
            try:
                raw = await simple_chat(
                    llm,
                    [
                        {
                            "role": "system",
                            "content": "你是数学建模竞赛的模型选优专家。必须围绕题面和数据结构给出模型候选；启用文献检索时只能引用已验证来源，未启用时禁止编造来源。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                )
                parsed = legacy._extract_json_object(raw)
                candidate_list = legacy._normalize_model_options_payload(parsed)
                if not candidate_list:
                    continue
                candidate = candidate_list[0]
                candidate["questionIndex"] = q_idx
                candidate["referenceSearchEnabled"] = bool(enabled_tools)
                candidate["referenceTools"] = enabled_tools
                candidate = _sanitize_candidate_sources(candidate, references)
                quality_issues = legacy._validate_model_options_for_questions([candidate], question_map)
                if not quality_issues:
                    async with progress_lock:
                        progress[q_idx] = "done"
                        await _publish_progress()
                    return candidate
            except Exception as exc:
                logger.warning(f"第{q_idx}问候选生成异常: {exc}")
                quality_issues = [f"候选生成异常：{exc}"]

        last_issues_text = "；".join(quality_issues) if quality_issues else "未生成有效候选模型"
        async with progress_lock:
            progress[q_idx] = "failed"
            await _publish_progress()
        raise RuntimeError(f"第 {q_idx} 问模型候选生成失败：{last_issues_text}")

    tasks = [asyncio.create_task(_generate_for_question(q)) for q in questions]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    normalized: list[dict[str, Any]] = []
    failed_questions: list[int] = []
    for i, result in enumerate(raw_results):
        q_idx = int(questions[i].get("questionIndex", i + 1))
        if isinstance(result, Exception):
            logger.error(f"第{q_idx}问模型候选生成失败: {result}")
            failed_questions.append(q_idx)
            continue
        normalized.append(result)

    if failed_questions:
        failed_text = "、".join(str(i) for i in sorted(set(failed_questions)))
        await redis_manager.publish_message(
            safe_task_id,
            SystemMessage(content=f"模型候选方案生成未完成：第 {failed_text} 问失败。", type="error"),
        )
        raise HTTPException(status_code=500, detail=f"模型候选方案生成未完成：第 {failed_text} 问失败")

    legacy._save_model_options_cache(safe_task_id, cache_key, normalized)
    await redis_manager.publish_message(
        safe_task_id,
        SystemMessage(content=f"模型候选方案生成完成，共 {len(questions)} 问，请在各卡片中选择建模方案", type="success"),
    )
    return ModelingOptionsResponse(success=True, message="已按用户选择的文献检索工具生成模型候选", questions=normalized)


@router.post("/modeling/{task_id}/discussion-chat", response_model=ModelingDiscussionChatResponse)
async def modeling_discussion_chat(task_id: str, body: ModelingDiscussionChatRequest):
    """Card-level model discussion with optional reference retrieval."""
    try:
        safe_task_id = ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc

    enabled_tools = normalize_reference_tools(
        body.reference_tools if body.reference_tools is not None else DEFAULT_REFERENCE_TOOLS,
        body.reference_search_enabled,
    )
    selected_question = next(
        (q for q in body.questions if int(q.get("questionIndex", -1)) == body.question_index),
        None,
    )
    title = str(selected_question.get("questionTitle") or "") if selected_question else ""
    q_text = str(selected_question.get("questionText") or "") if selected_question else ""
    references: list[dict[str, Any]] = []
    if enabled_tools:
        references = await _search_refs_async(
            title=title,
            question_text=q_text,
            user_message=body.message,
            work_dir=get_work_dir(safe_task_id),
            question_index=body.question_index,
            limit=8,
            reference_search_enabled=True,
            reference_tools=enabled_tools,
        )

    shared_context = json.dumps(body.questions, ensure_ascii=False, indent=2)
    user_prompt = f"""
你是建模方案讨论助手。用户会逐问选择模型，所有问题卡片共用同一个上下文。
请结合全部卡片的已选模型、自定义方案、对话历史和参考文献检索状态，回答当前问题卡片的追问。
不要直接启动正式建模，只给出可供用户选择/修正的建议；如果更合适的模型不在候选卡片中，请明确建议用户通过“自定义方案”填写。

【当前讨论的问题】第 {body.question_index} 问
{json.dumps(selected_question, ensure_ascii=False, indent=2) if selected_question else '(未找到当前问题卡片)'}

【全部问题卡片共享上下文】
{shared_context}

【参考文献检索状态】
{_reference_status(enabled_tools)}

【本问已验证文献摘要】
{format_references_for_prompt(references, max_items=6)}

【用户本轮消息】
{body.message}
"""
    llm = LLM(
        api_type=settings.MODELER_API_TYPE,
        api_key=settings.MODELER_API_KEY,
        model=settings.MODELER_MODEL,
        base_url=settings.MODELER_BASE_URL,
        task_id=safe_task_id,
    )
    try:
        content = await simple_chat(
            llm,
            [
                {
                    "role": "system",
                    "content": "你是数学建模竞赛中的建模方案讨论助手。回答要简洁、具体、可执行；启用检索时只引用已验证来源，未启用时禁止编造来源。",
                },
                {"role": "user", "content": user_prompt},
            ],
        )
    except Exception as exc:
        logger.error(f"建模讨论失败 {safe_task_id}: {exc}")
        raise HTTPException(status_code=500, detail=f"建模讨论失败: {exc}") from exc

    return ModelingDiscussionChatResponse(success=True, message="已生成建模讨论回复", content=content.strip())
