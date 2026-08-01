"""运行时收敛、防重试风暴与消息持久化测试。"""

import asyncio
import json
import sys
import types
from unittest.mock import AsyncMock, patch

import pytest

# Codex 的轻量测试运行时不包含 Redis 客户端；本文件只验证持久化逻辑，
# 不建立真实连接，因此在依赖缺失时提供最小导入桩。
try:
    import redis.asyncio  # type: ignore[import-untyped]  # noqa: F401
except ModuleNotFoundError:
    redis_module = types.ModuleType("redis")
    redis_asyncio_module = types.ModuleType("redis.asyncio")

    class _RedisStub:
        """仅用于满足 RedisManager 类型和导入要求。"""

        @classmethod
        def from_url(cls, *_args, **_kwargs):
            return cls()

    redis_asyncio_module.Redis = _RedisStub
    redis_module.asyncio = redis_asyncio_module
    sys.modules["redis"] = redis_module
    sys.modules["redis.asyncio"] = redis_asyncio_module

try:
    import openai  # type: ignore[import-untyped]  # noqa: F401
except ModuleNotFoundError:
    openai_module = types.ModuleType("openai")
    openai_module.AsyncOpenAI = object
    sys.modules["openai"] = openai_module

try:
    import anthropic  # type: ignore[import-untyped]  # noqa: F401
except ModuleNotFoundError:
    anthropic_module = types.ModuleType("anthropic")
    anthropic_module.AsyncAnthropic = object
    sys.modules["anthropic"] = anthropic_module

from app.core.llm.llm import LLM, LLMRetryExhaustedError, NonRetryableLLMError
from app.core.llm.types import StandardResponse
from app.schemas.enums import AgentType
from app.schemas.response import (
    CoordinatorMessage,
    ModelerMessage,
    SystemMessage,
    WriterMessage,
)
from app.services.redis_manager import RedisManager


class _StatusError(RuntimeError):
    """携带 HTTP 状态码的测试异常。"""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class _FailingProvider:
    """记录调用次数并始终失败的 Provider。"""

    def __init__(self, exc: Exception):
        self.exc = exc
        self.calls = 0

    async def call(self, **_kwargs) -> StandardResponse:
        self.calls += 1
        raise self.exc


class _TransientProvider:
    """前两次失败、第三次成功的 Provider。"""

    def __init__(self):
        self.calls = 0

    async def call(self, **_kwargs) -> StandardResponse:
        self.calls += 1
        if self.calls < 3:
            raise _StatusError(503, "temporary unavailable")
        return StandardResponse(content="ok")


class _AlwaysTransientProvider:
    """始终返回临时错误的 Provider。"""

    def __init__(self):
        self.calls = 0

    async def call(self, **_kwargs) -> StandardResponse:
        self.calls += 1
        raise _StatusError(503, "temporary unavailable")


class _SuccessfulProvider:
    """始终成功并记录调用次数的 Provider。"""

    def __init__(self):
        self.calls = 0

    async def call(self, **_kwargs) -> StandardResponse:
        self.calls += 1
        return StandardResponse(content="ok")


def _llm(provider) -> LLM:
    model = LLM(
        api_type=None,
        api_key="test-key",
        model="test-model",
        task_id="test-task",
    )
    model.provider = provider
    model.send_message = AsyncMock()
    return model


def test_non_retryable_balance_error_stops_after_one_attempt() -> None:
    """余额错误必须立即失败，不能进入重试风暴。"""
    provider = _FailingProvider(_StatusError(402, "Insufficient Balance"))
    model = _llm(provider)

    with pytest.raises(NonRetryableLLMError, match="账户余额"):
        asyncio.run(model.chat(max_retries=5))

    assert provider.calls == 1


