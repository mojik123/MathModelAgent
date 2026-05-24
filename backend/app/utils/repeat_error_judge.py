"""Coordinator based repeated error judge for CoderAgent."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from app.config.setting import settings
from app.core.llm.llm import LLM
from app.utils.log_util import logger


def error_signature(error_message: str) -> str:
    lines = str(error_message or "").strip().split("\n")
    return lines[-1][:160] if lines else str(error_message)[:160]


def _json_from_text(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", text or "", flags=re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _get_judge_llm(task_id: str) -> LLM | None:
    if not getattr(settings, "CODER_REPEAT_ERROR_JUDGE_ENABLED", True):
        return None
    if not settings.COORDINATOR_API_TYPE or not settings.COORDINATOR_MODEL:
        return None
    try:
        return LLM(
            api_type=settings.COORDINATOR_API_TYPE,
            api_key=settings.COORDINATOR_API_KEY,
            model=settings.COORDINATOR_MODEL,
            base_url=settings.COORDINATOR_BASE_URL,
            task_id=task_id,
            max_tokens=min(int(settings.COORDINATOR_MAX_TOKENS or 4096), 4096),
        )
    except Exception as exc:
        logger.warning(f"Failed to build repeat-error judge LLM: {exc}")
        return None


async def judge_repeated_error(
    *,
    task_id: str,
    subtask_title: str,
    previous_error: str,
    current_error: str,
    current_code: str,
    same_count: int,
    retry_count: int,
) -> dict[str, Any]:
    fallback_same = bool(previous_error) and (
        error_signature(previous_error) == error_signature(current_error)
    )

    llm = _get_judge_llm(task_id)
    if llm is None:
        return {
            "same_error": fallback_same,
            "should_restart": False,
            "confidence": 0.0,
            "root_cause": error_signature(current_error),
            "advice": "根据最新错误重新定位，避免重复上一版修复路径。",
            "reason": "judge_llm_unavailable",
        }

    prompt = f"""
你是数学建模流程协调者。请判断 Coder 当前报错是否与上一轮属于同一根因，以及是否需要换一个新的 Coder 重新处理本小问。
只输出 JSON，不要输出 Markdown。

返回格式：
{{"same_error": true, "should_restart": false, "confidence": 0.85, "root_cause": "一句话根因", "advice": "给当前 Coder 的具体修复建议", "reason": "判断依据"}}

判断原则：
1. same_error=true：字段、路径、语法、约束、数据类型等根因相同。
2. should_restart=true：已经围绕同一根因重复修补，继续当前上下文价值不高，需要新 Coder 重新组织方案。
3. 如果错误在变化、修复方向在变化、已有成功执行，倾向 should_restart=false。

子任务：{subtask_title}
连续同类计数：{same_count}
累计错误次数：{retry_count}

上一轮错误：
{previous_error[-2000:] if previous_error else '(无)'}

当前错误：
{current_error[-2500:]}

当前代码摘要：
{current_code[-3000:]}
"""

    try:
        response = await llm.chat(
            history=[{"role": "user", "content": prompt}],
            agent_name="CoordinatorRepeatErrorJudge",
        )
        data = _json_from_text(response.content or "")
        return {
            "same_error": bool(data.get("same_error", fallback_same)),
            "should_restart": bool(data.get("should_restart", False)),
            "confidence": float(data.get("confidence", 0.0) or 0.0),
            "root_cause": str(data.get("root_cause") or error_signature(current_error)),
            "advice": str(data.get("advice") or ""),
            "reason": str(data.get("reason") or ""),
        }
    except Exception as exc:
        logger.warning(f"Repeat-error judge failed; using fallback signature: {exc}")
        return {
            "same_error": fallback_same,
            "should_restart": False,
            "confidence": 0.0,
            "root_cause": error_signature(current_error),
            "advice": "根据最新错误重新定位，避免重复上一版修复路径。",
            "reason": f"judge_failed: {exc}",
        }
