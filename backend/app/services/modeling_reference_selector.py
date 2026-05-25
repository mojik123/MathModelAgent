"""Selectable wrapper for modeling reference search tools.

The base service provides normalization, scoring and caching helpers. This module
adds user-controlled source selection so a modeling run can use OpenAlex,
Crossref, Tavily, any subset of them, or skip reference retrieval entirely.
"""

from __future__ import annotations

from typing import Any

from app.services.modeling_reference_service import (
    _deduplicate,
    _hash_payload,
    _persist_reference_pack,
    _read_cache,
    _score,
    _search_crossref,
    _search_openalex,
    _search_tavily,
    _write_cache,
    build_academic_queries,
)
from app.utils.log_util import logger

VALID_REFERENCE_TOOLS = {"openalex", "crossref", "tavily"}
DEFAULT_REFERENCE_TOOLS = ["openalex", "crossref"]


def normalize_reference_tools(tools: list[str] | None, enabled: bool = True) -> list[str]:
    """Normalize user-selected reference tools.

    Tavily remains optional because it needs SEARCH_ENABLED=true and a key. Keeping
    it out of the default avoids surprising slow web calls on local runs.
    """
    if not enabled:
        return []
    selected = tools if tools is not None else DEFAULT_REFERENCE_TOOLS
    normalized: list[str] = []
    for tool in selected:
        key = str(tool or "").strip().lower()
        if key in VALID_REFERENCE_TOOLS and key not in normalized:
            normalized.append(key)
    return normalized


def search_modeling_references_with_tools(
    problem_title: str,
    question_text: str,
    user_message: str = "",
    *,
    limit: int = 8,
    work_dir: str | None = None,
    question_index: int | None = None,
    reference_tools: list[str] | None = None,
    reference_search_enabled: bool = True,
) -> list[dict[str, Any]]:
    enabled_tools = normalize_reference_tools(reference_tools, reference_search_enabled)
    queries = build_academic_queries(problem_title, question_text, user_message)

    if not enabled_tools:
        _persist_reference_pack(work_dir, question_index, queries, [])
        return []

    cache_key = _hash_payload(
        {
            "title": problem_title,
            "question": question_text,
            "user": user_message,
            "queries": queries,
            "limit": limit,
            "reference_tools": enabled_tools,
        }
    )
    cached = _read_cache(work_dir, cache_key)
    if cached is not None:
        _persist_reference_pack(work_dir, question_index, queries, cached)
        return cached[:limit]

    searchers = {
        "openalex": ("OpenAlex", _search_openalex),
        "tavily": ("Tavily", _search_tavily),
        "crossref": ("Crossref", _search_crossref),
    }
    raw_results: list[dict[str, Any]] = []
    per_query_limit = max(4, min(8, limit))
    for query in queries:
        for tool in enabled_tools:
            name, searcher = searchers[tool]
            try:
                raw_results.extend(searcher(query, per_query_limit))
            except Exception as exc:
                logger.warning(f"建模文献检索失败 {name}: {exc}")

    unique = _deduplicate(raw_results)
    for item in unique:
        item["relevance_score"] = _score(item, queries, question_text)
    unique.sort(
        key=lambda item: (
            float(item.get("relevance_score") or 0),
            int(item.get("year") or 0),
        ),
        reverse=True,
    )

    refs: list[dict[str, Any]] = []
    q_prefix = f"Q{question_index}-" if question_index is not None else ""
    for idx, item in enumerate(unique[:limit], start=1):
        refs.append(
            {
                "source_id": f"{q_prefix}S{idx}",
                "title": item.get("title") or "",
                "year": item.get("year"),
                "authors": item.get("authors") or [],
                "source": item.get("source") or "",
                "doi": item.get("doi") or "",
                "url": item.get("url") or "",
                "abstract": item.get("abstract") or "",
                "snippet": item.get("snippet") or "",
                "method_tags": item.get("method_tags") or [],
                "relevance_score": item.get("relevance_score") or 0,
            }
        )

    _write_cache(work_dir, cache_key, refs)
    _persist_reference_pack(work_dir, question_index, queries, refs)
    return refs
