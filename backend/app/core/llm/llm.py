"""LLM 交互模块，封装大语言模型的调用、重试和消息发送。"""

import asyncio
from typing import Any
from app.utils.common_utils import transform_link, split_footnotes
from app.utils.log_util import logger
import time
from app.schemas.response import (
    CoderMessage,
    WriterMessage,
    ModelerMessage,
    SystemMessage,
    CoordinatorMessage,
    SubCoordinatorMessage,
)
from app.services.redis_manager import redis_manager
from app.schemas.enums import AgentType
from app.config.setting import ApiType
from app.core.llm.types import StandardResponse
from app.core.llm.providers.base import BaseProvider
from app.core.llm.providers.openai_chat import OpenAIChatProvider
from app.core.llm.providers.openai_responses import OpenAIResponsesProvider
from app.core.llm.providers.anthropic import AnthropicProvider

# 流式发布节流间隔（秒）
_STREAM_THROTTLE_SECONDS = 0.08


class LLM:
    """大语言模型封装类，提供对话调用、重试和工具调用验证功能。"""

    def __init__(
        self,
        api_type: ApiType | None = None,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        task_id: str = "",
        max_tokens: int | None = None,
        agent_index: int | None = None,  # 并行组编号（1-based），None 表示全局单例
    ):
        self.api_type = api_type
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.chat_count = 0
        self.max_tokens = max_tokens
        self.task_id = task_id
        self.agent_index = agent_index
        self.provider = self._create_provider(api_type)

    def _create_provider(self, api_type: ApiType | None) -> BaseProvider:
        """根据 api_type 创建对应的 Provider。"""
        match api_type:
            case ApiType.OPENAI_RESPONSES:
                return OpenAIResponsesProvider()
            case ApiType.ANTHROPIC:
                return AnthropicProvider()
            case _:
                # 默认使用 OpenAI Chat Completions（兼容未配置 api_type 的情况）
                return OpenAIChatProvider()

    def _validate_config(self, agent_name: str) -> None:
        """验证 LLM 配置是否完整。"""
        if not self.model or not str(self.model).strip():
            raise ValueError(f"{agent_name} 未配置模型 ID，请设置对应的 *_MODEL")
        if not self.api_key or not str(self.api_key).strip():
            raise ValueError(f"{agent_name} 未配置 API Key，请设置对应的 *_API_KEY")

    async def chat(
        self,
        history: list | None = None,
        tools: list | None = None,
        tool_choice: str | None = None,
        max_retries: int | None = None,
        retry_delay: float = 1.0,
        top_p: float | None = None,
        agent_name: str = "SystemAgent",
        sub_title: str | None = None,
    ) -> StandardResponse:
        self._validate_config(agent_name)

        # 验证和修复工具调用完整性（仅对 OpenAI 格式的历史有效）
        if history:
            history = self._validate_and_fix_tool_calls(history)

        messages = history or []

        attempt = 0
        while True:
            try:
                response = await self.provider.call(
                    messages=messages,
                    model=self.model,  # type: ignore[arg-type]
                    api_key=self.api_key,  # type: ignore[arg-type]
                    base_url=self.base_url,
                    tools=tools,
                    tool_choice=tool_choice,
                    max_tokens=self.max_tokens,
                    top_p=top_p,
                )
                logger.info(f"API返回: content={response.content!r}, tool_calls={len(response.tool_calls or [])}")
                self.chat_count += 1
                await self.send_message(response, agent_name, sub_title)
                return response
            except Exception as e:
                attempt += 1
                logger.error(f"第{attempt}次重试: {str(e)}")
                if max_retries is not None and attempt >= max_retries:
                    raise
                time.sleep(retry_delay * min(attempt, 10))

    async def chat_stream(
        self,
        history: list | None = None,
        tools: list | None = None,
        tool_choice: str | None = None,
        max_retries: int | None = None,
        retry_delay: float = 1.0,
        top_p: float | None = None,
        agent_name: str = "SystemAgent",
        sub_title: str | None = None,
    ) -> StandardResponse:
        """流式调用 LLM，逐块发布增量内容到前端。

        与非流式 chat() 接口保持一致，但每次收到文本增量时
        立即通过 Redis 广播中间消息给前端。

        Returns:
            包含完整内容、用量和工具调用的 StandardResponse。
        """
        self._validate_config(agent_name)

        if history:
            history = self._validate_and_fix_tool_calls(history)

        messages = history or []

        attempt = 0
        while True:
            try:
                accumulated: list[str] = []
                accumulated_reasoning: list[str] = []
                last_publish_time = 0.0
                publish_task: asyncio.Task | None = None

                async for chunk in self.provider.call_stream(
                    messages=messages,
                    model=self.model,  # type: ignore[arg-type]
                    api_key=self.api_key,  # type: ignore[arg-type]
                    base_url=self.base_url,
                    tools=tools,
                    max_tokens=self.max_tokens,
                    top_p=top_p,
                ):
                    if chunk.is_done:
                        break

                    if chunk.reasoning_content:
                        accumulated_reasoning.append(chunk.reasoning_content)
                        if not chunk.delta:
                            continue

                    if chunk.delta:
                        accumulated.append(chunk.delta)
                        now_ts = time.monotonic()
                        if now_ts - last_publish_time >= _STREAM_THROTTLE_SECONDS:
                            # 发布中间增量
                            partial_content = "".join(accumulated)
                            await self._send_streaming_message(
                                partial_content, agent_name, sub_title
                            )
                            last_publish_time = now_ts

                # 构建最终响应
                full_content = "".join(accumulated)
                usage = chunk.usage
                tool_calls = chunk.tool_calls

                full_reasoning = "".join(accumulated_reasoning)
                response = StandardResponse(
                    content=full_content,
                    reasoning_content=full_reasoning or chunk.reasoning_content or None,
                    tool_calls=tool_calls,
                    usage=usage,
                )

                logger.info(f"流式返回完成: content_len={len(full_content)}, tool_calls={len(tool_calls or [])}")
                self.chat_count += 1
                await self.send_message(response, agent_name, sub_title)
                return response

            except Exception as e:
                attempt += 1
                logger.error(f"第{attempt}次重试 (stream): {str(e)}")
                if max_retries is not None and attempt >= max_retries:
                    raise
                time.sleep(retry_delay * min(attempt, 10))

    async def _send_streaming_message(
        self,
        partial_content: str,
        agent_name: str,
        sub_title: str | None = None,
    ) -> None:
        """发布流式增量消息到前端。"""
        from app.schemas.response import CoderMessage, WriterMessage, ModelerMessage, CoordinatorMessage, SubCoordinatorMessage

        idx = self.agent_index
        agent_msg: Any = None
        match agent_name:
            case AgentType.CODER:
                agent_msg = CoderMessage(content=partial_content, stream_state="streaming", agent_index=idx)
            case AgentType.WRITER:
                content, _ = split_footnotes(partial_content)
                content = transform_link(self.task_id, content)
                agent_msg = WriterMessage(content=content, sub_title=sub_title, stream_state="streaming", agent_index=idx)
            case AgentType.MODELER:
                agent_msg = ModelerMessage(content=partial_content, stream_state="streaming", agent_index=idx)
            case AgentType.COORDINATOR:
                agent_msg = CoordinatorMessage(content=partial_content, stream_state="streaming", agent_index=idx)
            case AgentType.SUB_COORDINATOR:
                agent_msg = SubCoordinatorMessage(content=partial_content, stream_state="streaming", agent_index=idx)
            case _:
                return

        await redis_manager.publish_message(self.task_id, agent_msg)

    def _validate_and_fix_tool_calls(self, history: list) -> list:
        """验证并修复工具调用完整性。"""
        if not history:
            return history

        fixed_history = []
        i = 0

        while i < len(history):
            msg = history[i]

            if isinstance(msg, dict) and "tool_calls" in msg and msg["tool_calls"]:
                valid_tool_calls = []
                for tool_call in msg["tool_calls"]:
                    tool_call_id = tool_call.get("id")
                    if tool_call_id:
                        found_response = False
                        for j in range(i + 1, len(history)):
                            if (
                                history[j].get("role") == "tool"
                                and history[j].get("tool_call_id") == tool_call_id
                            ):
                                found_response = True
                                break
                        if found_response:
                            valid_tool_calls.append(tool_call)

                if valid_tool_calls:
                    fixed_msg = msg.copy()
                    fixed_msg["tool_calls"] = valid_tool_calls
                    fixed_history.append(fixed_msg)
                else:
                    cleaned_msg = {k: v for k, v in msg.items() if k != "tool_calls"}
                    if cleaned_msg.get("content"):
                        fixed_history.append(cleaned_msg)

            elif isinstance(msg, dict) and msg.get("role") == "tool":
                tool_call_id = msg.get("tool_call_id")
                found_call = False
                for j in range(len(fixed_history)):
                    if fixed_history[j].get("tool_calls") and any(
                        tc.get("id") == tool_call_id
                        for tc in fixed_history[j]["tool_calls"]
                    ):
                        found_call = True
                        break
                if found_call:
                    fixed_history.append(msg)
            else:
                fixed_history.append(msg)

            i += 1

        return fixed_history

    async def send_message(
        self,
        response: StandardResponse,
        agent_name: str,
        sub_title: str | None = None,
    ):
        """将 LLM 响应通过 Redis 发送给前端。"""
        content = response.content

        if content is None:
            return

        idx = self.agent_index
        agent_msg: Any = None
        match agent_name:
            case AgentType.CODER:
                agent_msg = CoderMessage(content=content, agent_index=idx)
            case AgentType.WRITER:
                content, _ = split_footnotes(content)
                content = transform_link(self.task_id, content)
                agent_msg = WriterMessage(content=content, sub_title=sub_title, agent_index=idx)
            case AgentType.MODELER:
                agent_msg = ModelerMessage(content=content, agent_index=idx)
            case AgentType.SYSTEM:
                agent_msg = SystemMessage(content=content)
            case AgentType.COORDINATOR:
                agent_msg = CoordinatorMessage(content=content, agent_index=idx)
            case AgentType.SUB_COORDINATOR:
                agent_msg = SubCoordinatorMessage(content=content, agent_index=idx)
            case _:
                raise ValueError(f"不支持的agent类型: {agent_name}")

        await redis_manager.publish_message(self.task_id, agent_msg)


async def simple_chat(model: LLM, history: list) -> str:
    """使用 LLM 进行简单的单轮对话。"""
    response = await model.provider.call(
        messages=history,
        model=model.model,  # type: ignore[arg-type]
        api_key=model.api_key,  # type: ignore[arg-type]
        base_url=model.base_url,
    )
    return response.content or ""
