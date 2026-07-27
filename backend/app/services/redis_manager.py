"""Redis 管理模块，提供消息发布/订阅和持久化存储。"""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Optional
from uuid import uuid4

import redis.asyncio as aioredis

from app.config.setting import settings
from app.schemas.enums import AgentType
from app.schemas.response import AgentMessage, Message
from app.utils.log_util import logger


class RedisManager:
    """Redis 连接管理器，负责消息发布/订阅和任务消息持久化。"""

    def __init__(self):
        self.redis_url = settings.REDIS_URL
        self._client: Optional[aioredis.Redis] = None
        self._pubsub_client: Optional[aioredis.Redis] = None
        self._initialized = False
        self.messages_dir = Path("logs/messages")
        self.messages_dir.mkdir(parents=True, exist_ok=True)
        self._message_file_locks: dict[str, asyncio.Lock] = {}

    async def _ensure_connected(self) -> None:
        if self._initialized:
            return
        if self._client is None:
            self._client = aioredis.Redis.from_url(
                self.redis_url,
                decode_responses=True,
                max_connections=max(20, settings.REDIS_MAX_CONNECTIONS),
                socket_connect_timeout=5,
                socket_keepalive=True,
                health_check_interval=30,
                retry_on_timeout=True,
            )
        await self._client.ping()
        logger.info(f"Redis 连接池已就绪: {self.redis_url}")
        self._initialized = True

    async def get_client(self) -> aioredis.Redis:
        await self._ensure_connected()
        return self._client  # type: ignore[return-value]

    async def _get_pubsub_client(self) -> aioredis.Redis:
        if self._pubsub_client is None:
            self._pubsub_client = aioredis.Redis.from_url(
                self.redis_url,
                decode_responses=True,
                max_connections=max(10, settings.REDIS_MAX_CONNECTIONS // 4),
                socket_connect_timeout=5,
                socket_keepalive=True,
                health_check_interval=30,
                retry_on_timeout=True,
            )
        return self._pubsub_client

    async def set(self, key: str, value: str):
        client = await self.get_client()
        await client.set(key, value)
        await client.expire(key, 36000)

    def _infer_question_index(self, message: Message) -> int | None:
        if getattr(message, "question_index", None) is not None:
            return message.question_index
        # 全局 Coordinator / Modeler 的结构化结果会包含 ques1/ques2 等 JSON 键，
        # 不能把这些键当成当前消息所属的子问题。真正的分组消息会显式携带
        # question_index，并已在上方直接返回。
        if isinstance(message, AgentMessage) and message.agent_type in {
            AgentType.COORDINATOR,
            AgentType.MODELER,
        }:
            return None
        text = str(message.content or "")
        description = getattr(message, "description", None)
        if description:
            text += "\n" + str(description)
        for pattern in (
            r"\[组#(\d+)\]",
            r"子问题组#(\d+)",
            r"Group#(\d+)",
            r"q(\d+)\.",
            r"ques(\d+)",
        ):
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except (TypeError, ValueError):
                    return None
        return None

    def _infer_agent_instance_id(
        self, message: Message, question_index: int | None
    ) -> str | None:
        if getattr(message, "agent_instance_id", None):
            return message.agent_instance_id
        if isinstance(message, AgentMessage):
            prefix = f"q{question_index}" if question_index is not None else ""
            if message.agent_type == AgentType.COORDINATOR:
                return "coordinator"
            if message.agent_type == AgentType.SUB_COORDINATOR:
                return f"{prefix}.sub_coordinator" if prefix else "sub_coordinator"
            if message.agent_type == AgentType.MODELER:
                return f"{prefix}.modeler" if prefix else "modeler"
            if message.agent_type == AgentType.CODER:
                return f"{prefix}.coder.main" if prefix else "coder"
            if message.agent_type == AgentType.WRITER:
                return f"{prefix}.writer" if prefix else "writer"
        text = str(message.content or "")
        description = getattr(message, "description", None)
        if description:
            text += "\n" + str(description)
        if question_index is None:
            if "Coordinator" in text or "协调者" in text or "问题拆解" in text:
                return "coordinator"
            if "Modeler" in text or "建模手" in text or "建模方案" in text:
                return "modeler"
            if "Writer" in text or "论文手" in text:
                return "writer"
            if "Coder" in text or "代码手" in text:
                return "coder"
            return None
        prefix = f"q{question_index}"
        if "SubCoordinator" in text or "子问题组" in text:
            return f"{prefix}.sub_coordinator"
        if "Writer" in text or "论文手" in text or "写作" in text:
            return f"{prefix}.writer"
        if "备用" in text or "b1" in text or "轻量修复" in text:
            return f"{prefix}.coder.b1"
        if (
            "Coder" in text
            or "代码手" in text
            or "execute_code" in text
            or message.msg_type == "tool"
        ):
            return f"{prefix}.coder.main"
        if "Modeler" in text or "建模手" in text or "模型" in text:
            return f"{prefix}.modeler"
        return None

    def _infer_phase(
        self, message: Message, agent_instance_id: str | None
    ) -> str | None:
        if getattr(message, "phase", None):
            return message.phase
        text = str(message.content or "")
        if (
            "已停止" in text
            or "超时" in text
            or getattr(message, "type", "") == "error"
        ):
            return "stopped"
        if not agent_instance_id:
            return None
        if ".sub_coordinator" in agent_instance_id:
            return "coordinating"
        if ".modeler" in agent_instance_id:
            return "modeling"
        if ".coder" in agent_instance_id:
            return "coding"
        if ".writer" in agent_instance_id:
            return "writing"
        if agent_instance_id == "coordinator":
            return "planning"
        if agent_instance_id == "sub_coordinator":
            return "coordinating"
        if agent_instance_id == "modeler":
            return "modeling"
        if agent_instance_id == "coder":
            return "coding"
        if agent_instance_id == "writer":
            return "writing"
        return None

    def _enrich_message_identity(self, message: Message) -> Message:
        try:
            question_index = self._infer_question_index(message)
            if question_index is not None:
                message.question_index = question_index
            agent_instance_id = self._infer_agent_instance_id(message, question_index)
            if agent_instance_id:
                message.agent_instance_id = agent_instance_id
                message.group_id = agent_instance_id
            phase = self._infer_phase(message, agent_instance_id)
            if phase:
                message.phase = phase
        except Exception as exc:
            logger.warning(f"消息身份字段补齐失败，不影响发布: {exc}")
        return message

    async def _save_message_to_file(self, task_id: str, message: Message):
        """原子保存一条完整消息，避免并行 Agent 写坏 JSON。"""
        lock = self._message_file_locks.setdefault(task_id, asyncio.Lock())
        temp_path: Path | None = None
        try:
            async with lock:
                self.messages_dir.mkdir(parents=True, exist_ok=True)
                file_path = self.messages_dir / f"{task_id}.json"
                messages = []
                if file_path.exists():
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            messages = json.load(f)
                    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
                        logger.warning(
                            f"消息文件无法读取，将从下一条完整消息重建: "
                            f"{file_path} ({type(exc).__name__})"
                        )

                message_data = message.model_dump()
                msg_type = message_data.get("msg_type")
                stream_state = message_data.get("stream_state")
                if msg_type == "agent" and not stream_state:
                    message_data["stream_state"] = "complete"

                # streaming 消息只通过 Redis 广播，正常情况下不会进入持久化。
                # 兼容旧文件：若残留同实例的 streaming 占位，则以完整消息替换。
                replaced = False
                if msg_type == "agent":
                    agent_instance_id = message_data.get("agent_instance_id")
                    agent_type = message_data.get("agent_type")
                    for i in range(len(messages) - 1, -1, -1):
                        existing = messages[i]
                        same_instance = (
                            agent_instance_id
                            and existing.get("agent_instance_id") == agent_instance_id
                        )
                        same_legacy_type = (
                            not agent_instance_id
                            and existing.get("agent_type") == agent_type
                        )
                        if (
                            existing.get("msg_type") == "agent"
                            and existing.get("stream_state") == "streaming"
                            and (same_instance or same_legacy_type)
                        ):
                            messages[i] = message_data
                            replaced = True
                            break
                if not replaced:
                    messages.append(message_data)

                temp_path = file_path.with_name(f".{file_path.name}.{uuid4().hex}.tmp")
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(messages, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, file_path)
                temp_path = None
                logger.debug(f"完整消息已原子保存: {file_path}, count={len(messages)}")
        except Exception as e:
            logger.error(f"保存消息到文件失败: {str(e)}")
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    async def publish_message(self, task_id: str, message: Message):
        message = self._enrich_message_identity(message)
        client = await self.get_client()
        channel = f"task:{task_id}:messages"
        try:
            message_json = message.model_dump_json()
            await client.publish(channel, message_json)
            logger.debug(
                f"消息已发布: channel={channel}, type={message.msg_type}, "
                f"stream_state={getattr(message, 'stream_state', None)}, "
                f"content_len={len(str(message.content or ''))}"
            )
            is_streaming = (
                message.msg_type == "agent"
                and getattr(message, "stream_state", None) == "streaming"
            )
            if not is_streaming:
                await self._save_message_to_file(task_id, message)
        except Exception as e:
            logger.error(f"发布消息失败: {str(e)}")
            raise

    async def subscribe_to_task(self, task_id: str):
        pubsub_client = await self._get_pubsub_client()
        pubsub = pubsub_client.pubsub()
        await pubsub.subscribe(f"task:{task_id}:messages")
        return pubsub

    async def close(self):
        if self._client:
            await self._client.close()
            self._client = None
        if self._pubsub_client:
            await self._pubsub_client.close()
            self._pubsub_client = None
        self._initialized = False


redis_manager = RedisManager()
