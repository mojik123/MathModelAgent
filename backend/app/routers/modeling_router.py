"""建模任务路由模块，提供任务创建、API 验证和配置管理等接口。"""

from fastapi import APIRouter, File, Form, UploadFile
from app.core.workflow import MathModelWorkFlow
from app.schemas.enums import CompTemplate, FormatOutPut
from app.utils.log_util import logger
from app.services.redis_manager import redis_manager
from app.services.task_state import (
    get_task_state,
    mark_task_ready,
    mark_task_running,
    mark_task_stopping,
    mark_task_terminal,
)
from app.schemas.request import Problem
from app.schemas.response import SystemMessage, ProgressMessage, UserMessage
from app.utils.common_utils import (
    create_task_id,
    create_work_dir,
    get_current_files,
    get_work_dir,
    ensure_safe_task_id,
    md_2_docx,
    md_2_pdf,
)
import os
import asyncio
import hashlib
import json
import re
from typing import Any, Dict, Tuple
from fastapi import HTTPException
from icecream import ic  # type: ignore[import-unresolved]
from app.schemas.request import ExampleRequest
from pydantic import BaseModel
from app.config.setting import settings, ApiType
from app.core.llm.providers.openai_chat import OpenAIChatProvider
from app.core.llm.providers.openai_responses import OpenAIResponsesProvider
from app.core.llm.providers.anthropic import AnthropicProvider
from app.core.llm.providers.base import BaseProvider
from app.core.llm.llm import LLM, simple_chat
import requests

router = APIRouter()

# 任务注册表: task_id -> (asyncio.Task, asyncio.Event)
_active_tasks: Dict[str, dict] = {}
TASK_CONFIG_FILENAME = "task_config.json"
MODEL_OPTION_LIMIT = 4
MODEL_OPTIONS_CACHE_FILENAME = ".modeling_options_cache.json"


