"""响应数据模型定义，包括消息类型和代码执行结果。"""

from datetime import datetime, timezone
from typing import Literal, Union
from app.schemas.enums import AgentType
from pydantic import BaseModel, Field
from uuid import uuid4


class Message(BaseModel):
    """消息基类。"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    msg_type: str  # system | agent | user | tool | approval
    content: str | None = None


class ToolMessage(Message):
    msg_type: Literal["system", "agent", "user", "tool"] = "tool"  # type: ignore[assignment]
    tool_name: Literal["execute_code", "search_scholar"]
    input: dict | None = None
    output: list | None = None


class SystemMessage(Message):
    msg_type: Literal["system", "agent", "user", "tool"] = "system"  # type: ignore[assignment]
    type: Literal["info", "warning", "success", "error"] = "info"


class UserMessage(Message):
    msg_type: Literal["system", "agent", "user", "tool"] = "user"  # type: ignore[assignment]


class AgentMessage(Message):
    msg_type: Literal["system", "agent", "user", "tool"] = "agent"  # type: ignore[assignment]
    agent_type: AgentType  # CoordinatorAgent | ModelerAgent | CoderAgent | WriterAgent
    agent_index: int | None = None  # 并行组编号（1-based），None 表示全局单例
    stream_state: Literal["streaming", "complete"] | None = None  # streaming=增量内容，complete=最终完整内容
    # 结构化身份字段（多 Agent 协同用）
    agent_instance_id: str | None = None  # 全局唯一实例 ID，如 "q1.coder.r2"
    question_index: int | None = None  # 所属问题编号（1-based）
    race_index: int | None = None  # 竞速编号（1-based），非竞速 Agent 为 None
    phase: str | None = None  # 当前阶段：coordinating|modeling|coding|writing|reviewing
    group_id: str | None = None  # 前端分组用，同组 Agent 共享，如 "q1.coder"
    feedback_kind: str | None = None  # user_checkpoint|auto_quality_check|rework|handoff|final_review


class ModelerMessage(AgentMessage):
    agent_type: AgentType = AgentType.MODELER


class CoordinatorMessage(AgentMessage):
    agent_type: AgentType = AgentType.COORDINATOR


class SubCoordinatorMessage(AgentMessage):
    """子问题组协调者消息，携带组编号。"""
    agent_type: AgentType = AgentType.SUB_COORDINATOR


class CodeExecution(BaseModel):
    """代码执行结果基类。"""
    res_type: Literal["stdout", "stderr", "result", "error"]
    msg: str | None = None


class StdOutModel(CodeExecution):
    res_type: Literal["stdout", "stderr", "result", "error"] = "stdout"  # type: ignore[assignment]


class StdErrModel(CodeExecution):
    res_type: Literal["stdout", "stderr", "result", "error"] = "stderr"  # type: ignore[assignment]


class ResultModel(CodeExecution):
    res_type: Literal["stdout", "stderr", "result", "error"] = "result"  # type: ignore[assignment]
    format: Literal[
        "text",
        "html",
        "markdown",
        "png",
        "jpeg",
        "svg",
        "pdf",
        "latex",
        "json",
        "javascript",
    ]


class ErrorModel(CodeExecution):
    res_type: Literal["stdout", "stderr", "result", "error"] = "error"  # type: ignore[assignment]
    name: str
    value: str
    traceback: str


# 代码执行结果类型
OutputItem = Union[StdOutModel, StdErrModel, ResultModel, ErrorModel]


class ScholarMessage(ToolMessage):
    tool_name: Literal["execute_code", "search_scholar"] = "search_scholar"  # type: ignore[assignment]
    input: dict | None = None  # query
    output: list[str] | None = None  # cites


class InterpreterMessage(ToolMessage):
    tool_name: Literal["execute_code", "search_scholar"] = "execute_code"  # type: ignore[assignment]
    input: dict | None = None  # code
    output: list[OutputItem] | None = None  # code_results
    description: str | None = None  # 代码介绍：阶段、功能、预期结果


# 1. 只带 code
# 2. 只带 code result
class CoderMessage(AgentMessage):
    agent_type: AgentType = AgentType.CODER


class WriterMessage(AgentMessage):
    agent_type: AgentType = AgentType.WRITER
    sub_title: str | None = None


class ApprovalMessage(Message):
    """HIL 审批消息，发送到前端触发审批对话框。"""

    msg_type: Literal["system", "agent", "user", "tool", "approval", "progress"] = "approval"  # type: ignore[assignment]
    checkpoint_id: str = ""
    prompt: dict = Field(default_factory=dict)
    options: list[str] = Field(
        default_factory=lambda: [
            "confirm",
            "edit",
            "regenerate",
            "ask",
            "skip",
            "abort",
        ]
    )
    timeout: int = 300


class ProgressMessage(Message):
    """工作流进度消息，前端用此驱动统一进度条。"""

    msg_type: Literal["system", "agent", "user", "tool", "approval", "progress"] = "progress"  # type: ignore[assignment]
    current: int = 0
    total: int = 0
    percentage: int = 0
    description: str = ""


# 所有可能的消息类型
MessageType = Union[
    SystemMessage,
    UserMessage,
    AgentMessage,
    ToolMessage,
    ScholarMessage,
    InterpreterMessage,
    CoderMessage,
    WriterMessage,
    ModelerMessage,
    CoordinatorMessage,
    SubCoordinatorMessage,
    ProgressMessage,
]
