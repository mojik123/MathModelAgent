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
    """将具体异常归一化为可稳定比较的错误族。

    Args:
        error_message: Python 或数据处理异常文本。

    Returns:
        去除具体脏值和行号后的错误族标识。
    """
    text = str(error_message or "").strip()
    lower_text = text.lower()

    numeric_conversion_markers = (
        "invalid literal for int()",
        "cannot convert float nan to integer",
        "could not convert string to float",
        "unable to parse string",
        "cannot convert non-finite values",
    )
    if any(marker in lower_text for marker in numeric_conversion_markers):
        return "data_conversion:numeric"

    if "you are trying to merge on" in lower_text and (
        "int64 and object" in lower_text
        or "object and int64" in lower_text
        or "different types" in lower_text
    ):
        return "merge_key:dtype_mismatch"

    key_error = re.search(r"keyerror:\s*[\"']([^\"']+)[\"']", text, flags=re.I)
    if key_error:
        return f"schema:missing_column:{key_error.group(1).strip()}"

    if "indentationerror:" in lower_text or "taberror:" in lower_text:
        return "python_syntax:indentation"
    if "syntaxerror:" in lower_text:
        return "python_syntax:general"

    lines = text.splitlines()
    return lines[-1][:160] if lines else text[:160]


def error_recovery_advice(error_message: str) -> str:
    """返回无需额外模型调用即可执行的定向修复建议。

    Args:
        error_message: Python 或数据处理异常文本。

    Returns:
        与错误族对应的修复建议；未知错误返回通用建议。
    """
    signature = error_signature(error_message)
    if signature == "data_conversion:numeric":
        return (
            "不要对 Excel 原始列直接 astype(int)。先保存原始值，使用 "
            "pd.to_numeric(series, errors=\"coerce\")；打印转换失败且原值非空的行，"
            "过滤“注：”等尾注和空行后，再转为 pandas 可空整数 Int64。"
        )
    if signature == "merge_key:dtype_mismatch":
        return (
            "合并前分别检查两侧键的原值和 dtype，并将两侧统一为同一种可空类型；"
            "数值键使用 pd.to_numeric(..., errors=\"coerce\").astype(\"Int64\")，"
            "文本键使用 string.strip()。过滤无效键后再 merge，并核验匹配率。"
        )
    if signature.startswith("schema:missing_column:"):
        column = signature.rsplit(":", maxsplit=1)[-1]
        return (
            f"当前结果中不存在列“{column}”。先打印 columns；若 merge 两侧都有同名列，"
            "显式设置 suffixes 并从带后缀列合并回目标列，不能继续访问不存在的无后缀列。"
        )
    if signature == "python_syntax:indentation":
        return (
            "只重写报错代码块并统一使用 4 个空格缩进，禁止混用 Tab；"
            "先执行最小语法修复单元，再继续后续计算。"
        )
    return "根据最新 traceback 的最后一层定位根因，不要原样重跑上一版代码。"


def _deterministic_restart(fallback_same: bool, same_count: int) -> bool:
    """判断是否已达到无需模型裁决的同类错误切换阈值。"""
    max_same_error = max(
        2,
        int(getattr(settings, "CODER_MAX_SAME_ERROR", 2) or 2),
    )
    return fallback_same and same_count >= max_same_error


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
    deterministic_restart = _deterministic_restart(fallback_same, same_count)
    deterministic_advice = error_recovery_advice(current_error)

    llm = _get_judge_llm(task_id)
    if llm is None:
        return {
            "same_error": fallback_same,
            "should_restart": deterministic_restart,
            "confidence": 0.0,
            "root_cause": error_signature(current_error),
            "advice": deterministic_advice,
            "reason": (
                "deterministic_same_error_limit"
                if deterministic_restart
                else "judge_llm_unavailable"
            ),
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
            max_retries=1,
            publish_response=False,
        )
        data = _json_from_text(response.content or "")
        model_same = bool(data.get("same_error", fallback_same))
        model_restart = bool(data.get("should_restart", False))
        model_advice = str(data.get("advice") or "")
        model_reason = str(data.get("reason") or "")
        return {
            "same_error": model_same or fallback_same,
            "should_restart": model_restart or deterministic_restart,
            "confidence": float(data.get("confidence", 0.0) or 0.0),
            "root_cause": str(data.get("root_cause") or error_signature(current_error)),
            "advice": model_advice or deterministic_advice,
            "reason": (
                f"{model_reason}; deterministic_same_error_limit"
                if deterministic_restart and model_reason
                else (
                    "deterministic_same_error_limit"
                    if deterministic_restart
                    else model_reason
                )
            ),
        }
    except Exception as exc:
        logger.warning(f"Repeat-error judge failed; using fallback signature: {exc}")
        return {
            "same_error": fallback_same,
            "should_restart": deterministic_restart,
            "confidence": 0.0,
            "root_cause": error_signature(current_error),
            "advice": deterministic_advice,
            "reason": f"judge_failed: {exc}",
        }