def _model_options_cache_key(
    title: str,
    background: str,
    questions: list[dict[str, Any]],
) -> str:
    payload = {
        "title": title,
        "background": background,
        "questions": [
            {
                "questionIndex": int(q.get("questionIndex") or idx + 1),
                "questionText": str(q.get("questionText") or ""),
            }
            for idx, q in enumerate(questions)
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_model_options_cache(task_id: str, cache_key: str) -> list[dict] | None:
    path = os.path.join(get_work_dir(task_id), MODEL_OPTIONS_CACHE_FILENAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            cached = json.load(f)
    except Exception as exc:
        logger.warning(f"读取模型候选缓存失败 {task_id}: {exc}")
        return None
    if cached.get("cache_key") != cache_key:
        return None
    cached_questions = cached.get("questions")
    return cached_questions if isinstance(cached_questions, list) else None


def _save_model_options_cache(
    task_id: str,
    cache_key: str,
    questions: list[dict[str, Any]],
) -> None:
    path = os.path.join(get_work_dir(task_id), MODEL_OPTIONS_CACHE_FILENAME)
    payload = {
        "cache_key": cache_key,
        "questions": questions,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning(f"写入模型候选缓存失败 {task_id}: {exc}")


def _strip_html(text: str | None) -> str:
    """将搜索结果中的 HTML/多余空白压缩成短文本。"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _contains_any(text: str, keywords: tuple[str, ...] | list[str]) -> bool:
    """大小写不敏感的关键词包含检查，避免中文正则在不同终端编码下出错。"""
    lower_text = text.lower()
    return any(keyword.lower() in lower_text for keyword in keywords)


def _extract_json_object(text: str) -> dict[str, Any]:
    """从 LLM 返回中提取 JSON 对象，兼容 ```json fenced block。"""
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()

    start = cleaned.find("{")
    if start < 0:
        raise ValueError("LLM 未返回 JSON 对象")

    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(cleaned[start:], start=start):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(cleaned[start : i + 1])
    raise ValueError("LLM 返回的 JSON 对象不完整")


def _model_option_id(label: str, question_index: int, option_index: int) -> str:
    raw = re.sub(r"[^a-zA-Z0-9]+", "_", label.lower()).strip("_")
    return raw or f"q{question_index}_model_{option_index}"


def _normalize_model_options_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    questions = payload.get("questions")
    if not isinstance(questions, list):
        raise ValueError("模型候选结果缺少 questions 数组")

    normalized_questions: list[dict[str, Any]] = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        question_index = int(q.get("questionIndex") or q.get("index") or 0)
        if question_index <= 0:
            continue

        raw_options = q.get("options")
        if not isinstance(raw_options, list):
            raw_options = []

        options: list[dict[str, Any]] = []
        for idx, raw_option in enumerate(raw_options[:MODEL_OPTION_LIMIT], start=1):
            if not isinstance(raw_option, dict):
                continue
            label = str(raw_option.get("label") or raw_option.get("model") or "").strip()
            if not label:
                continue
            option_id = str(raw_option.get("id") or "").strip() or _model_option_id(
                label, question_index, idx
            )
            score = raw_option.get("score")
            try:
                score = int(score)
            except Exception:
                score = None
            options.append(
                {
                    "id": option_id,
                    "label": label,
                    "description": str(raw_option.get("description") or "").strip(),
                    "pros": str(raw_option.get("pros") or "").strip(),
                    "cons": str(raw_option.get("cons") or "").strip(),
                    "reason": str(raw_option.get("reason") or "").strip(),
                    "score": score,
                    "isRecommended": bool(raw_option.get("isRecommended")),
                    "sources": raw_option.get("sources")
                    if isinstance(raw_option.get("sources"), list)
                    else [],
                }
            )

        if options and not any(option["isRecommended"] for option in options):
            recommended_id = str(q.get("recommendedOptionId") or "").strip()
            for option in options:
                if option["id"] == recommended_id:
                    option["isRecommended"] = True
                    break
            else:
                options[0]["isRecommended"] = True

        normalized_questions.append(
            {
                "questionIndex": question_index,
                "researchSummary": str(q.get("researchSummary") or "").strip(),
                "recommendedOptionId": next(
                    (
                        option["id"]
                        for option in options
                        if option.get("isRecommended")
                    ),
                    options[0]["id"] if options else "",
                ),
                "options": options,
            }
        )

    if not normalized_questions:
        raise ValueError("LLM 未生成有效模型候选")
    return normalized_questions


def _search_tavily(query: str, limit: int = 3) -> list[dict[str, str]]:
    if not settings.SEARCH_ENABLED or not settings.TAVILY_API_KEY:
        return []
    response = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": settings.TAVILY_API_KEY,
            "query": query,
            "max_results": limit,
            "search_depth": "basic",
            "include_answer": False,
        },
        timeout=10,
    )
    response.raise_for_status()
    results = response.json().get("results", [])
    return [
        {
            "title": str(item.get("title") or ""),
            "url": str(item.get("url") or ""),
            "snippet": _strip_html(str(item.get("content") or ""))[:500],
            "source": "tavily",
        }
        for item in results[:limit]
        if item.get("title") or item.get("content")
    ]


def _search_crossref(query: str, limit: int = 3) -> list[dict[str, str]]:
    response = requests.get(
        "https://api.crossref.org/works",
        params={"query": query, "rows": limit},
        timeout=10,
    )
    response.raise_for_status()
    items = response.json().get("message", {}).get("items", [])
    results: list[dict[str, str]] = []
    for item in items[:limit]:
        title = " ".join(item.get("title") or []) if isinstance(item.get("title"), list) else str(item.get("title") or "")
        container = (
            " ".join(item.get("container-title") or [])
            if isinstance(item.get("container-title"), list)
            else str(item.get("container-title") or "")
        )
        year_parts = item.get("issued", {}).get("date-parts") or []
        year = str(year_parts[0][0]) if year_parts and year_parts[0] else ""
        snippet = _strip_html(item.get("abstract"))
        fallback = "；".join(part for part in [container, year] if part)
        results.append(
            {
                "title": title,
                "url": str(item.get("URL") or ""),
                "snippet": snippet[:500] or fallback,
                "source": "crossref",
            }
        )
    return [result for result in results if result["title"] or result["snippet"]]


def _search_modeling_references(
    problem_title: str,
    question_text: str,
    user_message: str = "",
    limit: int = 3,
) -> list[dict[str, str]]:
    """联网检索与当前问题相关的建模方法，优先 Tavily，失败时退到 Crossref。"""
    inferred_terms = _infer_modeling_search_terms(question_text + " " + user_message)
    query = " ".join(
        part.strip()
        for part in [
            inferred_terms,
            problem_title,
            question_text[:120],
            user_message[:80],
            "model selection methods",
        ]
        if part and part.strip()
    )
    if not query:
        return []

    for searcher in (_search_tavily, _search_crossref):
        try:
            results = searcher(query, limit=limit)
            if results:
                return results
        except Exception as e:
            logger.warning(f"模型候选联网检索失败 {searcher.__name__}: {e}")
    return []


def _infer_modeling_search_terms(text: str) -> str:
    """基于题目关键词给联网检索加约束，防止被泛化搜索结果带偏。"""
    text_lower = text.lower()
    terms: list[str] = []
    keyword_terms = [
        (("社交媒体", "用户行为", "博主", "关注", "点赞", "评论"), "social media user behavior prediction follower growth recommender system"),
        (("推荐", "个性化", "内容分发"), "recommender systems collaborative filtering learning to rank"),
        (("时段", "时间习惯", "在线", "小时"), "temporal user activity prediction time aware recommendation"),
        (("新增关注", "增长", "次日"), "time series forecasting gradient boosting feature engineering"),
        (("是否", "二分类", "分类", "关注概率"), "binary classification logistic regression gradient boosting class imbalance"),
        (("预测", "forecast", "prediction"), "predictive modeling machine learning model comparison"),
        (("时间序列", "时序", "趋势"), "time series forecasting ARIMA XGBoost temporal features"),
        (("优化", "最优", "资源", "调度", "路径"), "optimization linear programming mixed integer programming heuristic algorithms"),
        (("评价", "指标", "综合评价"), "multi criteria decision making TOPSIS AHP entropy weight"),
        (("聚类", "画像", "分群"), "clustering user profiling kmeans gaussian mixture"),
    ]
    for keywords, phrase in keyword_terms:
        if any(keyword.lower() in text_lower for keyword in keywords):
            terms.append(phrase)
    if not terms:
        terms.append("mathematical modeling model selection data science")
    return " ".join(dict.fromkeys(terms))


def _infer_problem_traits(question_text: str) -> list[str]:
    """给 LLM 一个不可替代题面阅读的轻量任务类型提示。"""
    text = question_text.lower()
    traits: list[str] = []
    checks = [
        (("新增关注", "增长", "关注数", "互动数"), "计数/连续值预测"),
        (("是否", "二分类", "关注概率"), "二分类概率预测"),
        (("推荐", "top", "博主"), "推荐排序"),
        (("时段", "小时", "在线"), "时段感知/时间行为建模"),
        (("时间序列", "时序", "次日"), "短期时序预测"),
        (("优化", "最优", "约束"), "约束优化"),
        (("评价", "指标"), "多指标评价"),
    ]
    for keywords, trait in checks:
        if any(keyword.lower() in text for keyword in keywords):
            traits.append(trait)
    return traits or ["需由 LLM 结合题面判断任务类型"]


def _seed_model_guidance(question_text: str) -> list[str]:
    """按题面任务类型给 LLM 动态提示可考虑方向，最终仍由 LLM 筛选排序。"""
    text = question_text.lower()
    hints: list[str] = []
    if any(key in text for key in ("新增关注", "增长", "次日", "时间序列", "时序")):
        hints.extend(
            [
                "XGBoost/LightGBM + 滞后值/滚动窗口/累计量等时序特征",
                "Poisson 或负二项回归处理新增关注数这类计数目标",
                "ARIMA/Prophet 作为短期时序预测基线",
                "LSTM/Temporal Fusion Transformer 仅在时间序列足够长时作为复杂备选",
            ]
        )
    if any(key in text for key in ("是否", "新关注", "关注概率", "二分类", "分类")):
        hints.extend(
            [
                "L2/ElasticNet 逻辑回归 + 类别不平衡处理，适合概率解释",
                "XGBoost/LightGBM/CatBoost 分类器，适合非线性用户-博主交互特征",
                "Factorization Machines 处理稀疏用户-博主交叉特征",
                "学习排序或阈值优化用于从候选博主中筛选最可能关注对象",
            ]
        )
    if any(key in text for key in ("推荐", "博主", "top", "互动数")):
        hints.extend(
            [
                "两阶段推荐：在线状态/活跃度预测 + 用户-博主互动强度排序",
                "协同过滤/矩阵分解/隐语义模型，用于用户-博主偏好匹配",
                "Learning-to-Rank 或 LambdaMART，用于 TopN 推荐排序",
                "Factorization Machines/LightFM 融合用户、博主和交互特征",
            ]
        )
    if any(key in text for key in ("时段", "小时", "在线", "时间习惯")):
        hints.extend(
            [
                "时段感知推荐：用户小时画像 + 博主时段热度矩阵 + 互动倾向融合",
                "随机森林/LightGBM 预测用户在线时段概率",
                "时间感知协同过滤或序列推荐模型，处理小时级活跃偏好",
                "Markov/序列转移模型作为在线时段预测基线",
            ]
        )
    if any(key in text for key in ("优化", "最优", "约束", "资源", "路径", "调度")):
        hints.extend(
            [
                "线性规划/整数规划用于明确目标函数与约束的优化问题",
                "动态规划用于阶段决策和状态转移清晰的问题",
                "遗传算法/粒子群/模拟退火仅作为非线性或离散复杂优化备选",
            ]
        )
    if any(key in text for key in ("评价", "指标", "综合评价")):
        hints.extend(
            [
                "熵权法/TOPSIS 用于多指标综合评价",
                "AHP 用于专家偏好明确的层次评价",
                "灰色关联分析用于样本较少且指标关联未知的评价问题",
            ]
        )
    return list(dict.fromkeys(hints))


def _validate_model_options_for_questions(
    normalized: list[dict[str, Any]],
    question_map: dict[int, dict[str, Any]],
) -> list[str]:
    """检查 LLM 候选是否明显脱题；返回问题列表，供自动重试。"""
    issues: list[str] = []
    optimization_terms = (
        "遗传算法",
        "粒子群",
        "模拟退火",
        "线性规划",
        "整数规划",
        "NSGA",
        "多目标优化",
        "贝叶斯优化",
    )
    evaluation_terms = ("TOPSIS", "AHP", "熵权", "MCDA", "DEA", "灰色关联")

    for result in normalized:
        idx = int(result.get("questionIndex") or 0)
        source = question_map.get(idx, {})
        question_text = str(source.get("questionText") or "")
        traits = "、".join(source.get("systemHints") or [])
        options = result.get("options") if isinstance(result.get("options"), list) else []
        if len(options) < 3:
            issues.append(f"第{idx}问候选不足 3 个")
            continue

        recommended = next(
            (option for option in options if option.get("isRecommended")),
            options[0],
        )
        recommended_text = " ".join(
            str(recommended.get(field) or "")
            for field in ("label", "description", "reason", "pros", "cons")
        )
        recommended_focus_text = " ".join(
            str(recommended.get(field) or "")
            for field in ("label", "reason")
        )
        all_text = " ".join(
            " ".join(
                str(option.get(field) or "")
                for field in ("label", "description", "reason")
            )
            for option in options
        )

        if any(bad in all_text for bad in ("本题未明确", "通用首选", "常见优化/分类任务", "生产调度")):
            issues.append(f"第{idx}问候选过泛化或脱离题面")

        is_temporal_task = (
            "时段感知/时间行为建模" in traits
            or "时段" in question_text
            or "在线" in question_text
            or "小时" in question_text
        )
        is_short_count_forecast = (
            "短期时序预测" in traits
            or "新增关注" in question_text
            or "次日" in question_text
        )
        is_binary_follow_task = (
            "二分类概率预测" in traits
            or "新关注" in question_text
            or "关注概率" in question_text
            or "是否" in question_text
        )

        if is_temporal_task:
            temporal_hits = [
                key
                for key in ("时段", "小时", "时间", "在线", "活跃", "推荐", "排序", "协同", "矩阵", "序列", "互动", "博主")
                if _contains_any(recommended_focus_text, (key,))
            ]
            if len(temporal_hits) < 2:
                issues.append(f"第{idx}问推荐模型没有体现时段/在线/推荐任务")
            if "博主" in question_text and "互动数" in question_text:
                if not (
                    _contains_any(recommended_focus_text, ("博主",))
                    and _contains_any(recommended_focus_text, ("互动", "互动数"))
                    and _contains_any(recommended_focus_text, ("时段", "小时", "时间"))
                ):
                    issues.append(f"第{idx}问推荐理由没有覆盖博主、互动数和时段三要素")

        if is_short_count_forecast:
            if not _contains_any(
                recommended_focus_text,
                (
                    "新增关注",
                    "关注数",
                    "博主",
                    "次日",
                    "计数",
                    "时序",
                    "滞后",
                    "滚动",
                    "窗口",
                    "xgboost",
                    "lightgbm",
                    "poisson",
                    "负二项",
                    "arima",
                    "prophet",
                    "lstm",
                ),
            ):
                issues.append(f"第{idx}问推荐模型没有体现次日新增关注的时序计数预测")
            if _contains_any(
                recommended_focus_text,
                ("在线时段", "二分类", "推荐排序", "预测互动数", "互动数预测", "目标为互动数"),
            ):
                issues.append(f"第{idx}问推荐模型把新增关注数预测误写成其他任务")

        if is_binary_follow_task:
            if not _contains_any(
                recommended_focus_text,
                (
                    "分类",
                    "分类器",
                    "概率",
                    "逻辑回归",
                    "logistic",
                    "auc",
                    "不平衡",
                    "factorization",
                    "用户-博主",
                    "新关注",
                    "关注行为",
                ),
            ):
                issues.append(f"第{idx}问推荐模型没有体现关注行为分类/概率预测")
            if _contains_any(
                recommended_focus_text,
                ("在线时段", "在线时长", "目标为互动数", "预测互动数", "互动数预测"),
            ):
                issues.append(f"第{idx}问推荐模型把新关注分类误写成在线/互动数任务")
            if _contains_any(recommended_focus_text, ("预测互动数", "互动数预测", "回归")) and not _contains_any(
                recommended_focus_text, ("逻辑回归", "logistic")
            ):
                issues.append(f"第{idx}问推荐模型把新关注分类误写成回归/互动数预测")

        is_recommendation_question = any(
            key in question_text
            for key in ("推荐", "博主", "互动数", "时段", "在线")
        )
        is_optimization_question = any(
            key in question_text
            for key in ("优化", "最优", "约束", "资源", "路径", "调度")
        )
        is_evaluation_question = any(
            key in question_text
            for key in ("评价", "指标", "综合评价")
        )
        if is_recommendation_question and not is_optimization_question:
            if any(term in recommended_focus_text for term in optimization_terms):
                issues.append(f"第{idx}问推荐模型误用了优化算法作为主模型")
        if not is_evaluation_question:
            if any(term in recommended_focus_text for term in evaluation_terms):
                issues.append(f"第{idx}问推荐模型误用了评价模型作为主模型")

        if traits and not any(term in all_text for term in _seed_model_guidance(question_text)[:2]):
            # 这里只做弱约束：候选文本至少应靠近题面提示，而不是完全泛化。
            if "需由 LLM" not in traits and len(question_text) > 20:
                relevant_keywords = [
                    key
                    for key in ("博主", "关注", "用户", "互动", "时段", "在线", "推荐", "预测")
                    if key in question_text
                ]
                if relevant_keywords and not any(key in all_text for key in relevant_keywords):
                    issues.append(f"第{idx}问候选没有覆盖题面关键词：{','.join(relevant_keywords)}")

    return issues


def _task_config_path(task_id: str) -> str:
    safe_task_id = ensure_safe_task_id(task_id)
    return os.path.join(get_work_dir(safe_task_id), TASK_CONFIG_FILENAME)


def _save_task_config(
    task_id: str,
    ques_all: str,
    comp_template: CompTemplate,
    format_output: FormatOutPut,
) -> None:
    config_path = _task_config_path(task_id)
    payload = {
        "task_id": task_id,
        "ques_all": ques_all,
        "comp_template": comp_template.value,
        "format_output": format_output.value,
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _load_task_problem(task_id: str) -> Problem:
    config_path = _task_config_path(task_id)
    if not os.path.exists(config_path):
        raise HTTPException(status_code=404, detail="任务配置不存在，无法启动")

    with open(config_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    return Problem(
        task_id=task_id,
        ques_all=payload.get("ques_all", ""),
        comp_template=CompTemplate(payload.get("comp_template", CompTemplate.CHINA.value)),
        format_output=FormatOutPut(payload.get("format_output", FormatOutPut.Markdown.value)),
    )


async def _mark_task_created(task_id: str, ques_all: str) -> None:
    await redis_manager.set(f"task_id:{task_id}", task_id)
    await mark_task_ready(task_id)
    await redis_manager.publish_message(task_id, UserMessage(content=ques_all))
    await redis_manager.publish_message(
        task_id,
        SystemMessage(content="任务已创建，等待手动启动"),
    )


class ValidateApiKeyRequest(BaseModel):
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    model_id: str
    api_type: str = "openai-chat"


class ValidateOpenalexEmailRequest(BaseModel):
    email: str


class ValidateOpenalexEmailResponse(BaseModel):
    valid: bool
    message: str


class ValidateApiKeyResponse(BaseModel):
    valid: bool
    message: str


class SaveApiConfigRequest(BaseModel):
    coordinator: dict
    modeler: dict
    coder: dict
    writer: dict
    openalex_email: str


@router.post("/save-api-config")
async def save_api_config(request: SaveApiConfigRequest):
    """
    保存验证成功的 API 配置到 settings
    """
    try:
        # 更新各个模块的设置（仅当传入非空值时才覆盖，防止空串冲掉 .env.dev 配置）
        def _apply_config(prefix: str, config: dict) -> None:
            key = config.get("apiKey", "")
            model = config.get("modelId", "")
            base = config.get("baseUrl", "")
            if key:
                setattr(settings, f"{prefix}_API_KEY", key)
            if model:
                setattr(settings, f"{prefix}_MODEL", model)
            if base:
                setattr(settings, f"{prefix}_BASE_URL", base)
            if api_type := config.get("apiType"):
                setattr(settings, f"{prefix}_API_TYPE", api_type)
            if cw := config.get("contextWindow"):
                setattr(settings, f"{prefix}_CONTEXT_WINDOW", int(cw))

        if request.coordinator:
            _apply_config("COORDINATOR", request.coordinator)
        if request.modeler:
            _apply_config("MODELER", request.modeler)
        if request.coder:
            _apply_config("CODER", request.coder)
        if request.writer:
            _apply_config("WRITER", request.writer)

        if request.openalex_email:
            settings.OPENALEX_EMAIL = request.openalex_email

        return {"success": True, "message": "配置保存成功"}
    except Exception as e:
        logger.error(f"保存配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"保存配置失败: {str(e)}")


@router.post("/validate-api-key", response_model=ValidateApiKeyResponse)
async def validate_api_key(request: ValidateApiKeyRequest):
    """
    验证 API Key 的有效性
    """
    try:
        provider: BaseProvider
        match request.api_type:
            case ApiType.OPENAI_RESPONSES:
                provider = OpenAIResponsesProvider()
            case ApiType.ANTHROPIC:
                provider = AnthropicProvider()
            case _:
                provider = OpenAIChatProvider()

        await provider.call(
            messages=[{"role": "user", "content": "Hi"}],
            model=request.model_id,
            api_key=request.api_key,
            base_url=request.base_url
            if request.base_url != "https://api.openai.com/v1"
            else None,
            max_tokens=1,
        )

        return ValidateApiKeyResponse(valid=True, message="✓ 模型 API 验证成功")
    except Exception as e:
        error_msg = str(e)

        # 解析不同类型的错误
        if "401" in error_msg or "Unauthorized" in error_msg:
            return ValidateApiKeyResponse(valid=False, message="✗ API Key 无效或已过期")
        elif "404" in error_msg or "Not Found" in error_msg:
            return ValidateApiKeyResponse(
                valid=False, message="✗ 模型 ID 不存在或 Base URL 错误"
            )
        elif "429" in error_msg or "rate limit" in error_msg.lower():
            return ValidateApiKeyResponse(
                valid=False, message="✗ 请求过于频繁，请稍后再试"
            )
        elif "403" in error_msg or "Forbidden" in error_msg:
            return ValidateApiKeyResponse(
                valid=False, message="✗ API 权限不足或账户余额不足"
            )
        else:
            return ValidateApiKeyResponse(
                valid=False, message=f"✗ 验证失败: {error_msg[:50]}..."
            )


@router.post("/validate-openalex-email", response_model=ValidateOpenalexEmailResponse)
async def validate_openalex_email(request: ValidateOpenalexEmailRequest):
    """
    验证 OpenAlex Email 的有效性
    """
    try:
        params = {"mailto": request.email}
        if settings.OPENALEX_API_KEY:
            params["api_key"] = settings.OPENALEX_API_KEY

        response = requests.get("https://api.openalex.org/works", params=params)
        logger.debug(f"OpenAlex Email 验证响应: {response}")
        response.raise_for_status()
        return ValidateOpenalexEmailResponse(
            valid=True, message="✓ OpenAlex Email 验证成功"
        )
    except Exception as e:
        return ValidateOpenalexEmailResponse(
            valid=False, message=f"✗ OpenAlex Email 验证失败: {str(e)}"
        )


@router.post("/example")
async def exampleModeling(
    example_request: ExampleRequest,
):
    task_id = create_task_id()
    work_dir = create_work_dir(task_id)
    example_dir = os.path.join("app", "example", "example", example_request.source)
    ic(example_dir)
    with open(os.path.join(example_dir, "questions.txt"), "r", encoding="utf-8") as f:
        ques_all = f.read()

    current_files = get_current_files(example_dir, "data")
    for file in current_files:
        src_file = os.path.join(example_dir, file)
        dst_file = os.path.join(work_dir, file)
        with open(src_file, "rb") as src, open(dst_file, "wb") as dst:
            dst.write(src.read())
    _save_task_config(task_id, ques_all, CompTemplate.CHINA, FormatOutPut.Markdown)
    await _mark_task_created(task_id, ques_all)
    return {"task_id": task_id, "status": "created"}


@router.post("/modeling")
async def modeling(
    ques_all: str = Form(...),  # 从表单获取
    comp_template: CompTemplate = Form(...),  # 从表单获取
    format_output: FormatOutPut = Form(...),  # 从表单获取
    files: list[UploadFile] = File(default=None),
):
    task_id = create_task_id()
    work_dir = create_work_dir(task_id)

    # 如果有上传文件，保存文件
    if files:
        logger.info(f"开始处理上传的文件，工作目录: {work_dir}")
        for file in files:
            try:
                assert file.filename is not None
                data_file_path = os.path.join(work_dir, file.filename)
                logger.info(f"保存文件: {file.filename} -> {data_file_path}")

                # 确保文件名不为空
                if not file.filename:
                    logger.warning("跳过空文件名")
                    continue

                content = await file.read()
                if not content:
                    logger.warning(f"文件 {file.filename} 内容为空")
                    continue

                with open(data_file_path, "wb") as f:
                    f.write(content)
                logger.info(f"成功保存文件: {data_file_path}")

            except Exception as e:
                logger.error(f"保存文件 {file.filename} 失败: {str(e)}")
                raise HTTPException(
                    status_code=500, detail=f"保存文件 {file.filename} 失败: {str(e)}"
                )
    else:
        logger.warning("没有上传文件")

    _save_task_config(task_id, ques_all, comp_template, format_output)
    await _mark_task_created(task_id, ques_all)
    return {"task_id": task_id, "status": "created"}


@router.post("/modeling/{task_id}/start")
async def start_task(task_id: str):
    """手动启动或重新启动一个已创建的建模任务。"""
    try:
        safe_task_id = ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc

    active = _active_tasks.get(safe_task_id)
    if active and active.get("task") is not None and not active["task"].done():
        state = await get_task_state(safe_task_id)
        status = state.get("status") if state else "running"
        return {"success": True, "status": status, "message": "任务已在运行"}
    if active and active["task"].done():
        _active_tasks.pop(safe_task_id, None)

    state = await get_task_state(safe_task_id)
    if state and state.get("status") == "stopping":
        state = await mark_task_terminal(
            safe_task_id,
            "interrupted",
            "上次停止没有对应的后台任务，已标记为中断，可重新启动",
        )
    is_resume = bool(state and state.get("status") in {"stopped", "interrupted", "failed"})

    problem = _load_task_problem(safe_task_id)
    await redis_manager.set(f"task_id:{safe_task_id}", safe_task_id)
    start_message = (
        "任务已启动，将从最近完成的步骤继续执行"
        if is_resume
        else "任务已启动，等待后台流程接管"
    )
    await mark_task_running(
        safe_task_id,
        start_message,
        current_step="resume" if is_resume else "start",
        progress=0,
    )
    logger.info(f"Manually starting background task for task_id: {safe_task_id}")
    asyncio.create_task(
        run_modeling_task_async(
            safe_task_id,
            problem.ques_all,
            problem.comp_template,
            problem.format_output,
        ),
        name=f"modeling-{safe_task_id}",
    )
    return {"success": True, "status": "processing", "message": start_message}


@router.get("/modeling/{task_id}/state")
async def get_modeling_task_state(task_id: str):
    try:
        safe_task_id = ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc

    active = _active_tasks.get(safe_task_id)
    state = await get_task_state(safe_task_id)
    if active and active.get("task") is not None and not active["task"].done():
        if not state or state.get("status") not in {"running", "stopping"}:
            state = await mark_task_running(safe_task_id, "任务正在运行")
        return {
            "task_id": safe_task_id,
            "status": state.get("status", "running"),
            "message": state.get("message", "任务正在运行"),
            "current_step": state.get("current_step", ""),
            "progress": state.get("progress"),
            "started_at": state.get("started_at"),
            "finished_at": state.get("finished_at"),
            "updated_at": state.get("updated_at"),
            "active": True,
        }

    if state and state.get("status") in {"running", "stopping"}:
        state = await mark_task_terminal(safe_task_id, "interrupted", "后端没有找到运行中的任务，流程可能已中断")

    return {
        "task_id": safe_task_id,
        "status": (state or {}).get("status", "interrupted"),
        "message": (state or {}).get("message", "未找到运行状态"),
        "current_step": (state or {}).get("current_step", ""),
        "progress": (state or {}).get("progress"),
        "started_at": (state or {}).get("started_at"),
        "finished_at": (state or {}).get("finished_at"),
        "updated_at": (state or {}).get("updated_at"),
        "active": False,
    }


async def run_modeling_task_async(
    task_id: str,
    ques_all: str,
    comp_template: CompTemplate,
    format_output: FormatOutPut,
):
    """异步执行建模任务。

    Args:
        task_id: 任务 ID。
        ques_all: 完整题目信息。
        comp_template: 竞赛模板类型。
        format_output: 输出格式。
    """
    logger.info(f"run modeling task for task_id: {task_id}")

    # 立即注册到全局表（在所有 await 之前），确保后续代码始终能找到该条目
    cancel_event = asyncio.Event()
    # 使用 asyncio.current_task() 而非 None，确保状态端点不会在启动瞬间
    # 因 task is None 而错误返回 "interrupted"
    _active_tasks[task_id] = {"task": asyncio.current_task(), "cancel_event": cancel_event}

    problem = Problem(
        task_id=task_id,
        ques_all=ques_all,
        comp_template=comp_template,
        format_output=format_output,
    )

    await mark_task_running(task_id, "任务开始处理", current_step="准备中", progress=0)
    await redis_manager.publish_message(
        task_id,
        SystemMessage(content="任务开始处理"),
    )
    await redis_manager.publish_message(
        task_id,
        ProgressMessage(current=0, total=100, percentage=0, description="准备中..."),
    )

    # 给一个短暂的延迟，确保 WebSocket 有机会连接
    await asyncio.sleep(1)

    # 创建工作流并传入取消事件
    workflow = MathModelWorkFlow()
    workflow.cancel_event = cancel_event

    # 创建工作流任务并更新注册表
    task = asyncio.create_task(workflow.execute(problem))
    _active_tasks[task_id] = {"task": task, "cancel_event": cancel_event}

    task_completed = False
    try:
        # 设置超时时间（5 小时）
        await asyncio.wait_for(task, timeout=3600 * 5)
        task_completed = True

        await mark_task_terminal(task_id, "completed", "任务处理完成")
        # 发送任务完成状态
        await redis_manager.publish_message(
            task_id,
            SystemMessage(content="任务处理完成", type="success"),
        )
    except asyncio.CancelledError:
        logger.info(f"任务 {task_id} 被取消")
        await mark_task_terminal(task_id, "stopped", "任务已停止")
        await redis_manager.publish_message(
            task_id,
            SystemMessage(content="任务已停止", type="warning"),
        )
    except Exception as e:
        logger.error(f"任务 {task_id} 执行失败: {e}")
        await mark_task_terminal(task_id, "failed", f"任务执行失败: {str(e)}")
        await redis_manager.publish_message(
            task_id,
            SystemMessage(content=f"任务执行失败: {str(e)}", type="error"),
        )
    finally:
        # 从注册表中清理
        _active_tasks.pop(task_id, None)
        try:
            client = await redis_manager.get_client()
            await client.delete(f"task_id:{task_id}")
        except Exception as e:
            logger.warning(f"清理任务运行标记失败 {task_id}: {e}")
        # 仅在正常完成时转换 DOCX；PDF 改为用户打开 PDF 预览时按需编译。
        if task_completed:
            md_2_docx(task_id)


class CancelTaskResponse(BaseModel):
    success: bool
    message: str


@router.post("/modeling/{task_id}/cancel", response_model=CancelTaskResponse)
async def cancel_task(task_id: str):
    """取消正在运行的任务。"""
    try:
        safe_task_id = ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc

    active = _active_tasks.get(safe_task_id)
    if not active or active["task"].done():
        _active_tasks.pop(safe_task_id, None)
        return CancelTaskResponse(
            success=False,
            message="任务不存在或已完成",
        )

    running_task = active["task"]; cancel_event = active["cancel_event"]
    cancel_event.set()
    await mark_task_stopping(safe_task_id, "停止指令已发送，正在安全停止当前步骤")
    await redis_manager.publish_message(
        safe_task_id,
        SystemMessage(content="停止指令已发送，正在安全停止当前步骤"),
    )
    running_task.cancel()
    logger.info(f"已发送取消信号给任务 {safe_task_id}")

    return CancelTaskResponse(
        success=True,
        message="停止指令已发送",
    )


class ModelingConfirmRequest(BaseModel):
    """用户确认建模方案的请求体。"""
    selections: list[dict]  # [{index: 1, model: "random_forest", chatHistory: [...]}, ...]


class ModelingOptionsRequest(BaseModel):
    """为建模讨论卡片动态生成候选模型。"""
    title: str = ""
    background: str = ""
    questions: list[dict]
    force_refresh: bool = False


class ModelingOptionsResponse(BaseModel):
    success: bool
    message: str
    questions: list[dict]


class ModelingDiscussionChatRequest(BaseModel):
    question_index: int
    message: str
    questions: list[dict]


class ModelingDiscussionChatResponse(BaseModel):
    success: bool


class QuestionConfirmRequest(BaseModel):
    """用户确认问题划分的请求体。"""
    questions: list[dict]


class QuestionDiscussionChatRequest(BaseModel):
    """问题划分讨论对话请求体。"""
    message: str
    questions: list[dict] = []
    original_problem: str = ""


class RegenerateQuestionsRequest(BaseModel):
    """重新生成问题划分请求体。"""
    message: str = ""
    questions: list[dict] = []
    original_problem: str = ""


class RegenerateQuestionsResponse(BaseModel):
    success: bool
    message: str
    questions: list[dict]


class OriginalProblemResponse(BaseModel):
    task_id: str
    ques_all: str
    files: list[str] = []
    message: str
    content: str


@router.post("/modeling/{task_id}/model-options", response_model=ModelingOptionsResponse)
async def generate_model_options(task_id: str, body: ModelingOptionsRequest):
    """根据题目动态生成逐问模型候选，而不是返回固定预设列表。"""
    try:
        safe_task_id = ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc

    questions = [
        {
            "questionIndex": int(q.get("index") or q.get("questionIndex") or idx + 1),
            "questionText": str(q.get("text") or q.get("questionText") or ""),
            "systemHints": _infer_problem_traits(
                str(q.get("text") or q.get("questionText") or "")
            ),
            "candidateHints": _seed_model_guidance(
                str(q.get("text") or q.get("questionText") or "")
            ),
        }
        for idx, q in enumerate(body.questions)
        if isinstance(q, dict)
    ]
    if not questions:
        raise HTTPException(status_code=400, detail="缺少问题列表，无法生成模型候选")

    cache_key = _model_options_cache_key(body.title, body.background, questions)
    if not body.force_refresh:
        cached_questions = _load_model_options_cache(safe_task_id, cache_key)
        if cached_questions:
            return ModelingOptionsResponse(
                success=True,
                message="已复用本题已有模型候选结果",
                questions=cached_questions,
            )

    total_q = len(questions)
    await redis_manager.publish_message(
        safe_task_id,
        SystemMessage(content=f"ModelerAgent 正在为 {total_q} 个问题并行生成候选模型方案..."),
    )

    # 进度追踪
    progress: dict[int, str] = {}
    progress_lock = asyncio.Lock()

    async def _publish_progress():
        searching = sorted([k for k, v in progress.items() if v == "searching"])
        generating = sorted([k for k, v in progress.items() if v == "generating"])
        done = sorted([k for k, v in progress.items() if v == "done"])
        parts: list[str] = []
        if searching:
            parts.append(f"第 {'、'.join(str(i) for i in searching)} 问正在检索文献")
        if generating:
            parts.append(f"第 {'、'.join(str(i) for i in generating)} 问正在生成模型方案")
        if done:
            parts.append(f"第 {'、'.join(str(i) for i in done)} 问已完成")
        msg = "；".join(parts) if parts else "正在准备..."
        await redis_manager.publish_message(safe_task_id, SystemMessage(content=msg))

    async def _generate_for_question(q: dict[str, Any]) -> dict[str, Any] | None:
        """每问一个独立协程：检索 → LLM 生成 → 质检 → 返回结果。"""
        q_idx = int(q["questionIndex"])
        q_llm = LLM(
            api_type=settings.MODELER_API_TYPE, api_key=settings.MODELER_API_KEY,
            model=settings.MODELER_MODEL, base_url=settings.MODELER_BASE_URL,
            task_id=safe_task_id, max_tokens=settings.MODELER_MAX_TOKENS,
        )

        async with progress_lock:
            progress[q_idx] = "searching"
            await _publish_progress()
        research = _search_modeling_references(body.title, q["questionText"], limit=3)

        async with progress_lock:
            progress[q_idx] = "generating"
            await _publish_progress()

        question_map = {q_idx: q}
        quality_issues: list[str] = []

        for attempt in range(3):
            if attempt > 0:
                await redis_manager.publish_message(
                    safe_task_id,
                    SystemMessage(content=f"第 {q_idx} 问自动质检未通过（第{attempt}次），正在重试...", type="warning"),
                )
            feedback_text = ""
            if quality_issues:
                feedback_text = "\n".join(f"- {item}" for item in quality_issues)

            prompt = (
                "请只针对下面这一问生成经过筛选的候选模型方案。\n"
                "要求：3-4 个候选、有且仅有一个 isRecommended=true、每个候选含 label/description/pros/cons/reason/score。\n"
                "禁止改写题目场景、禁止泛化理由、候选互有区分度。\n"
                f"{feedback_text}\n"
                "输出 JSON：{\"questions\":[{\"questionIndex\":" + str(q_idx) + ",\"researchSummary\":\"...\",\"recommendedOptionId\":\"...\",\"options\":[{\"id\":\"...\",\"label\":\"...\",\"description\":\"...\",\"pros\":\"...\",\"cons\":\"...\",\"reason\":\"...\",\"score\":92,\"isRecommended\":true,\"sources\":[]}]}]}\n\n"
                f"【题目标题】\n{body.title}\n\n"
                f"【题目背景】\n{body.background[:5000]}\n\n"
                f"【当前问题】\n{json.dumps(q, ensure_ascii=False, indent=2)}\n\n"
                f"【联网检索】\n{json.dumps(research, ensure_ascii=False, indent=2)}"
            )

            try:
                raw = await simple_chat(q_llm, [
                    {"role": "system", "content": "你是数学建模竞赛的模型选优专家。先判断题目结构再给候选模型，检索与题面不一致时服从题面。"},
                    {"role": "user", "content": prompt},
                ])
                parsed = _extract_json_object(raw)
                candidate_list = _normalize_model_options_payload(parsed)
                if not candidate_list:
                    continue
                candidate_list[0]["questionIndex"] = q_idx
                candidate = candidate_list[0]
                quality_issues = _validate_model_options_for_questions([candidate], question_map)
                if not quality_issues:
                    async with progress_lock:
                        progress[q_idx] = "done"
                        await _publish_progress()
                    return candidate
            except Exception as e:
                logger.warning(f"第{q_idx}问候选生成异常: {e}")

        logger.warning(f"第{q_idx}问候选生成失败（3次尝试均未通过质检）")
        async with progress_lock:
            progress[q_idx] = "done"
            await _publish_progress()
        return None

    # 每问一个独立协程并行执行
    try:
        tasks = [asyncio.create_task(_generate_for_question(q)) for q in questions]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.error(f"动态模型候选生成失败 {safe_task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"动态模型候选生成失败: {e}") from e

    normalized: list[dict[str, Any]] = []
    for i, r in enumerate(raw_results):
        q_idx = int(questions[i].get("questionIndex", i + 1))
        if isinstance(r, Exception):
            logger.error(f"第{q_idx}问模型候选生成异常: {r}")
        elif r is not None:
            normalized.append(r)

    if not normalized:
        raise HTTPException(status_code=500, detail="所有问题的模型候选生成均失败")

    _save_model_options_cache(safe_task_id, cache_key, normalized)

    await redis_manager.publish_message(
        safe_task_id,
        SystemMessage(
            content=f"模型候选方案生成完成，共 {len(normalized)} 问，请在各卡片中选择建模方案",
            type="success",
        ),
    )

    return ModelingOptionsResponse(
        success=True,
        message="已基于题目和联网检索生成模型候选",
        questions=normalized,
    )


@router.post("/modeling/{task_id}/discussion-chat", response_model=ModelingDiscussionChatResponse)
async def modeling_discussion_chat(task_id: str, body: ModelingDiscussionChatRequest):
    """卡片内建模讨论：所有卡片历史一起作为共享上下文。"""
    try:
        safe_task_id = ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc

    selected_question = next(
        (
            question
            for question in body.questions
            if int(question.get("questionIndex", -1)) == body.question_index
        ),
        None,
    )
    search_context = _search_modeling_references(
        str(selected_question.get("questionTitle") or "") if selected_question else "",
        str(selected_question.get("questionText") or "") if selected_question else "",
        body.message,
        limit=3,
    )
    shared_context = json.dumps(body.questions, ensure_ascii=False, indent=2)
    user_prompt = (
        "你是建模方案讨论助手。用户会逐问选择模型，所有问题卡片共用同一个上下文。\n"
        "请结合全部卡片的已选模型、自定义方案、对话历史和联网检索摘要，回答当前问题卡片的追问。\n"
        "不要直接启动正式建模，只给出可供用户选择/修正的建议；如果更合适的模型不在候选卡片中，"
        "请明确建议用户通过「自定义方案」填写。\n\n"
        f"【当前讨论的问题】第 {body.question_index} 问\n"
        f"{json.dumps(selected_question, ensure_ascii=False, indent=2) if selected_question else '(未找到当前问题卡片)'}\n\n"
        f"【全部问题卡片共享上下文】\n{shared_context}\n\n"
        f"【本问联网检索摘要】\n{json.dumps(search_context, ensure_ascii=False, indent=2)}\n\n"
        f"【用户本轮消息】\n{body.message}"
    )

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
                    "content": (
                        "你是数学建模竞赛中的建模方案讨论助手。回答要简洁、具体、可执行；"
                        "必须围绕题目数据和目标做模型比选，不要局限在已有选项。"
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
        )
    except Exception as e:
        logger.error(f"建模讨论失败 {safe_task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"建模讨论失败: {e}") from e

    return ModelingDiscussionChatResponse(
        success=True,
        message="已生成建模讨论回复",
        content=content.strip(),
    )


@router.post("/modeling/{task_id}/confirm-modeling")
async def confirm_modeling(task_id: str, body: ModelingConfirmRequest):
    """接收用户确认的建模方案，恢复工作流继续执行。"""
    try:
        safe_task_id = ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc

    active = _active_tasks.get(safe_task_id)
    if not active:
        raise HTTPException(status_code=404, detail="任务不存在或已完成")

    event = active.get("modeling_ready_event")
    ref = active.get("modeling_selections_ref")
    if not event or not ref:
        raise HTTPException(status_code=409, detail="任务未在等待建模确认状态")
    if not body.selections:
        raise HTTPException(status_code=400, detail="请先为每一问选择建模方案")
    missing = [
        item.get("index")
        for item in body.selections
        if not str(item.get("model") or "").strip()
    ]
    if missing:
        raise HTTPException(status_code=400, detail=f"第 {missing} 问尚未选择建模方案")

    # 将用户选择存入工作流实例
    ref.modeling_selections = body.selections

    # 立即保存断点并发布确认消息，防止前端在 event.set() 与工作流实际写入之间刷新时丢失状态
    try:
        checkpoint = ref._load_checkpoint()
        checkpoint["modeling_selections"] = body.selections
        ref._save_checkpoint(checkpoint)
    except Exception as exc:
        logger.warning(f"预保存建模方案到断点失败 {safe_task_id}: {exc}")
    await redis_manager.publish_message(
        safe_task_id,
        SystemMessage(content="建模方案已确认，开始执行建模"),
    )

    event.set()
    logger.info(f"任务 {safe_task_id} 收到建模方案确认，共 {len(body.selections)} 问")

    return {"success": True, "message": "建模方案已确认，任务继续执行"}


# ── 问题划分讨论接口 ─────────────────────────────────────────────


@router.get("/modeling/{task_id}/problem")
async def get_original_problem(task_id: str):
    """获取原始题目内容，供问题讨论阶段右侧面板显示。"""
    try:
        safe_task_id = ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc

    try:
        problem = _load_task_problem(safe_task_id)
        work_dir = get_work_dir(safe_task_id)
        files: list[str] = []
        if os.path.exists(work_dir):
            files = [
                name for name in os.listdir(work_dir)
                if name != TASK_CONFIG_FILENAME and not name.startswith(".")
            ]
        return {
            "task_id": safe_task_id,
            "ques_all": problem.ques_all,
            "files": files,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取原始题目失败 {safe_task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"获取原始题目失败: {e}") from e


@router.post("/modeling/{task_id}/confirm-questions")
async def confirm_questions(task_id: str, body: QuestionConfirmRequest):
    """接收用户确认的问题划分，恢复工作流继续执行。"""
    try:
        safe_task_id = ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc

    active = _active_tasks.get(safe_task_id)
    if not active:
        raise HTTPException(status_code=404, detail="任务不存在或已完成")

    event = active.get("question_ready_event")
    ref = active.get("question_selections_ref")
    if not event or not ref:
        raise HTTPException(status_code=409, detail="任务未在等待问题划分确认状态")

    if not body.questions:
        raise HTTPException(status_code=400, detail="问题划分不能为空")

    valid_questions: list[dict] = []
    for idx, item in enumerate(body.questions, start=1):
        text = str(item.get("questionText") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail=f"第 {idx} 问内容不能为空")
        valid_questions.append({
            "questionIndex": idx,
            "questionTitle": str(item.get("questionTitle") or f"第 {idx} 问"),
            "questionText": text,
            "chatHistory": item.get("chatHistory", []),
        })

    ref.question_selections = valid_questions

    try:
        checkpoint = ref._load_checkpoint()
        checkpoint["question_selections"] = valid_questions
        ref._save_checkpoint(checkpoint)
    except Exception as exc:
        logger.warning(f"预保存问题划分失败 {safe_task_id}: {exc}")

    await redis_manager.publish_message(
        safe_task_id,
        SystemMessage(content="问题划分已确认，开始进入建模思路讨论"),
    )

    event.set()
    logger.info(f"任务 {safe_task_id} 收到问题划分确认，共 {len(valid_questions)} 问")
    return {"success": True, "message": "问题划分已确认，任务继续执行"}


@router.post("/modeling/{task_id}/question-discussion-chat")
async def question_discussion_chat(task_id: str, body: QuestionDiscussionChatRequest):
    """问题划分讨论：用户与 Agent 讨论如何拆分问题。"""
    try:
        safe_task_id = ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc

    user_prompt = (
        "你是数学建模竞赛题目分析助手。用户正在讨论题目应拆分为几个问题。\n"
        "你只提供问题划分建议，不进入具体建模方法。\n"
        "请简洁说明应该如何调整问题划分，给出具体的问题拆分方案。\n\n"
        f"【原始题目】\n{body.original_problem}\n\n"
        f"【当前问题卡片】\n{json.dumps(body.questions, ensure_ascii=False, indent=2)}\n\n"
        f"【用户意见】\n{body.message}"
    )

    llm = LLM(
        api_type=settings.COORDINATOR_API_TYPE,
        api_key=settings.COORDINATOR_API_KEY,
        model=settings.COORDINATOR_MODEL,
        base_url=settings.COORDINATOR_BASE_URL,
        task_id=safe_task_id,
    )
    try:
        content = await simple_chat(
            llm,
            [
                {
                    "role": "system",
                    "content": "你负责数学建模题目拆解。回答要具体，可直接指导用户修改问题卡片。",
                },
                {"role": "user", "content": user_prompt},
            ],
        )
    except Exception as e:
        logger.error(f"问题讨论失败 {safe_task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"问题讨论失败: {e}") from e

    return {
        "success": True,
        "message": "已生成问题划分讨论回复",
        "content": content.strip(),
    }


@router.post("/modeling/{task_id}/regenerate-questions", response_model=RegenerateQuestionsResponse)
async def regenerate_questions(task_id: str, body: RegenerateQuestionsRequest):
    """根据用户意见重新生成问题划分卡片。"""
    try:
        safe_task_id = ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc

    problem = _load_task_problem(safe_task_id)
    original_problem = body.original_problem or problem.ques_all

    prompt = (
        "请根据原始数学建模题目，重新生成问题划分。\n\n"
        "要求：\n"
        "1. 输出 JSON。\n"
        "2. questions 是数组。\n"
        "3. 每个问题包含 questionIndex、questionTitle、questionText。\n"
        "4. 问题数量根据题意确定，通常为 3-5 个。\n"
        "5. 每个 questionText 要写成可直接放入任务卡片的描述。\n"
        "6. 不要输出建模方法，不要输出代码。\n\n"
        f"【原始题目】\n{original_problem}\n\n"
        f"【用户调整意见】\n{body.message}\n\n"
        f"【当前问题划分】\n{json.dumps(body.questions, ensure_ascii=False, indent=2)}\n\n"
        "输出格式：\n"
        "{\n"
        '  "questions": [\n'
        "    {\n"
        '      "questionIndex": 1,\n'
        '      "questionTitle": "问题一标题",\n'
        '      "questionText": "问题一描述"\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    llm = LLM(
        api_type=settings.COORDINATOR_API_TYPE,
        api_key=settings.COORDINATOR_API_KEY,
        model=settings.COORDINATOR_MODEL,
        base_url=settings.COORDINATOR_BASE_URL,
        task_id=safe_task_id,
    )
    try:
        raw = await simple_chat(
            llm,
            [
                {
                    "role": "system",
                    "content": "你是数学建模竞赛题目拆解专家。只输出 JSON。",
                },
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as e:
        logger.error(f"重新生成问题划分失败 {safe_task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"重新生成问题划分失败: {e}") from e

    parsed = _extract_json_object(raw)
    questions = parsed.get("questions", [])
    normalized: list[dict] = []
    for idx, item in enumerate(questions, start=1):
        normalized.append({
            "questionIndex": idx,
            "questionTitle": str(item.get("questionTitle") or f"第 {idx} 问"),
            "questionText": str(item.get("questionText") or "").strip(),
        })
    normalized = [q for q in normalized if q["questionText"]]
    if not normalized:
        raise HTTPException(status_code=500, detail="重新生成问题划分失败：LLM 未返回有效结果")

    return RegenerateQuestionsResponse(
        success=True,
        message="已重新生成问题划分",
        questions=normalized,
    )
