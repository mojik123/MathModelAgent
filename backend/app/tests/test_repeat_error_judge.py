"""Coder 重复错误归一化与后台判定测试。"""

import asyncio
from unittest.mock import patch

from app.core.llm.types import StandardResponse
from app.utils.repeat_error_judge import (
    error_recovery_advice,
    error_signature,
    judge_repeated_error,
)


class _JudgeLLM:
    """记录内部判定器调用参数的假 LLM。"""

    def __init__(self, content: str):
        self.content = content
        self.kwargs: dict = {}

    async def chat(self, **kwargs) -> StandardResponse:
        self.kwargs = kwargs
        return StandardResponse(content=self.content)


def test_numeric_conversion_errors_share_one_stable_family() -> None:
    """NaN 与 Excel 尾注触发的整数转换失败属于同一根因。"""
    nan_error = "ValueError: cannot convert float NaN to integer"
    note_error = "ValueError: invalid literal for int() with base 10: '注：'"

    assert error_signature(nan_error) == "data_conversion:numeric"
    assert error_signature(note_error) == "data_conversion:numeric"


def test_numeric_recovery_advice_requires_coercion_and_rejected_row_audit() -> None:
    """数值转换失败必须获得可直接执行的清洗方案。"""
    advice = error_recovery_advice(
        "ValueError: invalid literal for int() with base 10: '注：'"
    )

    assert "pd.to_numeric" in advice
    assert 'errors="coerce"' in advice
    assert "转换失败" in advice
    assert "Int64" in advice


def test_merge_suffix_key_error_gets_schema_specific_advice() -> None:
    """merge 后同名列丢失时应提示检查后缀而不是重复访问原列。"""
    error = "KeyError: '作物类型'"

    assert error_signature(error) == "schema:missing_column:作物类型"
    assert "suffixes" in error_recovery_advice(error)


def test_background_judge_is_hidden_and_bounded() -> None:
    """后台判定不写对话流，且只允许一次非关键模型尝试。"""
    judge_llm = _JudgeLLM(
        '{"same_error": true, "should_restart": false, '
        '"confidence": 0.8, "root_cause": "脏数据", '
        '"advice": "过滤尾注", "reason": "同属数值转换"}'
    )

    with patch(
        "app.utils.repeat_error_judge._get_judge_llm",
        return_value=judge_llm,
    ):
        result = asyncio.run(
            judge_repeated_error(
                task_id="task-1",
                subtask_title="eda",
                previous_error="ValueError: cannot convert float NaN to integer",
                current_error=(
                    "ValueError: invalid literal for int() with base 10: '注：'"
                ),
                current_code="df['编号'].astype(int)",
                same_count=2,
                retry_count=4,
            )
        )

    assert judge_llm.kwargs["publish_response"] is False
    assert judge_llm.kwargs["max_retries"] == 1
    assert result["same_error"] is True
    assert result["should_restart"] is True
    assert "deterministic_same_error_limit" in result["reason"]
