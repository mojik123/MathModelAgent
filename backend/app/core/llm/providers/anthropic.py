"""Anthropic Messages API Provider。"""

import json as _json
from collections.abc import AsyncGenerator

from anthropic import AsyncAnthropic

from app.core.llm.providers.base import BaseProvider
from app.core.llm.types import StandardResponse, StreamChunk, ToolCall, Usage
from app.utils.log_util import logger


class AnthropicProvider(BaseProvider):
    """Anthropic Messages API (/v1/messages) 实现。"""

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
        client = AsyncAnthropic(api_key=api_key, base_url=base_url)

        system_prompt, anthropic_messages = self._convert_messages(messages)

        kwargs: dict = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens or 4096,
            "thinking": {"type": "disabled"},
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if top_p is not None:
            kwargs["top_p"] = top_p
        if tools:
            kwargs["tools"] = self._convert_tools(tools)
            if tool_choice:
                kwargs["tool_choice"] = self._convert_tool_choice(tool_choice)

        response = await client.messages.create(**kwargs)

        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=_json.dumps(block.input),
                ))

        content = "".join(content_parts) if content_parts else None

        usage = Usage(
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
        )

        return StandardResponse(content=content, tool_calls=tool_calls, usage=usage)

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
        """流式调用 Anthropic Messages API，逐块返回文本增量。"""
        client = AsyncAnthropic(api_key=api_key, base_url=base_url)

        system_prompt, anthropic_messages = self._convert_messages(messages)

        kwargs: dict = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens or 4096,
            "thinking": {"type": "disabled"},
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if top_p is not None:
            kwargs["top_p"] = top_p
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        usage = Usage()

        try:
            async with client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            text = event.delta.text
                            content_parts.append(text)
                            yield StreamChunk(delta=text, is_done=False)
                        elif event.delta.type == "input_json_delta":
                            # 工具调用参数增量，暂存
                            pass

                    elif event.type == "content_block_start":
                        if event.content_block.type == "tool_use":
                            tool_calls.append(ToolCall(
                                id=event.content_block.id,
                                name=event.content_block.name,
                                arguments="",
                            ))

                    elif event.type == "message_delta":
                        if event.usage:
                            usage = Usage(
                                prompt_tokens=event.usage.input_tokens,
                                completion_tokens=event.usage.output_tokens,
                            )

                # 获取最终消息以提取完整工具调用参数
                final_message = await stream.get_final_message()
                for block in final_message.content:
                    if block.type == "tool_use":
                        # 更新对应的 tool_call 参数
                        for tc in tool_calls:
                            if tc.id == block.id:
                                tc.arguments = _json.dumps(block.input)
                                break

                # 重建 usage（优先使用 final_message 中的）
                if final_message.usage:
                    usage = Usage(
                        prompt_tokens=final_message.usage.input_tokens,
                        completion_tokens=final_message.usage.output_tokens,
                    )

        except Exception as e:
            logger.error(f"Anthropic 流式调用失败: {e}")
            # 退化为非流式调用
            result = await self.call(
                messages=messages,
                model=model,
                api_key=api_key,
                base_url=base_url,
                tools=tools,
                max_tokens=max_tokens,
                top_p=top_p,
            )
            yield StreamChunk(
                delta=result.content or "",
                is_done=True,
                usage=result.usage,
                reasoning_content=result.reasoning_content,
                tool_calls=result.tool_calls,
            )
            return

        yield StreamChunk(
            delta="",
            is_done=True,
            usage=usage,
            tool_calls=tool_calls if tool_calls else None,
        )

    def _convert_messages(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        """将 OpenAI 格式 messages 转为 Anthropic 格式。

        处理 thinking 块：若 content 已是 Anthropic block 列表格式，
        保留 thinking 块以确保符合 Anthropic API 要求。
        """
        system_prompt = None
        converted: list[dict] = []

        for msg in messages:
            role = msg.get("role", "user")

            if role == "system" or role == "developer":
                if system_prompt is None:
                    system_prompt = msg.get("content", "")
                else:
                    system_prompt = system_prompt + "\n\n" + msg.get("content", "")
                continue

            if role == "assistant":
                content = msg.get("content")

                # 如果 content 已经是 Anthropic block 列表格式，保留 thinking 块
                if isinstance(content, list):
                    filtered_blocks = [
                        b for b in content
                        if b.get("type") in ("text", "tool_use", "thinking")
                    ]
                    converted.append({"role": "assistant", "content": filtered_blocks})
                    continue

                # OpenAI 格式：从 tool_calls 重建 Anthropic content blocks
                if "tool_calls" in msg and msg["tool_calls"]:
                    content_blocks: list[dict] = []
                    if content and isinstance(content, str) and content.strip():
                        content_blocks.append({"type": "text", "text": content})
                    for tc in msg["tool_calls"]:
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "input": _json.loads(tc["function"]["arguments"])
                            if isinstance(tc["function"]["arguments"], str)
                            else tc["function"]["arguments"],
                        })
                    converted.append({"role": "assistant", "content": content_blocks})
                    continue

                # 纯文本 assistant 消息，去除 Anthropic 不识别的字段
                converted.append({
                    "role": "assistant",
                    "content": content if isinstance(content, str) else "",
                })

            elif role == "tool":
                converted.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": msg.get("content", ""),
                    }],
                })
            else:
                # user 消息，确保 content 是纯字符串
                val = msg.get("content", "")
                converted.append({
                    "role": role,
                    "content": val if isinstance(val, str) else "",
                })

        return system_prompt, converted

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """将工具定义转为 Anthropic 格式。

        兼容两种输入：
        - OpenAI 格式：{"type": "function", "function": {"name": ..., "parameters": ...}}
        - 已是 Anthropic 格式：{"name": ..., "input_schema": ...}
        """
        converted = []
        for tool in tools:
            if tool.get("type") == "function":
                # OpenAI 格式 → 转换
                func = tool["function"]
                converted.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {}),
                })
            elif "name" in tool and "input_schema" in tool:
                # 已是 Anthropic 格式 → 直接透传，避免被误过滤
                converted.append(tool)
        return converted

    def _convert_tool_choice(self, tool_choice: str) -> dict:
        """转换 tool_choice 为 Anthropic 格式。"""
        if tool_choice == "auto":
            return {"type": "auto"}
        if tool_choice == "none":
            return {"type": "none"}
        if tool_choice == "required":
            return {"type": "any"}
        return {"type": "auto"}
