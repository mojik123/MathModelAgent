"""Agent 间通信数据模型定义。"""

from pydantic import BaseModel, field_validator
from typing import Any


class CoordinatorToModeler(BaseModel):
    """协调者传递给建模手的数据结构。"""
    questions: dict
    ques_count: int


class ModelerToCoder(BaseModel):
    """建模手传递给代码手的数据结构。"""
    questions_solution: dict[str, str]


class CoderToWriter(BaseModel):
    """代码手传递给写作手的数据结构。"""
    code_response: str | None = None
    code_output: str | None = None
    created_images: list[str] | None = None


class WriterResponse(BaseModel):
    """写作手的响应数据结构。"""
    response_content: Any
    footnotes: list[tuple[str, str]] | None = None

    @field_validator("footnotes", mode="before")
    @classmethod
    def normalize_footnotes(cls, value: Any) -> list[tuple[str, str]] | None:
        """兼容 LLM/旧流程返回的脚注异常格式。

        WriterResponse 的 footnotes 语义上是脚注列表，但实际运行中写作手
        偶尔会返回 {}、{"a": "b"} 或字符串列表。这里统一归一化，避免正文
        已经生成完成后因为脚注字段类型不匹配导致整个任务失败。
        """
        if value is None:
            return None
        if value == {}:
            return []
        if isinstance(value, dict):
            return [(str(k), str(v)) for k, v in value.items()]
        if isinstance(value, list):
            normalized: list[tuple[str, str]] = []
            for item in value:
                if isinstance(item, tuple) and len(item) == 2:
                    normalized.append((str(item[0]), str(item[1])))
                elif isinstance(item, list) and len(item) == 2:
                    normalized.append((str(item[0]), str(item[1])))
                elif isinstance(item, dict):
                    key = item.get("key") or item.get("id") or item.get("label") or ""
                    text = item.get("text") or item.get("content") or item.get("value") or ""
                    if key or text:
                        normalized.append((str(key), str(text)))
                elif item is not None:
                    normalized.append(("", str(item)))
            return normalized
        if isinstance(value, str):
            stripped = value.strip()
            return [] if not stripped else [("", stripped)]
        return []
