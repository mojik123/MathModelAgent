"""Redis 管理模块，提供消息发布/订阅和持久化存储。"""

import redis.asyncio as aioredis
from typing import Optional
import json
import re
from pathlib import Path
from app.config.setting import settings
from app.schemas.response import Message
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
        text = str(message.content or "")
        description = getattr(message, "description", None)
        if description:
            text += "\n" + str(description)
        for pattern in (r"\[组#(\d+)\]", r"子问题组#(\d+)", r"Group#(\d+)", r"q(\d+)\.", r"ques(\d+)"):
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except (TypeError, ValueError):
                    return None
        return None

    def _infer_agent_instance_id(self, message: Message, question_index: int | None) -> str | None:
        if getattr(message, "agent_instance_id", None):
            return message.agent_instance_id
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
        if "Coder" in text or "代码手" in text or "execute_code" in text or message.msg_type == "tool":
            return f"{prefix}.coder.main"
        if "Modeler" in text or "建模手" in text or "模型" in text:
            return f"{prefix}.modeler"
        return None

    def _infer_phase(self, message: Message, agent_instance_id: str | None) -> str | None:
        if getattr(message, "phase", None):
            return message.phase
        text = str(message.content or "")
        if "已停止" in text or "超时" in text or getattr(message, "type", "") == "error":
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
        try:
            self.messages_dir.mkdir(exist_ok=True)
            file_path = self.messages_dir / f"{task_id}.json"
            messages = []
            if file_path.exists():
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        messages = json.load(f)
                except (json.JSONDecodeError, Exception):
                    logger.warning(f"消息文件损坏，将重新创建: {file_path}")
            message_data = message.model_dump()
            msg_type = message_data.get("msg_type")
            stream_state = message_data.get("stream_state")
            if msg_type == "agent" and stream_state == "streaming":
                agent_instance_id = message_data.get("agent_instance_id")
                agent_type = message_data.get("agent_type")
                replaced = False
                for i in range(len(messages) - 1, -1, -1):
                    existing = messages[i]
                    same_instance = agent_instance_id and existing.get("agent_instance_id") == agent_instance_id
                    same_legacy_type = not agent_instance_id and existing.get("agent_type") == agent_type
                    if existing.get("msg_type") == "agent" and existing.get("stream_state") == "streaming" and (same_instance or same_legacy_type):
                        messages[i] = message_data
                        replaced = True
                        break
                if not replaced:
                    messages.append(message_data)
            else:
                messages.append(message_data)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
            logger.debug(f"消息已追加到文件: {file_path}")
        except Exception as e:
            logger.error(f"保存消息到文件失败: {str(e)}")

    async def publish_message(self, task_id: str, message: Message):
        message = self._enrich_message_identity(message)
        client = await self.get_client()
        channel = f"task:{task_id}:messages"
        try:
            message_json = message.model_dump_json()
            await client.publish(channel, message_json)
            logger.debug(
                f"消息已发布到频道 {channel}:mes_type:{message.msg_type}:msg_content:{message.content}"
            )
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
