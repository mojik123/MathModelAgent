"""File management routes for task files, paper preview, PDF, and image revision."""

import hashlib
import json
import os
import re
import subprocess
import textwrap
import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from icecream import ic  # type: ignore[import-unresolved]
from pydantic import BaseModel

from app.config.setting import settings
from app.core.llm.llm import LLM, simple_chat
from app.core.prompts.image_revision import get_image_revision_prompt
from app.schemas.response import SystemMessage, ProgressMessage
from app.schemas.enums import AgentType
from app.services.redis_manager import redis_manager
from app.core.prompts.text_revision import get_text_revision_prompt
from app.tools.local_interpreter import LocalCodeInterpreter
from app.tools.notebook_serializer import NotebookSerializer
from app.utils.common_utils import get_current_files, get_work_dir, md_2_pdf
from app.utils.image_code_index import (
    extract_saved_images,
    get_image_code_entry,
    get_notebook_code_cells,
    normalize_image_name,
    update_image_code_index,
    update_image_metadata,
)
from app.utils.image_constants import IMAGE_EXTENSION_RE_FRAGMENT
from app.utils.log_util import logger

router = APIRouter()


async def _publish_revision_step(
    task_id: str,
    *,
    title: str,
    detail: str = "",
    current: int = 0,
    total: int = 0,
    msg_type: str = "info",
) -> None:
    """向前端发布局部 AI 修订任务的进度反馈。"""
    content = title if not detail else f"{title}\n{detail}"

    await redis_manager.publish_message(
        task_id,
        SystemMessage(
            content=content,
            type=msg_type,
        ),
    )

    # 局部修订不发 ProgressMessage，避免干扰主任务 100% 进度条
    # if total > 0:
    #     percentage = round(current / total * 100)
    #     await redis_manager.publish_message(
    #         task_id,
    #         ProgressMessage(
    #             current=current,
    #             total=total,
    #             percentage=percentage,
    #             description=title,
    #         ),
    #     )


_IMAGE_REVISION_COMPAT_CODE = r"""
import builtins as _mma_builtins

if not hasattr(_mma_builtins, "_mma_original_sorted"):
    _mma_builtins._mma_original_sorted = _mma_builtins.sorted

def _mma_safe_sorted(iterable, *args, **kwargs):
    try:
        return _mma_builtins._mma_original_sorted(iterable, *args, **kwargs)
    except TypeError as exc:
        message = str(exc)
        if "not supported between instances" not in message or "key" in kwargs:
            raise
        fallback_kwargs = dict(kwargs)
        def _mma_sort_key(value):
            type_name = type(value).__name__
            is_missing = value is None or type_name in {"NAType", "NaTType"}
            try:
                is_missing = is_missing or bool(value != value)
            except Exception:
                pass
            return (is_missing, str(type(value)), "" if value is None else str(value))
        fallback_kwargs["key"] = _mma_sort_key
        return _mma_builtins._mma_original_sorted(iterable, *args, **fallback_kwargs)

_mma_builtins.sorted = _mma_safe_sorted
"""


class PaperSaveRequest(BaseModel):
    task_id: str
    content: str


class ImageRevisionRequest(BaseModel):
    task_id: str
    filename: str
    instruction: str


class ImageRevisionChatRequest(BaseModel):
    task_id: str
    filename: str
    instruction: str
    title: str | None = None
    description: str | None = None
    conversation_history: list[dict] | None = None


class ImageRevisionChatResponse(BaseModel):
    success: bool
    status: str = "success"
    message: str = ""
    analysis_text: str
    revised_code: str | None = None
    updated_alt_text: str | None = None
    updated_caption: str | None = None
    paper_updated: bool = False
    caption_updated: bool = False
    render_success: bool = False
    render_message: str | None = None
    image_url: str | None = None
    code_found: bool = False


class TextRevisionChatRequest(BaseModel):
    task_id: str
    instruction: str
    selected_text: str
    context: str | None = None
    conversation_history: list[dict] | None = None


class TextRevisionChatResponse(BaseModel):
    success: bool
    status: str = "success"
    message: str = ""
    revised_text: str | None = None
    updated_paper: str | None = None
    paper_updated: bool = False
    revision_scope: str = "selection"
    applied: bool = False
    validation_issues: list[str] | None = None


class ImageCodeResponse(BaseModel):
    found: bool
    filename: str
    cell_index: int | None = None
    code: str | None = None
    section: str | None = None
    description: str | None = None
    alt_text: str | None = None
    caption: str | None = None


@router.get("/download_url")
async def get_download_url(task_id: str, filename: str):
    return {"download_url": f"http://localhost:8000/static/{task_id}/{filename}"}


@router.get("/download_all_url")
async def get_download_all_url(task_id: str):
    return {"download_url": f"http://localhost:8000/static/{task_id}/all.zip"}


@router.get("/files")
async def get_files(task_id: str):
    work_dir = get_work_dir(task_id)
    files = get_current_files(work_dir, "all")
    return [{"filename": item, "file_type": item.split(".")[-1]} for item in files]


@router.get("/image_code")
async def get_image_code(task_id: str, filename: str) -> ImageCodeResponse:
    work_dir = get_work_dir(task_id)
    image_name = normalize_image_name(filename)
    entry = get_image_code_entry(work_dir, image_name)
    if not entry:
        return ImageCodeResponse(found=False, filename=image_name)
    return ImageCodeResponse(
        found=True,
        filename=image_name,
        cell_index=entry.get("cell_index"),
        code=entry.get("code"),
        section=entry.get("section"),
        description=entry.get("description"),
        alt_text=entry.get("alt_text"),
        caption=entry.get("caption"),
    )


