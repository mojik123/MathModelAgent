"""LLM 响应标准化类型定义。"""

from dataclasses import dataclass, field


@dataclass
class ToolCall:
    """标准化工具调用。"""

    id: str
    name: str
    arguments: str  # JSON string


@dataclass
class Usage:
    """Token 用量。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class StandardResponse:
    """LLM 响应的标准化格式。

    Agent 侧统一使用此格式访问 LLM 结果，不感知底层 API 差异。
    """

    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


@dataclass
class StreamChunk:
    """流式响应的单个数据块。

    Attributes:
        delta: 本次增量文本内容。
        is_done: 是否为最后一个块（流结束）。
        reasoning_content: 推理内容增量（如有）。
        tool_calls: 工具调用列表（仅最后一个块可能携带）。
        usage: Token 用量（仅最后一个块携带）。
    """

    delta: str = ""
    is_done: bool = False
    reasoning_content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
