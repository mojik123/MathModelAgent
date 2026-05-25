"""OpenAlex connectivity test endpoint."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from app.services.modeling_reference_selector import search_modeling_references_with_tools

router = APIRouter()


@router.get("/modeling/reference/openalex-test")
async def openalex_test(
    query: str = Query("mathematical modeling optimization", min_length=1),
    limit: int = Query(5, ge=1, le=10),
):
    """Test whether OpenAlex search is reachable and returns usable records."""
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