@router.get("/paper")
async def get_paper(task_id: str):
    work_dir = get_work_dir(task_id)
    md_path = os.path.join(work_dir, "res.md")
    if not os.path.exists(md_path):
        return {"content": ""}

    with open(md_path, "r", encoding="utf-8") as f:
        return {"content": f.read()}


@router.post("/paper")
async def save_paper(payload: PaperSaveRequest):
    work_dir = get_work_dir(payload.task_id)
    md_path = os.path.join(work_dir, "res.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(payload.content)
    return {"success": True}


@router.post("/compile_pdf")
async def compile_pdf(task_id: str):
    try:
        pdf_path = md_2_pdf(task_id)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"pdf_url": f"http://localhost:8000/static/{task_id}/res.pdf"}


@router.post("/revise_image")
async def revise_image(payload: ImageRevisionRequest):
    work_dir = get_work_dir(payload.task_id)
    image_path = os.path.join(work_dir, payload.filename)
    md_path = os.path.join(work_dir, "res.md")

    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="图片不存在")

    edited_filename = f"edited_{payload.filename}"
    edited_path = os.path.join(work_dir, edited_filename)

    try:
        from PIL import Image, ImageDraw, ImageFont

        image = Image.open(image_path).convert("RGB")
        footer_height = max(56, min(140, image.height // 6))
        canvas = Image.new("RGB", (image.width, image.height + footer_height), "white")
        canvas.paste(image, (0, 0))
        draw = ImageDraw.Draw(canvas)
        try:
            font = ImageFont.truetype("NotoSansCJK-Regular.ttc", max(14, image.width // 70))
        except Exception:
            font = ImageFont.load_default()
        wrapped = "\n".join(textwrap.wrap(payload.instruction, width=42))
        draw.rectangle((0, image.height, image.width, image.height + footer_height), fill=(250, 250, 250))
        draw.text((18, image.height + 14), f"修改说明：{wrapped}", fill=(30, 41, 59), font=font)
        canvas.save(edited_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"图片修改失败: {e}") from e

    content = ""
    if os.path.exists(md_path):
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace(f"]({payload.filename})", f"]({edited_filename})")
        content = content.replace(f"]({payload.filename.replace(os.sep, '/')})", f"]({edited_filename})")
        if edited_filename not in content:
            content += f"\n\n![修改后的图片]({edited_filename})\n\n> 图片修改说明：{payload.instruction}\n"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(content)

    return {
        "success": True,
        "filename": edited_filename,
        "image_url": f"http://localhost:8000/static/{payload.task_id}/{edited_filename}",
        "content": content,
    }


def _extract_image_context(paper_content: str, filename: str) -> str:
    escaped = re.escape(filename)
    pattern = rf"!\[([^\]]*)\]\([^)]*{escaped}\)"
    match = re.search(pattern, paper_content, re.IGNORECASE)
    if not match:
        return "(图片尚未在论文中引用)"

    start = max(0, match.start() - 500)
    end = min(len(paper_content), match.end() + 500)
    return paper_content[start:end].strip()


def _clip_context(value: str, limit: int) -> str:
    value = (value or "").strip()
    if len(value) <= limit:
        return value
    half = max(1, limit // 2)
    return (
        value[:half]
        + f"\n\n...（中间内容较长，已压缩；原始长度 {len(value)} 字）...\n\n"
        + value[-half:]
    )


def _read_task_messages(task_id: str) -> list[dict]:
    message_path = Path("logs/messages") / f"{task_id}.json"
    if not message_path.exists():
        return []
    try:
        data = json.loads(message_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"读取任务消息上下文失败 {task_id}: {e}")
        return []
    return data if isinstance(data, list) else []


def _format_tool_outputs(output: object) -> str:
    if not isinstance(output, list):
        return ""
    lines: list[str] = []
    for item in output:
        if isinstance(item, str):
            if item.strip():
                lines.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        if item.get("res_type") == "error":
            lines.append(
                f"[error] {item.get('name', '')}: {item.get('value', '')}\n{item.get('traceback', '')}".strip()
            )
        elif item.get("format") in {"png", "jpeg", "svg", "pdf"}:
            lines.append(f"[{item.get('format')}] 生成了图像/文件结果")
        else:
            msg = str(item.get("msg") or "").strip()
            if msg:
                lines.append(msg)
    return "\n".join(lines)



def _infer_text_revision_scope(instruction: str) -> str:
    text = (instruction or "").lower()
    global_keywords = [
        "全文",
        "全篇",
        "整篇",
        "整体",
        "通篇",
        "统一全文",
        "统一术语",
        "所有章节",
        "全部修改",
        "重构结构",
        "重写论文",
        "更新目录",
        "调整结构",
    ]
    if any(keyword in text for keyword in global_keywords):
        return "paper"
    return "selection"


def _build_focused_text_revision_context(
    paper_content: str,
    selected_text: str,
    nearby_context: str | None,
    scope: str,
) -> str:
    selected = (selected_text or "").strip()
    nearby = (nearby_context or "").strip()

    if scope == "paper":
        return "\n\n".join(
            part
            for part in [
                "## 当前完整论文 Markdown",
                _clip_context(paper_content, 50000) or "(当前没有论文正文)",
                "## 用户选中文本",
                selected or "(未提供)",
                "## 选中文本附近上下文",
                nearby or "(未提供)",
            ]
            if part
        )

    return "\n\n".join(
        part
        for part in [
            "## 用户选中文本",
            selected or "(未提供)",
            "## 选中文本附近上下文",
            _clip_context(nearby, 6000) or "(未提供)",
            "## 说明",
            "本次默认为局部修改，只能返回 revised_text，不要返回 updated_paper。",
        ]
        if part
    )


def _parse_text_revision_payload(raw_text: str) -> dict:
    text = raw_text.strip()

    fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    json_text = _extract_json_braces(text)
    if json_text:
        text = json_text

    try:
        parsed = json.loads(text)
    except Exception:
        return {
            "status": "failed",
            "message": "AI 返回格式异常，未解析到有效 JSON 对象。",
            "revised_text": None,
            "updated_paper": None,
            "parse_error": True,
            "raw_text": raw_text.strip(),
        }

    revised_text = parsed.get("revised_text")
    updated_paper = parsed.get("updated_paper")

    return {
        "status": parsed.get("status")
        if parsed.get("status") in {"success", "failed"}
        else "success",
        "message": str(parsed.get("message") or ""),
        "revised_text": (
            revised_text
            if isinstance(revised_text, str) and revised_text.strip()
            else None
        ),
        "updated_paper": (
            updated_paper
            if isinstance(updated_paper, str) and updated_paper.strip()
            else None
        ),
        "parse_error": False,
    }


def _find_normalized_span(source: str, needle: str) -> tuple | None:
    if not source or not needle:
        return None

    src_tokens = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"\S+", source)]
    needle_tokens = [m.group(0) for m in re.finditer(r"\S+", needle)]

    if not src_tokens or not needle_tokens:
        return None

    n = len(needle_tokens)
    for i in range(len(src_tokens) - n + 1):
        if [tok for tok, _, _ in src_tokens[i : i + n]] == needle_tokens:
            return src_tokens[i][1], src_tokens[i + n - 1][2]

    return None


def _apply_local_text_revision(
    paper_content: str,
    selected_text: str,
    revised_text: str,
) -> tuple:
    selected = (selected_text or "").strip()
    revised = (revised_text or "").strip()

    if not paper_content or not selected or not revised:
        return paper_content, False, "缺少原文或修订文本"

    count = paper_content.count(selected)
    if count == 1:
        return paper_content.replace(selected, revised, 1), True, "局部文本已替换"

    if count == 0:
        span = _find_normalized_span(paper_content, selected)
        if span:
            start, end = span
            return (
                paper_content[:start] + revised + paper_content[end:],
                True,
                "局部文本已通过空白归一化匹配替换",
            )
        return paper_content, False, "未能在当前论文中找到选中文本，可能前端内容已变化"

    return paper_content, False, f"选中文本在论文中出现 {count} 次，无法安全自动替换"


def _validate_text_revision_paper_update(
    original: str,
    updated: str,
) -> list[str]:
    issues: list[str] = []

    if not updated.strip():
        issues.append("updated_paper 为空")
        return issues

    if len(updated) < len(original) * 0.6:
        issues.append("updated_paper 长度异常缩短，疑似丢失章节")

    required_headings = [
        "一、问题重述",
        "二、问题分析",
        "三、模型假设",
        "五、模型的建立与求解",
    ]
    for heading in required_headings:
        if heading in original and heading not in updated:
            issues.append(f"缺少原有章节标题：{heading}")

    original_images = set(re.findall(r"!\[[^\]]*\]\([^)]+\)", original))
    updated_images = set(re.findall(r"!\[[^\]]*\]\([^)]+\)", updated))
    missing_images = list(original_images - updated_images)
    if missing_images:
        issues.append(f"丢失图片引用 {len(missing_images)} 个")

    original_formula_count = original.count("$$")
    updated_formula_count = updated.count("$$")
    if (
        original_formula_count >= 2
        and updated_formula_count < original_formula_count * 0.7
    ):
        issues.append("公式数量明显减少，疑似误删公式")

    return issues




def _build_task_revision_context(task_id: str, work_dir: str, paper_content: str) -> str:
    messages = _read_task_messages(task_id)
    modeler_parts: list[str] = []
    coder_parts: list[str] = []
    tool_parts: list[str] = []

    for message in messages:
        msg_type = message.get("msg_type")
        content = str(message.get("content") or "").strip()
        agent_type = message.get("agent_type")
        if msg_type == "agent" and content:
            if agent_type == "ModelerAgent":
                modeler_parts.append(_clip_context(content, 6000))
            elif agent_type == "CoderAgent":
                coder_parts.append(_clip_context(content, 6000))
        elif msg_type == "tool":
            tool_name = str(message.get("tool_name") or "tool")
            input_data = message.get("input") if isinstance(message.get("input"), dict) else {}
            code = ""
            if isinstance(input_data, dict) and isinstance(input_data.get("code"), str):
                code = _clip_context(str(input_data["code"]), 4000)
            outputs = _clip_context(_format_tool_outputs(message.get("output")), 5000)
            if code or outputs:
                tool_parts.append(
                    "\n".join(
                        part
                        for part in [
                            f"### 工具 {tool_name}",
                            f"代码：\n```python\n{code}\n```" if code else "",
                            f"输出：\n{outputs}" if outputs else "",
                        ]
                        if part
                    )
                )

    try:
        files = get_current_files(work_dir, "all")
    except Exception:
        files = []
    important_files = [
        item
        for item in files
        if re.search(rf"\.(?:csv|xlsx|xls|json|{IMAGE_EXTENSION_RE_FRAGMENT}|pdf|md|tex|ipynb|py)$", item, re.I)
    ][:120]

    try:
        code_cells = get_notebook_code_cells(work_dir)
    except Exception:
        code_cells = []
    notebook_context = "\n\n".join(
        f"### Notebook 代码单元 {index + 1}\n```python\n{_clip_context(code, 3500)}\n```"
        for index, code in enumerate(code_cells[-8:])
        if code.strip()
    )

    return "\n\n".join(
        part
        for part in [
            "## 完整论文 Markdown\n" + (paper_content.strip() or "(当前还没有论文正文)"),
            "## 建模思路上下文\n"
            + (_clip_context("\n\n".join(modeler_parts), 18000) or "(没有读取到建模手输出)"),
            "## 代码与执行结果上下文\n"
            + (
                _clip_context("\n\n".join([*coder_parts, *tool_parts]), 22000)
                or "(没有读取到代码手或工具执行结果)"
            ),
            "## 任务文件列表\n" + ("\n".join(important_files) or "(暂无文件列表)"),
            "## 最近 Notebook 代码上下文\n" + (notebook_context or "(暂无 Notebook 代码上下文)"),
        ]
        if part
    )


def _build_focused_image_task_context(
    task_id: str,
    work_dir: str,
    filename: str,
    code_entry: dict,
    paper_content: str,
) -> str:
    """只传目标图片相关上下文，不塞完整任务上下文，防止混入无关内容。"""
    image_name = normalize_image_name(filename)
    section = str(code_entry.get("section") or "")
    source_code = str(code_entry.get("code") or "")
    image_context = _extract_image_context(paper_content, image_name)

    return "\n\n".join(
        part
        for part in [
            f"## 目标图片\n{image_name}",
            f"## 图片所属章节\n{section or '(未知)'}",
            f"## 图片附近论文上下文\n{_clip_context(image_context, 3000)}",
            f"## 目标图片原始代码\n```python\n{_clip_context(source_code, 8000)}\n```",
        ]
        if part
    )


def _format_revision_history(history: list[dict] | None, limit: int = 5000) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for item in history[-8:]:
        role = str(item.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        label = "用户" if role == "user" else "AI"
        lines.append(f"{label}：{content}")
    return _clip_context("\n\n".join(lines), limit)


def _build_revision_message(
    filename: str,
    instruction: str,
    context: str,
    title: str | None,
    description: str | None,
    source_code: str,
    task_context: str,
    conversation_history: list[dict] | None = None,
) -> str:
    image_title = (title or "").strip() or "(未提供)"
    current_description = (description or "").strip() or "(当前界面未提取到图片旁边介绍)"
    history_text = _format_revision_history(conversation_history)
    history_block = (
        f"## 本图历史修订对话（仅作为用户意图上下文，不要模仿其输出格式）\n{history_text}\n\n"
        if history_text
        else ""
    )
    return (
        f"## 图片文件名\n`{filename}`\n\n"
        f"## 生成该图片的原始 Python 代码\n```python\n{source_code}\n```\n\n"
        f"## 图片标题\n{image_title}\n\n"
        f"## 当前图片旁边介绍\n{current_description}\n\n"
        f"## 论文上下文（图片周围 Markdown）\n```markdown\n{context}\n```\n\n"
        f"## 任务全局上下文（完整论文、建模思路、代码结果）\n{task_context}\n\n"
        f"{history_block}"
        f"## 用户修改指令\n{instruction}\n\n"
        "请根据以上所有信息（优先用户指令，其次论文上下文，最后靠标题/文件名推断），"
        "修改绘图代码并生成新的 alt-text 与图片旁边说明。"
        "无论本次修改是否很小，都必须返回可直接执行的完整 revised_code。"
    )


def _extract_json_braces(text: str) -> str | None:
    """从文本中提取首个完整 JSON 对象（正确处理嵌套大括号）。"""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start=start):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _parse_revision_payload(raw_text: str) -> dict:
    text = raw_text.strip()

    # 先尝试提取 ```json ... ``` 代码块
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    # 用括号匹配提取完整 JSON
    json_text = _extract_json_braces(text)
    if json_text:
        text = json_text

    try:
        parsed = json.loads(text)
    except Exception:
        return {
            "status": "failed",
            "message": "AI 返回格式异常，未返回 JSON 对象。",
            "analysis_text": raw_text.strip(),
            "revised_code": None,
            "updated_alt_text": None,
            "updated_caption": None,
            "parse_error": True,
        }

    return {
        "status": parsed.get("status") if parsed.get("status") in {"success", "failed"} else "success",
        "message": str(parsed.get("message") or ""),
        "analysis_text": str(parsed.get("analysis_text") or parsed.get("message") or ""),
        "revised_code": parsed.get("revised_code") or None,
        "updated_alt_text": parsed.get("updated_alt_text") or None,
        "updated_caption": parsed.get("updated_caption") or None,
        "parse_error": False,
    }


async def _repair_revision_payload(
    revision_llm: LLM,
    user_message: str,
    raw_text: str,
    filename: str,
    source_code: str,
) -> dict:
    logger.warning(
        f"图片修订返回缺少可执行 revised_code，尝试二次纠偏。filename={filename}, raw={_clip_context(raw_text, 1200)}"
    )
    repair_message = (
        f"{user_message}\n\n"
        "## 上一次 AI 返回内容\n"
        f"{_clip_context(raw_text, 4000)}\n\n"
        "## 强制修正要求\n"
        "上一次返回没有提供可执行的 revised_code，导致系统无法重新生成图片。"
        f"请以图片文件名 `{filename}` 和下面原始代码为基础，重新输出一个 JSON 对象。\n"
        "必须满足：\n"
        "1. status 为 success 时 revised_code 必须是完整 Python 代码，不允许为空。\n"
        f"2. revised_code 必须覆盖保存到原文件名 `{filename}`。\n"
        "3. 不要输出 Markdown 代码块，不要输出 JSON 之外的解释。\n\n"
        f"## 原始代码备份\n```python\n{source_code}\n```"
    )
    try:
        repaired_raw = await simple_chat(
            revision_llm,
            [
                {"role": "system", "content": get_image_revision_prompt()},
                {"role": "user", "content": repair_message},
            ],
        )
    except Exception as e:
        logger.error(f"AI 图片修订二次纠偏失败: {e}")
        return _parse_revision_payload(raw_text)
    return _parse_revision_payload(repaired_raw)


def _file_sha256(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _auto_patch_revision_code(code: str, error_text: str) -> tuple[str, bool, str]:
    """针对图片修订代码的常见 NameError 做保守自动补丁。"""
    patched = code
    notes: list[str] = []
    error_text = error_text or ""

    def ensure_import(import_line: str) -> None:
        nonlocal patched
        if import_line not in patched:
            patched = import_line + "\n" + patched

    if "name 'sign' is not defined" in error_text:
        if "import numpy as np" in patched:
            patched = re.sub(r"(?<![\w.])sign\s*\(", "np.sign(", patched)
            notes.append("已将 sign(...) 修正为 np.sign(...)")
        else:
            ensure_import("import numpy as np")
            patched = re.sub(r"(?<![\w.])sign\s*\(", "np.sign(", patched)
            notes.append("已补充 import numpy as np，并将 sign(...) 修正为 np.sign(...)")

    if "name 'np' is not defined" in error_text:
        ensure_import("import numpy as np")
        notes.append("已补充 import numpy as np")

    if "name 'pd' is not defined" in error_text:
        ensure_import("import pandas as pd")
        notes.append("已补充 import pandas as pd")

    if "name 'plt' is not defined" in error_text:
        ensure_import("import matplotlib.pyplot as plt")
        notes.append("已补充 import matplotlib.pyplot as plt")

    if "name 'sns' is not defined" in error_text:
        ensure_import("import seaborn as sns")
        notes.append("已补充 import seaborn as sns")

    return patched, patched != code, "；".join(notes)


async def _execute_revision_once(
    interpreter: LocalCodeInterpreter,
    code_to_run: str,
) -> tuple[bool, str]:
    """执行一次修订代码，返回 (成功, 错误信息)。"""
    _, error_occurred, error_message = await interpreter.execute_code(code_to_run)
    if error_occurred:
        return False, error_message
    return True, ""


async def _rerun_revised_image_code(
    task_id: str,
    work_dir: str,
    filename: str,
    revised_code: str,
    cell_index: int | None,
) -> tuple[bool, str]:
    target = os.path.join(work_dir, normalize_image_name(filename))
    serializer = NotebookSerializer(
        work_dir=work_dir,
        notebook_name=f"image_revision_{normalize_image_name(filename)}.ipynb",
    )
    interpreter = LocalCodeInterpreter(
        task_id=task_id,
        work_dir=work_dir,
        notebook_serializer=serializer,
    )
    await interpreter.initialize()
    try:
        compat_outputs = await asyncio.to_thread(
            interpreter.execute_code_,
            _IMAGE_REVISION_COMPAT_CODE,
        )
        compat_errors = [out for mark, out in compat_outputs if mark == "error"]
        if compat_errors:
            return False, f"图片修订兼容环境初始化失败：{compat_errors[-1]}"

        # 第一优先级：只执行 revised_code，不执行任何前置依赖
        before_digest = _file_sha256(target)
        ok, err = await _execute_revision_once(interpreter, revised_code)

        # 第二优先级：常见 NameError 自动补丁后重试
        if not ok:
            patched_code, changed, note = _auto_patch_revision_code(revised_code, err)
            if changed:
                ok, patched_err = await _execute_revision_once(interpreter, patched_code)
                if ok:
                    revised_code = patched_code
                else:
                    err = f"{err}\n自动补丁后仍失败：{patched_err}"

        if not ok:
            return False, f"修改后的绘图代码执行失败：{err}"

        if not os.path.exists(target):
            return False, "修改代码执行完成，但没有生成目标图片文件"

        after_digest = _file_sha256(target)
        if before_digest and after_digest == before_digest:
            return False, (
                "修改代码执行完成，但目标图片内容没有变化。"
                "请让 AI 修改绘图代码并覆盖保存到原图片文件名。"
            )

        update_image_code_index(
            work_dir,
            revised_code,
            cell_index=cell_index,
            section="image_revision",
        )
        return True, "图片已通过修改代码重新生成"
    finally:
        await interpreter.cleanup()


def _apply_image_text_revision(
    paper_content: str,
    filename: str,
    updated_alt_text: str | None,
    updated_caption: str | None,
) -> tuple[str, bool]:
    if not paper_content or not (updated_alt_text or updated_caption):
        return paper_content, False

    escaped = re.escape(filename)
    pattern = rf"!\[([^\]]*)\]\(([^)]*{escaped})\)"
    match = re.search(pattern, paper_content, re.IGNORECASE)
    if not match:
        return paper_content, False

    new_alt = (updated_alt_text or match.group(1)).strip()
    new_ref = f"![{new_alt}]({match.group(2)})"
    updated = paper_content[: match.start()] + new_ref + paper_content[match.end() :]

    if not updated_caption:
        return updated, updated != paper_content

    insert_at = match.start() + len(new_ref)
    caption = updated_caption.strip()
    caption_block = f"\n\n{caption}\n"
    next_image = updated.find("![", insert_at)
    paragraph_end = updated.find("\n\n", insert_at + 1)
    if paragraph_end != -1 and (next_image == -1 or paragraph_end < next_image):
        existing = updated[insert_at:paragraph_end].strip()
        if existing:
            updated = updated[:insert_at] + caption_block + updated[paragraph_end:]
        else:
            updated = updated[:insert_at] + caption_block + updated[paragraph_end + 2 :]
    else:
        updated = updated[:insert_at] + caption_block + updated[insert_at:]

    return updated, updated != paper_content


@router.post("/revise_image_chat")
async def revise_image_chat(payload: ImageRevisionChatRequest):
    work_dir = get_work_dir(payload.task_id)
    await _publish_revision_step(
        payload.task_id,
        title="图片修订启动：正在读取图片与论文上下文",
        current=1,
        total=9,
    )
    image_path = os.path.join(work_dir, payload.filename)
    md_path = os.path.join(work_dir, "res.md")

    if not os.path.exists(image_path):
        await _publish_revision_step(
            payload.task_id,
            title="图片修订失败：图片文件不存在",
            detail=payload.filename,
            msg_type="error",
        )
        raise HTTPException(status_code=404, detail="图片不存在")

    image_name = normalize_image_name(payload.filename)
    code_entry = get_image_code_entry(work_dir, image_name)
    if not code_entry or not code_entry.get("code"):
        await _publish_revision_step(
            payload.task_id,
            title="图片修订失败：没有找到图片对应的生成代码",
            detail="无法通过修改代码重新生成图片",
            msg_type="error",
        )
        return ImageRevisionChatResponse(
            success=False,
            status="failed",
            message="没有找到这张图片对应的生成代码，无法通过修改代码重新生成图片",
            analysis_text="当前任务缺少图片到代码单元的映射。请先重新运行一次生成该图片的代码，系统会记录映射。",
            code_found=False,
        )

    await _publish_revision_step(
        payload.task_id,
        title="图片修订：已定位原始绘图代码",
        detail=f"图片：{image_name}",
        current=2,
        total=9,
    )

    paper_content = ""
    if os.path.exists(md_path):
        with open(md_path, "r", encoding="utf-8") as f:
            paper_content = f.read()

    await _publish_revision_step(
        payload.task_id,
        title="图片修订：正在整理论文上下文和历史修改记录",
        current=3,
        total=9,
    )

    image_context = _extract_image_context(paper_content, payload.filename)
    task_context = _build_focused_image_task_context(
        payload.task_id,
        work_dir,
        image_name,
        code_entry,
        paper_content,
    )
    user_message = _build_revision_message(
        payload.filename,
        payload.instruction,
        image_context,
        payload.title,
        payload.description,
        str(code_entry.get("code") or ""),
        task_context,
        payload.conversation_history,
    )

    await _publish_revision_step(
        payload.task_id,
        title="图片修订：AI 正在分析修改指令并生成新绘图代码",
        detail=payload.instruction,
        current=4,
        total=9,
    )

    messages: list[dict] = [{"role": "system", "content": get_image_revision_prompt()}]
    messages.append({"role": "user", "content": user_message})

    revision_llm = LLM(
        api_type=settings.WRITER_API_TYPE,
        api_key=settings.WRITER_API_KEY,
        model=settings.WRITER_MODEL,
        base_url=settings.WRITER_BASE_URL,
        task_id=payload.task_id,
    )

    try:
        response = await revision_llm.chat_stream(
            history=messages,
            agent_name=AgentType.WRITER,
            sub_title="image_revision",
        )
        raw_text = response.content
    except Exception as e:
        logger.error(f"AI 图片修订失败: {e}")
        await _publish_revision_step(
            payload.task_id,
            title="图片修订失败：AI 调用异常",
            detail=str(e),
            msg_type="error",
        )
        raise HTTPException(status_code=500, detail=f"AI 修改失败: {e}") from e

    await _publish_revision_step(
        payload.task_id,
        title="图片修订：正在解析 AI 返回的修订方案",
        current=5,
        total=9,
    )

    parsed = _parse_revision_payload(raw_text)
    if parsed.get("parse_error") or (
        parsed.get("status") == "success" and not parsed.get("revised_code")
    ):
        await _publish_revision_step(
            payload.task_id,
            title="图片修订：AI 返回格式不完整，正在自动纠偏",
            detail="缺少 revised_code 或 JSON 格式异常",
            current=6,
            total=9,
            msg_type="warning",
        )
        parsed = await _repair_revision_payload(
            revision_llm,
            user_message,
            raw_text,
            image_name,
            str(code_entry.get("code") or ""),
        )
    revised_code = parsed.get("revised_code")
    if parsed["status"] == "success" and not revised_code:
        await _publish_revision_step(
            payload.task_id,
            title="图片修订失败：AI 没有返回可执行绘图代码",
            detail="缺少 revised_code",
            msg_type="error",
        )
        return ImageRevisionChatResponse(
            success=False,
            status="failed",
            message="AI 没有按要求返回可执行的 revised_code，无法重新生成图片",
            analysis_text=parsed["analysis_text"],
            code_found=True,
        )

    image_regenerated = False
    run_message = ""
    if parsed["status"] == "success":
        await _publish_revision_step(
            payload.task_id,
            title="图片修订：正在执行修改后的绘图代码",
            current=7,
            total=9,
        )
        image_regenerated, run_message = await _rerun_revised_image_code(
            payload.task_id,
            work_dir,
            image_name,
            str(revised_code),
            code_entry.get("cell_index"),
        )
        if not image_regenerated:
            # 即使重绘失败，也尽量更新 caption/alt-text
            await _publish_revision_step(
                payload.task_id,
                title="图片修订：图片重绘失败，尝试更新文案说明",
                detail=run_message,
                current=8,
                total=9,
                msg_type="warning",
            )
            caption_updated = False
            paper_updated_fallback = False

            if os.path.exists(md_path) and (
                parsed.get("updated_alt_text") or parsed.get("updated_caption")
            ):
                updated_content, paper_updated_fallback = _apply_image_text_revision(
                    paper_content,
                    image_name,
                    parsed.get("updated_alt_text"),
                    parsed.get("updated_caption"),
                )
                if paper_updated_fallback:
                    with open(md_path, "w", encoding="utf-8") as f:
                        f.write(updated_content)
                    caption_updated = True

                update_image_metadata(
                    work_dir,
                    image_name,
                    description=parsed.get("updated_caption") or parsed.get("updated_alt_text"),
                    alt_text=parsed.get("updated_alt_text"),
                    caption=parsed.get("updated_caption"),
                    metadata_source="ai_revision",
                )

            await _publish_revision_step(
                payload.task_id,
                title="图片修订完成（部分成功）",
                detail="文案已更新，但图片重绘失败" if caption_updated else run_message or "图片重绘失败",
                current=9,
                total=9,
                msg_type="warning" if caption_updated else "error",
            )

            return ImageRevisionChatResponse(
                success=caption_updated,
                status="partial_success" if caption_updated else "failed",
                message=(
                    "图片说明已更新，但图片重绘失败："
                    + (run_message or "修改代码执行失败，图片没有重新生成")
                    if caption_updated
                    else run_message or "修改代码执行失败，图片没有重新生成"
                ),
                analysis_text=parsed["analysis_text"],
                revised_code=str(revised_code),
                updated_alt_text=parsed.get("updated_alt_text"),
                updated_caption=parsed.get("updated_caption"),
                paper_updated=paper_updated_fallback if not image_regenerated else False,
                caption_updated=caption_updated,
                render_success=False,
                render_message=run_message,
                image_url=f"http://localhost:8000/static/{payload.task_id}/{image_name}",
                code_found=True,
            )

    paper_updated = False
    if parsed["status"] == "success" and os.path.exists(md_path):
        await _publish_revision_step(
            payload.task_id,
            title="图片修订：正在更新论文中的图片说明",
            current=8,
            total=9,
        )
        updated_content, paper_updated = _apply_image_text_revision(
            paper_content,
            image_name,
            parsed.get("updated_alt_text"),
            parsed.get("updated_caption"),
        )
        if paper_updated:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(updated_content)

    if parsed["status"] == "success":
        update_image_metadata(
            work_dir,
            image_name,
            description=parsed.get("updated_caption") or parsed.get("updated_alt_text"),
            alt_text=parsed.get("updated_alt_text"),
            caption=parsed.get("updated_caption"),
            metadata_source="ai_revision",
        )

    await _publish_revision_step(
        payload.task_id,
        title="图片修订完成：图片已重新生成并更新说明",
        detail=image_name,
        current=9,
        total=9,
        msg_type="success",
    )

    return ImageRevisionChatResponse(
        success=parsed["status"] == "success",
        status=parsed["status"],
        message=parsed["message"] or run_message or ("修改成功" if parsed["status"] == "success" else "修改失败"),
        analysis_text=parsed["analysis_text"],
        revised_code=str(revised_code) if revised_code else None,
        updated_alt_text=parsed.get("updated_alt_text"),
        updated_caption=parsed.get("updated_caption"),
        paper_updated=paper_updated,
        caption_updated=paper_updated,
        render_success=image_regenerated,
        render_message=run_message if not image_regenerated else None,
        image_url=f"http://localhost:8000/static/{payload.task_id}/{image_name}",
        code_found=True,
    )


@router.post("/revise_text_chat")
async def revise_text_chat(payload: TextRevisionChatRequest):
    """AI 对话修改论文文本。

    接受用户选中的文本段落和修改指令，调用 LLM 进行精准修订。
    """
    work_dir = get_work_dir(payload.task_id)
    await _publish_revision_step(
        payload.task_id,
        title="文本修订启动：正在读取论文和选中文本",
        current=1,
        total=6,
    )
    md_path = os.path.join(work_dir, "res.md")
    paper_content = ""
    if os.path.exists(md_path):
        with open(md_path, "r", encoding="utf-8") as f:
            paper_content = f.read()
    await _publish_revision_step(
        payload.task_id,
        title="文本修订：正在整理论文上下文和历史修改记录",
        current=2,
        total=6,
    )

    requested_scope = _infer_text_revision_scope(payload.instruction)

    task_context = _build_focused_text_revision_context(
        paper_content,
        payload.selected_text,
        payload.context,
        requested_scope,
    )

    await _publish_revision_step(
        payload.task_id,
        title="文本修订：AI 正在判断修改范围并生成修订内容",
        detail=f"{payload.instruction}（范围：{'全文' if requested_scope == 'paper' else '局部'}）",
        current=3,
        total=6,
    )

    messages: list[dict] = [
        {"role": "system", "content": get_text_revision_prompt()},
    ]
    history_text = _format_revision_history(payload.conversation_history)

    context_block = ""
    if payload.context:
        context_block = f"\n\n【选中文本附近上下文】\n{payload.context}"
    history_block = (
        f"\n\n【历史修订对话，仅作为意图上下文，不要模仿其输出格式】\n{history_text}"
        if history_text
        else ""
    )

    scope_instruction = (
        "【修改范围约束：全文修改】\n本次用户指令被判定为全文修改，可以返回 updated_paper。"
        if requested_scope == "paper"
        else "【修改范围约束：局部修改】\n必须只返回 revised_text，不要返回 updated_paper。"
    )

    messages.append({
        "role": "user",
        "content": (
            f"【需要修改的原文】\n{payload.selected_text}"
            f"{context_block}"
            f"{history_block}"
            f"\n\n{task_context}"
            f"\n\n【修改指令】\n{payload.instruction}"
            f"\n\n{scope_instruction}"
        ),
    })

    revision_llm = LLM(
        api_type=settings.WRITER_API_TYPE,
        api_key=settings.WRITER_API_KEY,
        model=settings.WRITER_MODEL,
        base_url=settings.WRITER_BASE_URL,
        task_id=payload.task_id,
    )

    try:
        response = await revision_llm.chat_stream(
            history=messages,
            agent_name=AgentType.WRITER,
            sub_title="text_revision",
        )
        raw_text = response.content
    except Exception as e:
        logger.error(f"AI 文本修订失败: {e}")
        await _publish_revision_step(
            payload.task_id,
            title="文本修订失败：AI 调用异常",
            detail=str(e),
            msg_type="error",
        )
        raise HTTPException(status_code=500, detail=f"AI 修改失败: {e}") from e

    await _publish_revision_step(
        payload.task_id,
        title="文本修订：正在解析 AI 返回结果",
        current=4,
        total=6,
    )

    parsed = _parse_text_revision_payload(raw_text)

    # 二次纠偏：JSON 解析失败或必要字段缺失时让模型重试一次
    need_repair = (
        parsed.get("parse_error")
        or (
            parsed.get("status") == "success"
            and requested_scope == "selection"
            and not parsed.get("revised_text")
        )
        or (
            parsed.get("status") == "success"
            and requested_scope == "paper"
            and not parsed.get("updated_paper")
        )
    )
    if need_repair:
        await _publish_revision_step(
            payload.task_id,
            title="文本修订：AI 返回格式不完整，正在自动纠偏",
            detail="缺少必要字段或 JSON 格式异常",
            current=4,
            total=6,
            msg_type="warning",
        )
        scope_rule = (
            "本次是全文修改，必须返回 updated_paper，revised_text 可为空。"
            if requested_scope == "paper"
            else "本次是局部修改，必须返回 revised_text，updated_paper 必须为空。"
        )
        repair_message = (
            messages[-1]["content"]
            + "\n\n## 上一次 AI 返回内容\n"
            + _clip_context(raw_text, 4000)
            + "\n\n## 强制修正要求\n"
            + "上一次返回没有形成可解析 JSON 或字段不完整。请重新输出一个 JSON 对象，不要输出 Markdown 代码块，不要输出 JSON 之外的解释。\n"
            + scope_rule
        )
        try:
            repair_response = await simple_chat(
                revision_llm,
                [
                    {"role": "system", "content": get_text_revision_prompt()},
                    {"role": "user", "content": repair_message},
                ],
            )
            parsed = _parse_text_revision_payload(repair_response)
        except Exception as e:
            logger.error(f"AI 文本修订二次纠偏失败: {e}")

    revised_text = parsed.get("revised_text")
    updated_paper = parsed.get("updated_paper")
    paper_updated = False
    applied = False
    validation_issues: list[str] = []

    if parsed.get("status") == "success":
        if requested_scope == "selection":
            if revised_text:
                updated_content, applied, apply_message = _apply_local_text_revision(
                    paper_content,
                    payload.selected_text,
                    revised_text,
                )
                if applied:
                    await _publish_revision_step(
                        payload.task_id,
                        title="文本修订：正在写入选中文段",
                        current=5,
                        total=6,
                    )
                    with open(md_path, "w", encoding="utf-8") as f:
                        f.write(updated_content)
                    paper_updated = True
                else:
                    validation_issues.append(apply_message)
            else:
                validation_issues.append("局部修改模式下 AI 未返回 revised_text")
        else:
            if updated_paper:
                validation_issues = _validate_text_revision_paper_update(
                    paper_content,
                    updated_paper,
                )
                if not validation_issues:
                    await _publish_revision_step(
                        payload.task_id,
                        title="文本修订：正在写入完整论文",
                        current=5,
                        total=6,
                    )
                    with open(md_path, "w", encoding="utf-8") as f:
                        f.write(updated_paper)
                    paper_updated = True
                    applied = True
            else:
                validation_issues.append("全文修改模式下 AI 未返回 updated_paper")

    await _publish_revision_step(
        payload.task_id,
        title="文本修订完成",
        detail=(
            "已更新完整论文" if applied
            else "已生成修订文本（未自动写回）" if revised_text
            else "AI 修订未完全成功"
        ),
        current=6,
        total=6,
        msg_type="success" if not validation_issues else "warning",
    )

    return TextRevisionChatResponse(
        success=parsed.get("status") == "success" and not validation_issues,
        status="partial_success" if (parsed.get("status") == "success" and validation_issues) else parsed.get("status", "failed"),
        message=(
            parsed.get("message") or ("修改成功" if not validation_issues else "修改存在风险，未完全写回")
        ),
        revised_text=revised_text,
        updated_paper=updated_paper if requested_scope == "paper" else None,
        paper_updated=paper_updated,
        revision_scope=requested_scope,
        applied=applied,
        validation_issues=validation_issues or None,
    )


@router.get("/open_folder")
async def open_folder(task_id: str):
    ic(task_id)
    work_dir = get_work_dir(task_id)

    if os.name == "nt":
        subprocess.run(["explorer", work_dir])
    elif os.name == "posix":
        subprocess.run(["open", work_dir])
    else:
        raise HTTPException(status_code=500, detail=f"不支持的操作系统: {os.name}")

    return {"message": "打开工作目录成功", "work_dir": work_dir}
