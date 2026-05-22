"""OpenAI Chat Completions API Provider。"""

from collections.abc import AsyncGenerator
from openai import AsyncOpenAI
from app.core.llm.providers.base import BaseProvider
from app.core.llm.types import StandardResponse, StreamChunk, ToolCall, Usage
from app.utils.log_util import logger


class OpenAIChatProvider(BaseProvider):
    """OpenAI Chat Completions API (/v1/chat/completions) 实现。"""

    async def call(
        self,
        messages: list[dict],
        model: str,
        api_key: str,
        base_url: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
    ) -> StandardResponse:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)

        kwargs: dict = {"model": model, "messages": messages}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if top_p is not None:
            kwargs["top_p"] = top_p
        if tools:
            kwargs["tools"] = tools
            if tool_choice:
                kwargs["tool_choice"] = tool_choice

        response = await client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        message = choice.message

        tool_calls: list[ToolCall] = []
        for tc in message.tool_calls or []:
            tool_calls.append(ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=tc.function.arguments,
            ))

        usage = Usage(
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
        )

        reasoning = getattr(message, "reasoning_content", None)
        return StandardResponse(
            content=message.content,
            reasoning_content=reasoning,
            tool_calls=tool_calls,
            usage=usage,
        )

    async def call_stream(
        self,
        messages: list[dict],
        model: str,
        api_key: str,
        base_url: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)

        kwargs: dict = {"model": model, "messages": messages, "stream": True}
        kwargs["stream_options"] = {"include_usage": True}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if top_p is not None:
            kwargs["top_p"] = top_p
        if tools:
            kwargs["tools"] = tools

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        usage = Usage()
        accumulated_tool_calls: dict[int, dict] = {}

        try:
            stream = await client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta if choice.delta else None
                if delta is None:
                    continue

                # 处理文本增量
                if delta.content:
                    content_parts.append(delta.content)
                    yield StreamChunk(delta=delta.content, is_done=False)

                # 处理 reasoning 增量
                reasoning_delta = getattr(delta, "reasoning_content", None) or ""
                if reasoning_delta:
                    reasoning_parts.append(reasoning_delta)
                    yield StreamChunk(
                        delta="",
                        is_done=False,
                        reasoning_content=reasoning_delta,
                    )

                # 处理 tool_calls 增量
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in accumulated_tool_calls:
                            accumulated_tool_calls[idx] = {
                                "id": tc.id or "",
                                "name": tc.function.name if tc.function else "",
                                "arguments": "",
                            }
                        entry = accumulated_tool_calls[idx]
                        if tc.id:
                            entry["id"] = tc.id
                        if tc.function and tc.function.name:
                            entry["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            entry["arguments"] += tc.function.arguments

                # 处理 usage（仅在最后一个 chunk）
                if chunk.usage:
                    usage = Usage(
                        prompt_tokens=chunk.usage.prompt_tokens or 0,
                        completion_tokens=chunk.usage.completion_tokens or 0,
                    )
        except Exception as e:
            logger.error(f"流式调用出错: {e}")
            raise

        # 构建最终 tool_calls
        tool_calls: list[ToolCall] = []
        for idx in sorted(accumulated_tool_calls.keys()):
            entry = accumulated_tool_calls[idx]
            if entry["id"]:
                tool_calls.append(ToolCall(
                    id=entry["id"],
                    name=entry["name"],
                    arguments=entry["arguments"],
                ))

        full_content = "".join(content_parts)
        full_reasoning = "".join(reasoning_parts)
        yield StreamChunk(
            delta="",
            is_done=True,
            usage=usage,
            tool_calls=tool_calls,
            reasoning_content=full_reasoning or None,
        )
