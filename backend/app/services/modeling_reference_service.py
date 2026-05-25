"""Structured academic reference search for modeling-plan generation.

This service upgrades modeling references from a light prompt add-on into a
traceable research pack:
- OpenAlex is the primary academic source.
- Tavily is optional web/search augmentation when SEARCH_ENABLED=true.
- Crossref is used as DOI/publication metadata fallback.
- Results are normalized, deduplicated, scored, cached, and persisted per task.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import requests

from app.config.setting import settings
from app.utils.log_util import logger

_CACHE_DIR = ".cache/modeling_references"
_REFERENCE_INDEX_FILE = "modeling_references.json"
_WRITE_LOCK = threading.Lock()

_METHOD_TAG_RULES: list[tuple[tuple[str, ...], str]] = [
    (("linear programming", "integer programming", "mixed integer", "optimization", "programming"), "optimization"),
    (("multi objective", "pareto", "nsga", "evolutionary"), "multi_objective_optimization"),
    (("time series", "forecast", "arima", "prophet", "temporal"), "time_series_forecasting"),
    (("regression", "random forest", "xgboost", "lightgbm", "gradient boosting"), "machine_learning_prediction"),
    (("classification", "logistic", "auc", "binary", "classifier"), "classification"),
    (("recommendation", "recommender", "collaborative filtering", "ranking", "learning to rank"), "recommendation"),
    (("topsis", "ahp", "entropy weight", "multi criteria", "mcda", "decision making"), "multi_criteria_evaluation"),
    (("clustering", "k-means", "gaussian mixture", "segmentation"), "clustering"),
    (("sensitivity analysis", "robustness", "uncertainty"), "sensitivity_analysis"),
]

_QUERY_TEMPLATES: list[tuple[tuple[str, ...], list[str]]] = [
    (
        ("优化", "最优", "约束", "资源", "调度", "路径", "分配"),
        [
            "mathematical modeling optimization linear programming integer programming application",
            "multi objective optimization modeling constraints decision variables",
        ],
    ),
    (
        ("预测", "forecast", "prediction", "时间序列", "时序", "趋势", "次日", "新增"),
        [
            "forecasting model time series regression machine learning feature engineering",
            "mathematical modeling prediction gradient boosting temporal features",
        ],
    ),
    (
        ("是否", "分类", "概率", "二分类", "识别", "判别"),
        [
            "binary classification probability prediction logistic regression gradient boosting",
            "classification model selection imbalanced data mathematical modeling",
        ],
    ),
    (
        ("推荐", "排序", "top", "匹配", "偏好"),
        [
            "recommender systems collaborative filtering learning to rank user behavior",
            "recommendation model ranking matrix factorization factorization machines",
        ],
    ),
    (
        ("评价", "指标", "综合评价", "评分", "优劣"),
        [
            "multi criteria decision making TOPSIS AHP entropy weight evaluation model",
            "comprehensive evaluation mathematical modeling indicator weighting",
        ],
    ),
    (
        ("聚类", "分群", "画像", "类别"),
        [
            "clustering user profiling k-means gaussian mixture mathematical modeling",
            "segmentation model cluster analysis data mining",
        ],
    ),
    (
        ("灵敏度", "敏感性", "稳健", "扰动"),
        [
            "sensitivity analysis parameter perturbation robustness mathematical modeling",
            "uncertainty analysis model validation sensitivity indices",
        ],
    ),
]


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _norm_space(text: str | None) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", title.lower())[:160]


def _hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _abstract_from_openalex_inverted_index(index: dict[str, list[int]] | None) -> str:
    if not isinstance(index, dict) or not index:
        return ""
    positions: list[tuple[int, str]] = []
    for token, idxs in index.items():
        if not isinstance(idxs, list):
            continue
        for i in idxs:
            try:
                positions.append((int(i), token))
            except Exception:
                continue
    positions.sort(key=lambda item: item[0])
    return _norm_space(" ".join(token for _, token in positions))


def _method_tags(text: str) -> list[str]:
    lower = text.lower()
    tags: list[str] = []
    for keywords, tag in _METHOD_TAG_RULES:
        if any(k in lower for k in keywords) and tag not in tags:
            tags.append(tag)
    return tags


def build_academic_queries(problem_title: str, question_text: str, user_message: str = "") -> list[str]:
    """Build focused academic queries by task type.

    The query is intentionally English-heavy because OpenAlex/Crossref metadata is
    mainly English, while Chinese domain words are retained for local relevance.
    """
    text = f"{problem_title} {question_text} {user_message}".lower()
    domain = _norm_space(f"{problem_title} {question_text[:160]}")
    queries: list[str] = []
    for keywords, templates in _QUERY_TEMPLATES:
        if any(k.lower() in text for k in keywords):
            queries.extend(f"{template} {domain}" for template in templates)
    if not queries:
        queries.append(f"mathematical modeling model selection data science methods {domain}")
    # Keep max 4 targeted queries to control latency.
    return list(dict.fromkeys(q[:420] for q in queries if q.strip()))[:4]


def _cache_path(work_dir: str | None, cache_key: str) -> Path | None:
    if not work_dir:
        return None
    path = Path(work_dir) / _CACHE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{cache_key}.json"


def _read_cache(work_dir: str | None, cache_key: str) -> list[dict[str, Any]] | None:
    path = _cache_path(work_dir, cache_key)
    if not path or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        created_at = float(payload.get("created_at") or 0)
        ttl = int(payload.get("ttl") or settings.SEARCH_CACHE_TTL or 86400)
        if time.time() - created_at > ttl:
            return None
        results = payload.get("results")
        return results if isinstance(results, list) else None
    except Exception as exc:
        logger.warning(f"读取建模文献缓存失败 {path}: {exc}")
        return None


def _write_cache(work_dir: str | None, cache_key: str, results: list[dict[str, Any]]) -> None:
    path = _cache_path(work_dir, cache_key)
    if not path:
        return
    try:
        payload = {"created_at": time.time(), "ttl": settings.SEARCH_CACHE_TTL, "results": results}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as exc:
        logger.warning(f"写入建模文献缓存失败 {path}: {exc}")


def _search_openalex(query: str, limit: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "search": query,
        "per-page": min(max(limit, 1), 20),
        "sort": "relevance_score:desc",
    }
    if settings.OPENALEX_EMAIL:
        params["mailto"] = settings.OPENALEX_EMAIL
    if settings.OPENALEX_API_KEY:
        params["api_key"] = settings.OPENALEX_API_KEY
    response = requests.get("https://api.openalex.org/works", params=params, timeout=12)
    response.raise_for_status()
    works = response.json().get("results", [])
    results: list[dict[str, Any]] = []
    for item in works[:limit]:
        title = _norm_space(item.get("display_name"))
        if not title:
            continue
        doi = _norm_space(item.get("doi")).replace("https://doi.org/", "")
        abstract = _abstract_from_openalex_inverted_index(item.get("abstract_inverted_index"))
        authorships = item.get("authorships") or []
        authors = []
        for author in authorships[:4]:
            display = ((author or {}).get("author") or {}).get("display_name")
            if display:
                authors.append(str(display))
        concepts = [str(c.get("display_name")) for c in (item.get("concepts") or [])[:5] if c.get("display_name")]
        url = item.get("doi") or item.get("id") or ""
        text = " ".join([title, abstract, " ".join(concepts)])
        results.append(
            {
                "title": title,
                "year": item.get("publication_year"),
                "authors": authors,
                "source": "OpenAlex",
                "doi": doi,
                "url": url,
                "abstract": abstract[:900],
                "snippet": abstract[:500] or "; ".join(concepts),
                "method_tags": _method_tags(text),
                "raw_source": "openalex",
            }
        )
    return results


def _search_crossref(query: str, limit: int) -> list[dict[str, Any]]:
    response = requests.get(
        "https://api.crossref.org/works",
        params={"query": query, "rows": min(max(limit, 1), 20), "sort": "relevance"},
        timeout=12,
    )
    response.raise_for_status()
    items = response.json().get("message", {}).get("items", [])
    results: list[dict[str, Any]] = []
    for item in items[:limit]:
        title_value = item.get("title")
        title = " ".join(title_value or []) if isinstance(title_value, list) else _norm_space(title_value)
        if not title:
            continue
        container_value = item.get("container-title")
        container = " ".join(container_value or []) if isinstance(container_value, list) else _norm_space(container_value)
        year_parts = item.get("issued", {}).get("date-parts") or []
        year = year_parts[0][0] if year_parts and year_parts[0] else None
        abstract = _strip_html(item.get("abstract"))
        authors = []
        for author in (item.get("author") or [])[:4]:
            name = " ".join(part for part in [author.get("given"), author.get("family")] if part)
            if name:
                authors.append(name)
        text = " ".join([title, abstract, container])
        results.append(
            {
                "title": title,
                "year": year,
                "authors": authors,
                "source": "Crossref",
                "doi": _norm_space(item.get("DOI")),
                "url": _norm_space(item.get("URL")),
                "abstract": abstract[:900],
                "snippet": abstract[:500] or "；".join(part for part in [container, str(year or "")] if part),
                "method_tags": _method_tags(text),
                "raw_source": "crossref",
            }
        )
    return results


def _search_tavily(query: str, limit: int) -> list[dict[str, Any]]:
    if not settings.SEARCH_ENABLED or not settings.TAVILY_API_KEY:
        return []
    response = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": settings.TAVILY_API_KEY,
            "query": query,
            "max_results": min(max(limit, 1), 10),
            "search_depth": "basic",
            "include_answer": False,
        },
        timeout=12,
    )
    response.raise_for_status()
    items = response.json().get("results", [])
    results: list[dict[str, Any]] = []
    for item in items[:limit]:
        title = _norm_space(item.get("title"))
        snippet = _strip_html(item.get("content"))
        if not title and not snippet:
            continue
        text = " ".join([title, snippet])
        results.append(
            {
                "title": title or snippet[:80],
                "year": None,
                "authors": [],
                "source": "Tavily",
                "doi": "",
                "url": _norm_space(item.get("url")),
                "abstract": snippet[:900],
                "snippet": snippet[:500],
                "method_tags": _method_tags(text),
                "raw_source": "tavily",
            }
        )
    return results


def _deduplicate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in results:
        doi = _norm_space(item.get("doi")).lower()
        key = f"doi:{doi}" if doi else f"title:{_title_key(str(item.get('title') or ''))}"
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _score(item: dict[str, Any], queries: list[str], question_text: str) -> float:
    haystack = " ".join(
        str(item.get(k) or "") for k in ("title", "abstract", "snippet")
    ).lower()
    question_keywords = [kw for kw in re.split(r"[\s,，。；;、:：()（）]+", question_text.lower()) if len(kw) >= 2]
    query_keywords = [kw for q in queries for kw in re.split(r"\W+", q.lower()) if len(kw) >= 5]
    score = 0.0
    score += sum(1.8 for kw in question_keywords[:18] if kw and kw in haystack)
    score += sum(1.0 for kw in query_keywords[:30] if kw and kw in haystack)
    score += len(item.get("method_tags") or []) * 3.0
    if item.get("abstract"):
        score += 4.0
    if item.get("doi"):
        score += 2.0
    if item.get("source") == "OpenAlex":
        score += 3.0
    elif item.get("source") == "Crossref":
        score += 1.0
    year = item.get("year")
    try:
        if year:
            score += max(0, min(6, (int(year) - 2010) / 3))
    except Exception:
        pass
    return round(score, 3)


def _persist_reference_pack(
    work_dir: str | None,
    question_index: int | None,
    queries: list[str],
    references: list[dict[str, Any]],
) -> None:
    if not work_dir or question_index is None:
        return
    path = Path(work_dir) / _REFERENCE_INDEX_FILE
    with _WRITE_LOCK:
        try:
            payload: dict[str, Any] = {}
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    payload = {}
            payload[f"ques{question_index}"] = {
                "query_list": queries,
                "all_candidates": references,
                "selected_sources": references[:5],
                "updated_at": int(time.time()),
            }
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except Exception as exc:
            logger.warning(f"写入建模文献依据失败 {path}: {exc}")


def search_modeling_references(
    problem_title: str,
    question_text: str,
    user_message: str = "",
    *,
    limit: int = 8,
    work_dir: str | None = None,
    question_index: int | None = None,
) -> list[dict[str, Any]]:
    queries = build_academic_queries(problem_title, question_text, user_message)
    cache_key = _hash_payload({"title": problem_title, "question": question_text, "user": user_message, "queries": queries, "limit": limit})
    cached = _read_cache(work_dir, cache_key)
    if cached is not None:
        _persist_reference_pack(work_dir, question_index, queries, cached)
        return cached[:limit]

    raw_results: list[dict[str, Any]] = []
    per_query_limit = max(4, min(8, limit))
    for query in queries:
        for name, searcher, factor in [
            ("OpenAlex", _search_openalex, 1),
            ("Tavily", _search_tavily, 1),
            ("Crossref", _search_crossref, 1),
        ]:
            try:
                raw_results.extend(searcher(query, per_query_limit))
            except Exception as exc:
                logger.warning(f"建模文献检索失败 {name}: {exc}")

    unique = _deduplicate(raw_results)
    for item in unique:
        item["relevance_score"] = _score(item, queries, question_text)
    unique.sort(key=lambda item: (float(item.get("relevance_score") or 0), int(item.get("year") or 0)), reverse=True)

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


def format_references_for_prompt(references: list[dict[str, Any]], *, max_items: int = 5) -> str:
    selected = references[:max_items]
    if not selected:
        return "[]"
    compact = []
    for ref in selected:
        compact.append(
            {
                "source_id": ref.get("source_id"),
                "title": ref.get("title"),
                "year": ref.get("year"),
                "source": ref.get("source"),
                "doi": ref.get("doi"),
                "url": ref.get("url"),
                "method_tags": ref.get("method_tags") or [],
                "relevance_score": ref.get("relevance_score"),
                "snippet": (ref.get("abstract") or ref.get("snippet") or "")[:420],
            }
        )
    return json.dumps(compact, ensure_ascii=False, indent=2)
