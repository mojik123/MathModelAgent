"""应用配置模块，基于 pydantic-settings 管理环境变量和全局配置。"""

from enum import Enum

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, SettingsConfigDict
import os
from typing import Annotated, Optional


class ApiType(str, Enum):
    """LLM API 类型。"""
    OPENAI_CHAT = "openai-chat"
    OPENAI_RESPONSES = "openai-responses"
    ANTHROPIC = "anthropic"


def parse_cors(value: str) -> list[str]:
    """将 CORS 配置字符串解析为 URL 列表。

    Args:
        value: 逗号分隔的 URL 字符串，或 "*" 表示允许所有来源。

    Returns:
        解析后的 URL 列表。
    """
    if value == "*":
        return ["*"]
    if "," in value:
        return [url.strip() for url in value.split(",")]
    return [value]


class Settings(BaseSettings):
    """全局应用配置，从环境变量和 .env 文件加载。"""
    ENV: str = "dev"

    COORDINATOR_API_TYPE: Optional[ApiType] = None
    COORDINATOR_API_KEY: Optional[str] = None
    COORDINATOR_MODEL: Optional[str] = None
    COORDINATOR_BASE_URL: Optional[str] = None
    COORDINATOR_MAX_TOKENS: Optional[int] = None
    COORDINATOR_CONTEXT_WINDOW: int = 128000

    MODELER_API_TYPE: Optional[ApiType] = None
    MODELER_API_KEY: Optional[str] = None
    MODELER_MODEL: Optional[str] = None
    MODELER_BASE_URL: Optional[str] = None
    MODELER_MAX_TOKENS: Optional[int] = None
    MODELER_CONTEXT_WINDOW: int = 128000

    CODER_API_TYPE: Optional[ApiType] = None
    CODER_API_KEY: Optional[str] = None
    CODER_MODEL: Optional[str] = None
    CODER_BASE_URL: Optional[str] = None
    CODER_MAX_TOKENS: Optional[int] = None
    CODER_CONTEXT_WINDOW: int = 128000

    WRITER_API_TYPE: Optional[ApiType] = None
    WRITER_API_KEY: Optional[str] = None
    WRITER_MODEL: Optional[str] = None
    WRITER_BASE_URL: Optional[str] = None
    WRITER_MAX_TOKENS: Optional[int] = None
    WRITER_CONTEXT_WINDOW: int = 128000
    WRITER_PARALLELISM: int = 3
    QUESTION_PARALLELISM: int = 4

    # ── Coder 执行配置 ──
    CODE_EXECUTION_TIMEOUT: int = 300  # 单次代码执行最长秒数
    CODER_MAX_RETRIES: int = 6       # Coder 内部最大重试次数
    CODER_MAX_SAME_ERROR: int = 3    # 连续相同错误上限，防止同类错误无限循环
    CODER_ATTEMPT_TIMEOUT: int = 1200  # 单个 Coder attempt 最长秒数，超时视为失败
    # ── 速度与阻塞控制 ──
    IMAGE_DESCRIPTION_ENABLED: bool = False
    IMAGE_DESCRIPTION_BACKGROUND: bool = True
    WRITER_IMAGE_REPAIR_ENABLED: bool = False

    # ── 超时保护 ──
    QUESTION_GROUP_TIMEOUT: int = 1800     # 单个小问组最长秒数
    WRITER_ATTEMPT_TIMEOUT: int = 900     # 单个 Writer 最长秒数
    CODER_MAX_TOTAL_STEPS: int = 35       # Coder 最大总执行步数

    # ── 产物检查分级 ──
    ARTIFACT_STRICT_FATAL: bool = False   # 非核心产物问题不直接判死

    # 兼容旧 .env 里的 MAX_RETRIES，下轮彻底删除
    MAX_RETRIES: int | None = None
    E2B_API_KEY: Optional[str] = None
    LOG_LEVEL: str = "DEBUG"
    DEBUG: bool = True
    REDIS_URL: str = "redis://redis:6379/0"
    REDIS_MAX_CONNECTIONS: int = 10
    CORS_ALLOW_ORIGINS: Annotated[list[str] | str, BeforeValidator(parse_cors)] = "*"
    SERVER_HOST: str = "http://localhost:8000"
    DEEPSEEK_MODEL: Optional[str] = None
    DEEPSEEK_BASE_URL: Optional[str] = None
    OPENALEX_EMAIL: Optional[str] = None
    OPENALEX_API_KEY: Optional[str] = None

    # Web Search 配置（Tavily API）
    TAVILY_API_KEY: Optional[str] = None
    SEARCH_CACHE_TTL: int = 86400  # 搜索缓存过期时间（秒）
    SEARCH_ENABLED: bool = False

    # RAG 知识库配置
    RAG_ENABLED: bool = False
    RAG_DB_PATH: str = "data/chromadb"
    RAG_TOP_K: int = 5
    RAG_EMBEDDING_MODEL: str = "BAAI/bge-m3"
    RAG_RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"

    HIL_TIMEOUT: int = 300  # 审批超时时间（秒），保留兼容

    model_config = SettingsConfigDict(
        env_file=".env.dev",
        env_file_encoding="utf-8",
        extra="allow",
    )

    @classmethod
    def from_env(cls, env: str | None = None):
        """根据环境名称加载对应配置。

        Args:
            env: 环境名称（如 dev、prod），默认从 ENV 环境变量获取。
        """
        env = env or os.getenv("ENV", "dev")
        env_file = f".env.{env.lower()}"
        return cls(_env_file=env_file, _env_file_encoding="utf-8")  # type: ignore[call-arg]


settings = Settings()
