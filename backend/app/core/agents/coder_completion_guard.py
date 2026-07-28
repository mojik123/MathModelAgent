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
    """Coder that cannot hand incomplete work to Writer.

    Every question Coder and every fallback Coder keeps its own original execution
    budget. A plain text response never opens an additional budget and never starts
    Writer; the current attempt fails so the workflow can use its normal fallback path.
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
                f"{subtask_title} 的 {identity} 已执行代码，但未显式调用 task_complete；"
                "本次 Coder 尝试判定未完成，禁止启动论文写作，将按当前小问的备用流程处理。"
            ),
        )
        raise RuntimeError(
            f"{subtask_title} Coder 未显式调用 task_complete，不能进入 Writer"
        )
