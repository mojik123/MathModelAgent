"""Redis 管理模块，提供消息发布/订阅和持久化存储。"""

import redis.asyncio as aioredis
from typing import Optional
import json
from pathlib import Path
from app.config.setting import settings
from app.schemas.response import Message
from app.utils.log_util import logger


class RedisManager:
    """Redis 连接管理器，负责消息发布/订阅和任务消息持久化。

    使用连接池复用连接，避免每次操作创建新连接。
    pubsub 通过专用客户端隔离，防止长连接占满主池。
    """

    def __init__(self):
        self.redis_url = settings.REDIS_URL
        self._client: Optional[aioredis.Redis] = None
        self._pubsub_client: Optional[aioredis.Redis] = None
        self._initialized = False
        # 创建消息存储目录
        self.messages_dir = Path("logs/messages")
        self.messages_dir.mkdir(parents=True, exist_ok=True)

    async def _ensure_connected(self) -> None:
        """确保连接池已初始化并可用（仅首次执行 ping）。"""
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
        """获取 Redis 客户端（不重复 ping，仅首次验证）。"""
        await self._ensure_connected()
        return self._client  # type: ignore[return-value]

    async def _get_pubsub_client(self) -> aioredis.Redis:
        """获取专用于 pubsub 的独立客户端，避免长连接占用主池。"""
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
        """设置Redis键值对"""
        client = await self.get_client()
        await client.set(key, value)
        await client.expire(key, 36000)

    async def _save_message_to_file(self, task_id: str, message: Message):
        """将消息保存到文件中，同一任务的消息保存在同一个文件中"""
        try:
            # 确保目录存在
            self.messages_dir.mkdir(exist_ok=True)

            # 使用任务ID作为文件名
            file_path = self.messages_dir / f"{task_id}.json"

            # 读取现有消息（如果文件存在）
            messages = []
            if file_path.exists():
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        messages = json.load(f)
                except (json.JSONDecodeError, Exception):
                    logger.warning(f"消息文件损坏，将重新创建: {file_path}")

            # 添加新消息（流式消息替换同 agent 的上一条流式消息，避免历史重复）
            message_data = message.model_dump()
            msg_type = message_data.get("msg_type")
            stream_state = message_data.get("stream_state")
            if msg_type == "agent" and stream_state == "streaming":
                agent_type = message_data.get("agent_type")
                # 从后往前找同 agent 的流式消息并替换
                replaced = False
                for i in range(len(messages) - 1, -1, -1):
                    existing = messages[i]
                    if (
                        existing.get("msg_type") == "agent"
                        and existing.get("agent_type") == agent_type
                        and existing.get("stream_state") == "streaming"
                    ):
                        messages[i] = message_data
                        replaced = True
                        break
                if not replaced:
                    messages.append(message_data)
            else:
                messages.append(message_data)

            # 保存所有消息到文件
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)

            logger.debug(f"消息已追加到文件: {file_path}")
        except Exception as e:
            logger.error(f"保存消息到文件失败: {str(e)}")
            # 不抛出异常，确保主流程不受影响

    async def publish_message(self, task_id: str, message: Message):
        """发布消息到特定任务的频道并保存到文件"""
        client = await self.get_client()
        channel = f"task:{task_id}:messages"
        try:
            message_json = message.model_dump_json()
            await client.publish(channel, message_json)
            logger.debug(
                f"消息已发布到频道 {channel}:mes_type:{message.msg_type}:msg_content:{message.content}"
            )
            # 保存消息到文件
            await self._save_message_to_file(task_id, message)
        except Exception as e:
            logger.error(f"发布消息失败: {str(e)}")
            raise

    async def subscribe_to_task(self, task_id: str):
        """订阅特定任务的消息（使用独立 pubsub 客户端，避免占满主池）。"""
        pubsub_client = await self._get_pubsub_client()
        pubsub = pubsub_client.pubsub()
        await pubsub.subscribe(f"task:{task_id}:messages")
        return pubsub

    async def close(self):
        """关闭所有 Redis 连接。"""
        if self._client:
            await self._client.close()
            self._client = None
        if self._pubsub_client:
            await self._pubsub_client.close()
            self._pubsub_client = None
        self._initialized = False


redis_manager = RedisManager()
