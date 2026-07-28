"""Coder completion guard.

Require each Coder attempt to finish with an explicit ``task_complete`` tool call.
A plain assistant message after one successful code execution must not be treated as
proof that the current question has been fully solved.
"""

from __future__ import annotations

from typing import Any

from app.core.agents.coder_agent import CoderAgent as BaseCoderAgent
from app.schemas.A2A import CoderToWriter
from app.schemas.response import SystemMessage
from app.services.redis_manager import redis_manager


def _response_calls_task_complete(response: Any) -> bool:
    """Return whether the final model response explicitly calls task_complete."""
    tool_calls = getattr(response, "tool_calls", None) or []
    return any(getattr(call, "name", "") == "task_complete" for call in tool_calls)


class CoderAgent(BaseCoderAgent):
    """Coder that cannot hand work to Writer without explicit completion.

    The base Coder historically allowed a no-tool text response to end an attempt after
    any successful ``execute_code`` call. That could promote a partially explored
    question into Writer. This guard gives the same Coder one lightweight verification
    round while preserving its interpreter, files and chat history. If it still does not
    explicitly call ``task_complete``, the attempt fails and the workflow can switch to
    its normal fallback Coder.
    """

    _last_model_response: Any = None

    async def _chat(self, *args: Any, **kwargs: Any) -> Any:
        response = await super()._chat(*args, **kwargs)
        self._last_model_response = response
        return response

    async def _publish_completion_guard(self, subtask_title: str, content: str) -> None:
        message = SystemMessage(content=content, type="warning")
        question_index = getattr(self.model, "question_index", None)
        agent_instance_id = getattr(self.model, "agent_instance_id", None)
        group_id = getattr(self.model, "group_id", None)
        if question_index is not None:
            message.question_index = question_index
        if agent_instance_id:
            message.agent_instance_id = agent_instance_id
        if group_id:
            message.group_id = group_id
        message.phase = "coding"
        await redis_manager.publish_message(self.task_id, message)

    async def run(self, prompt: str, subtask_title: str) -> CoderToWriter:  # type: ignore[override]
        self._last_model_response = None
        result = await super().run(prompt, subtask_title)
        if _response_calls_task_complete(self._last_model_response):
            return result

        identity = getattr(self.model, "agent_instance_id", "CoderAgent")
        await self._publish_completion_guard(
            subtask_title,
            (
                f"{subtask_title} 的 {identity} 尚未显式确认求解完成，"
                "暂不启动论文写作；保留当前代码和数据，进入本问轻量核验。"
            ),
        )

        verification_prompt = f"""
【完成门禁：仅核验，不重新完整求解】
你刚才在子任务 {subtask_title} 中以普通文字结束，尚未显式调用 task_complete。
当前已经生成的代码、变量、数据文件和图片全部保留。

请执行以下动作：
1. 复用现有结果，不重新读取大文件，不重新进行完整搜索或大规模计算；
2. 调用一次 execute_code 做轻量核验，确认核心结果文件、关键数值或模型输出真实存在；
3. 若核验失败，直接修复当前缺口；
4. 核验通过后，必须调用 task_complete；
5. 禁止仅输出文字总结后结束。
""".strip()

        self._last_model_response = None
        verified_result = await super().run(verification_prompt, subtask_title)
        if _response_calls_task_complete(self._last_model_response):
            return verified_result

        await self._publish_completion_guard(
            subtask_title,
            (
                f"{subtask_title} 的 {identity} 在核验轮次后仍未调用 task_complete，"
                "本次 Coder 尝试判定失败，禁止进入 Writer。"
            ),
        )
        raise RuntimeError(
            f"{subtask_title} Coder 未显式调用 task_complete，不能进入 Writer"
        )
