"""Coder completion guard and visible code-generation progress.

Each Coder attempt must finish with an explicit ``task_complete`` tool call.
The wrapper also exposes the real Coder loop to the task timeline: thinking,
streaming code generation, execution, error recovery, and cumulative code count.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.core.agents.coder_agent import CoderAgent as BaseCoderAgent
from app.schemas.A2A import CoderToWriter
from app.schemas.response import CoderMessage, SystemMessage
from app.services.redis_manager import redis_manager
from app.utils.log_util import logger


def _response_calls_task_complete(response: Any) -> bool:
    """Return whether the final model response explicitly calls task_complete."""
    tool_calls = getattr(response, "tool_calls", None) or []
    return any(getattr(call, "name", "") == "task_complete" for call in tool_calls)


def _tool_code(response: Any) -> str:
    """Extract Python source from the first execute_code tool call."""
    for call in getattr(response, "tool_calls", None) or []:
        if getattr(call, "name", "") != "execute_code":
            continue
        arguments = getattr(call, "arguments", None)
        if isinstance(arguments, dict):
            return str(arguments.get("code") or "")
        try:
            parsed = json.loads(str(arguments or "{}"))
            return str(parsed.get("code") or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            return ""
    return ""


def _scope_label(subtask_title: str) -> str:
    normalized = subtask_title.strip().lower()
    if normalized == "eda":
        return "EDA 数据探索"
    if normalized == "sensitivity_analysis":
        return "灵敏度分析"
    match = re.fullmatch(r"ques(\d+)", normalized)
    if match:
        return f"问题 {match.group(1)}"
    return subtask_title


def _first_clean_line(text: str) -> str:
    for raw_line in text.splitlines():
        line = re.sub(r"^[#>*`\-\s]+", "", raw_line).strip()
        if not line or line in {"代码介绍", "Python"}:
            continue
        return line[:96]
    return ""


def _code_label(response_content: str, code: str, subtask_title: str, index: int) -> str:
    """Build a concise user-facing name for one generated code block."""
    for pattern in (
        r"功能说明\s*[：:]\s*([^\n]+)",
        r"代码功能\s*[：:]\s*([^\n]+)",
        r"目标\s*[：:]\s*([^\n]+)",
    ):
        match = re.search(pattern, response_content or "", flags=re.I)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()[:96]

    save_match = re.search(
        r"savefig\s*\(\s*[frbu]*[\"']([^\"']+)[\"']",
        code,
        flags=re.I,
    )
    if save_match:
        return f"生成结果图片 {Path(save_match.group(1)).name}"
    if re.search(r"read_(?:excel|csv)|ExcelFile|read_table", code, flags=re.I):
        return "读取数据并检查字段与数据质量"
    if re.search(r"GridSearchCV|RandomizedSearchCV|cross_val|KFold", code, flags=re.I):
        return "模型训练、交叉验证与参数选择"
    if re.search(r"\.fit\s*\(|\.predict\s*\(|statsmodels|sm\.", code, flags=re.I):
        return "建立模型并计算预测结果"
    if re.search(r"sensitivity|敏感性|灵敏度|perturb", code, flags=re.I):
        return "执行参数扰动与灵敏度检验"
    if re.search(r"matplotlib|seaborn|plt\.|sns\.", code, flags=re.I):
        return "生成模型结果可视化"

    first_line = _first_clean_line(response_content or "")
    if first_line:
        return first_line
    return f"{_scope_label(subtask_title)}第 {index} 个计算步骤"


class CoderAgent(BaseCoderAgent):
    """Coder with explicit completion and observable code-generation progress."""

    _scope_code_counts: dict[tuple[str, str], int] = {}
    _last_model_response: Any = None
    _progress_subtask_title: str = ""
    _generated_code_count: int = 0
    _active_code_index: int = 0
    _active_code_label: str = ""

    def _counter_key(self, subtask_title: str) -> tuple[str, str]:
        """Keep code numbering continuous across main and fallback Coders."""
        return self.task_id, subtask_title.strip().lower()

    def _scope_count(self, subtask_title: str) -> int:
        return self._scope_code_counts.get(self._counter_key(subtask_title), 0)

    def _reserve_code_index(self, subtask_title: str) -> int:
        key = self._counter_key(subtask_title)
        next_index = self._scope_code_counts.get(key, 0) + 1
        self._scope_code_counts[key] = next_index
        return next_index

    def _identity(self, subtask_title: str) -> tuple[str, int | None, str]:
        question_index = getattr(self.model, "question_index", None)
        model_instance = getattr(self.model, "agent_instance_id", None)
        model_group = getattr(self.model, "group_id", None)
        if model_instance:
            instance_id = str(model_instance)
        elif question_index is not None:
            instance_id = f"q{question_index}.coder.main"
        else:
            instance_id = f"process.{subtask_title}.coder"
        group_id = str(
            model_group
            or (f"q{question_index}.coder" if question_index else instance_id)
        )
        return instance_id, question_index, group_id

    async def _publish_code_progress(
        self,
        *,
        subtask_title: str,
        state: str,
        action: str,
        code_count: int,
        code_index: int = 0,
        code_label: str = "",
        msg_type: str = "info",
    ) -> None:
        """Publish a structured, persistent Coder action for the task timeline."""
        instance_id, question_index, group_id = self._identity(subtask_title)
        lines = [
            f"代码求解进度：{action}｜已生成 {code_count} 段代码",
            f"子任务：{subtask_title}",
            f"状态：{state}",
        ]
        if code_index:
            lines.append(f"代码序号：{code_index}")
        if code_label:
            lines.append(f"代码名称：{code_label}")
        message = SystemMessage(
            content="\n".join(lines),
            type=msg_type,
            agent_instance_id=instance_id,
            question_index=question_index,
            phase="coding",
            group_id=group_id,
            feedback_kind="coder_progress",
        )
        try:
            await redis_manager.publish_message(self.task_id, message)
        except Exception as exc:
            logger.warning(f"发布 Coder 进度失败，不阻塞求解: {exc}")

    async def _publish_code_stream(
        self,
        *,
        subtask_title: str,
        code: str,
        code_index: int,
        code_label: str,
    ) -> None:
        """Reveal a completed tool-call code argument smoothly in the UI."""
        if not code:
            return
        instance_id, question_index, group_id = self._identity(subtask_title)
        stream_instance_id = f"{instance_id}.code-{code_index}"
        prefix = f"第 {code_index} 段代码：{code_label}\n"
        chunk_size = max(96, math.ceil(len(code) / 24))
        try:
            for end in range(chunk_size, len(code) + chunk_size, chunk_size):
                partial = code[: min(end, len(code))]
                await redis_manager.publish_message(
                    self.task_id,
                    CoderMessage(
                        content=prefix + partial,
                        stream_state="streaming",
                        agent_instance_id=stream_instance_id,
                        question_index=question_index,
                        phase="coding",
                        group_id=group_id,
                        feedback_kind="coder_code_stream",
                    ),
                )
                if end < len(code):
                    await asyncio.sleep(0.025)
            await redis_manager.publish_message(
                self.task_id,
                CoderMessage(
                    content=prefix + code,
                    stream_state="complete",
                    agent_instance_id=stream_instance_id,
                    question_index=question_index,
                    phase="coding",
                    group_id=group_id,
                    feedback_kind="coder_code_stream",
                ),
            )
        except Exception as exc:
            logger.warning(f"发布代码流失败，不阻塞执行: {exc}")

    async def _chat(self, *args: Any, **kwargs: Any) -> Any:
        subtask_title = self._progress_subtask_title
        next_index = self._scope_count(subtask_title) + 1 if subtask_title else 1
        if subtask_title:
            self._generated_code_count = self._scope_count(subtask_title)
            await self._publish_code_progress(
                subtask_title=subtask_title,
                state="thinking",
                action=(
                    f"正在思考 {_scope_label(subtask_title)} 的下一步，"
                    f"并准备第 {next_index} 段代码"
                ),
                code_count=self._generated_code_count,
            )

        response = await super()._chat(*args, **kwargs)
        self._last_model_response = response

        code = _tool_code(response)
        if code and subtask_title:
            self._generated_code_count = self._reserve_code_index(subtask_title)
            self._active_code_index = self._generated_code_count
            self._active_code_label = _code_label(
                getattr(response, "content", "") or "",
                code,
                subtask_title,
                self._active_code_index,
            )
            await self._publish_code_progress(
                subtask_title=subtask_title,
                state="generating",
                action=(
                    f"正在生成第 {self._active_code_index} 段代码："
                    f"{self._active_code_label}"
                ),
                code_count=self._generated_code_count,
                code_index=self._active_code_index,
                code_label=self._active_code_label,
            )
            await self._publish_code_stream(
                subtask_title=subtask_title,
                code=code,
                code_index=self._active_code_index,
                code_label=self._active_code_label,
            )
        return response

    async def _publish_completion_guard(self, subtask_title: str, content: str) -> None:
        await self._publish_code_progress(
            subtask_title=subtask_title,
            state="incomplete",
            action=content,
            code_count=self._generated_code_count,
            code_index=self._active_code_index,
            code_label=self._active_code_label,
            msg_type="warning",
        )

    async def run(self, prompt: str, subtask_title: str) -> CoderToWriter:  # type: ignore[override]
        self._last_model_response = None
        self._progress_subtask_title = subtask_title
        self._generated_code_count = self._scope_count(subtask_title)
        self._active_code_index = 0
        self._active_code_label = ""

        interpreter = self.code_interpreter
        original_execute: Callable[[str], Awaitable[tuple[str, bool, str]]] | None = None
        if interpreter is not None:
            original_execute = interpreter.execute_code

            async def tracked_execute(code: str) -> tuple[str, bool, str]:
                index = self._active_code_index or self._generated_code_count
                label = self._active_code_label or f"第 {index} 段代码"
                await self._publish_code_progress(
                    subtask_title=subtask_title,
                    state="executing",
                    action=f"正在执行第 {index} 段代码：{label}",
                    code_count=self._generated_code_count,
                    code_index=index,
                    code_label=label,
                )
                assert original_execute is not None
                output, error_occurred, error_message = await original_execute(code)
                if error_occurred:
                    await self._publish_code_progress(
                        subtask_title=subtask_title,
                        state="error",
                        action=f"第 {index} 段代码执行失败，正在分析错误并准备修正",
                        code_count=self._generated_code_count,
                        code_index=index,
                        code_label=label,
                        msg_type="warning",
                    )
                else:
                    await self._publish_code_progress(
                        subtask_title=subtask_title,
                        state="completed",
                        action=f"第 {index} 段代码执行完成：{label}",
                        code_count=self._generated_code_count,
                        code_index=index,
                        code_label=label,
                        msg_type="success",
                    )
                return output, error_occurred, error_message

            interpreter.execute_code = tracked_execute  # type: ignore[method-assign]

        try:
            result = await super().run(prompt, subtask_title)
            if _response_calls_task_complete(self._last_model_response):
                await self._publish_code_progress(
                    subtask_title=subtask_title,
                    state="finished",
                    action=f"{_scope_label(subtask_title)}代码求解完成",
                    code_count=self._generated_code_count,
                    code_index=self._active_code_index,
                    code_label=self._active_code_label,
                    msg_type="success",
                )
                return result

            identity = getattr(self.model, "agent_instance_id", "CoderAgent")
            await self._publish_completion_guard(
                subtask_title,
                (
                    f"{subtask_title} 的 {identity} 已执行代码，但未显式调用 task_complete；"
                    "本次 Coder 尝试判定未完成，禁止启动论文写作，将按当前小问的备用流程处理。"
                ),
            )
            raise RuntimeError(
                f"{subtask_title} Coder 未显式调用 task_complete，不能进入 Writer"
            )
        finally:
            if interpreter is not None and original_execute is not None:
                interpreter.execute_code = original_execute  # type: ignore[method-assign]
            self._progress_subtask_title = ""