def test_transient_error_uses_bounded_async_retries() -> None:
    """临时错误可重试，但必须受最大次数约束且使用异步等待。"""
    provider = _TransientProvider()
    model = _llm(provider)

    with patch("app.core.llm.llm.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        response = asyncio.run(model.chat(max_retries=3))

    assert response.content == "ok"
    assert provider.calls == 3
    assert sleep_mock.await_count == 2


def test_exhausted_transient_error_is_marked_fatal_for_current_agent() -> None:
    """耗尽 LLM 重试预算后必须上抛，不能被 Coder 再套一层循环。"""
    provider = _AlwaysTransientProvider()
    model = _llm(provider)

    with (
        patch("app.core.llm.llm.asyncio.sleep", new=AsyncMock()),
        pytest.raises(LLMRetryExhaustedError, match="连续失败 3 次"),
    ):
        asyncio.run(model.chat(max_retries=3))

    assert provider.calls == 3


def test_hidden_llm_call_does_not_publish_task_message() -> None:
    """内部判定调用应复用 LLM，但不能生成无效 Agent 消息。"""
    provider = _SuccessfulProvider()
    model = _llm(provider)

    response = asyncio.run(
        model.chat(
            agent_name="CoordinatorRepeatErrorJudge",
            publish_response=False,
        )
    )

    assert response.content == "ok"
    assert provider.calls == 1
    model.send_message.assert_not_awaited()


def test_message_publish_failure_does_not_repeat_model_request() -> None:
    """模型已成功后即使消息发布失败，也不能重新请求并重复计费。"""
    provider = _SuccessfulProvider()
    model = _llm(provider)
    model.send_message = AsyncMock(side_effect=ValueError("unsupported agent"))

    with pytest.raises(ValueError, match="unsupported agent"):
        asyncio.run(model.chat(max_retries=3))

    assert provider.calls == 1


def test_concurrent_message_writes_remain_valid_json(tmp_path) -> None:
    """并行 Agent 完成消息必须通过锁和原子替换保持 JSON 完整。"""
    manager = RedisManager()
    manager.messages_dir = tmp_path

    async def _write_all() -> None:
        await asyncio.gather(
            *[
                manager._save_message_to_file(
                    "task-1",
                    SystemMessage(content=f"message-{index}"),
                )
                for index in range(30)
            ]
        )

    asyncio.run(_write_all())
    messages = json.loads((tmp_path / "task-1.json").read_text(encoding="utf-8"))

    assert len(messages) == 30
    assert {item["content"] for item in messages} == {
        f"message-{index}" for index in range(30)
    }


def test_streaming_message_is_broadcast_but_not_persisted() -> None:
    """流式片段只广播，避免每个 token 都重写历史文件。"""
    manager = RedisManager()
    fake_client = AsyncMock()
    manager.get_client = AsyncMock(return_value=fake_client)
    manager._save_message_to_file = AsyncMock()
    message = WriterMessage(
        content="partial",
        agent_type=AgentType.WRITER,
        stream_state="streaming",
    )

    asyncio.run(manager.publish_message("task-1", message))

    fake_client.publish.assert_awaited_once()
    manager._save_message_to_file.assert_not_awaited()


def test_coordinator_json_is_not_misclassified_as_question_modeler() -> None:
    """Coordinator 的 ques1/模型字段不能凭文本误生成建模阶段。"""
    manager = RedisManager()
    message = CoordinatorMessage(
        content='{"ques_count": 1, "ques1": "请建立数学模型并求解"}'
    )

    enriched = manager._enrich_message_identity(message)

    assert enriched.agent_instance_id == "coordinator"
    assert enriched.group_id == "coordinator"
    assert enriched.question_index is None
    assert enriched.phase == "planning"


def test_global_modeler_message_gets_modeling_identity() -> None:
    """全局建模手消息应稳定归入建模阶段。"""
    manager = RedisManager()
    message = ModelerMessage(content='{"ques_count": 1, "ques1": "整体建模方案"}')

    enriched = manager._enrich_message_identity(message)

    assert enriched.agent_instance_id == "modeler"
    assert enriched.group_id == "modeler"
    assert enriched.question_index is None
    assert enriched.phase == "modeling"
