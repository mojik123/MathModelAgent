"""Artifact edit patch persistence and application.

Local AI edits can happen while the main modeling/writing workflow is still running.
The workflow may later overwrite ``res.md`` from section checkpoints, so edits must be
stored as patches and re-applied whenever the paper preview/final paper is assembled.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from app.utils.image_code_index import normalize_image_name
from app.utils.log_util import logger
from app.utils.paper_cleaner import clean_visible_image_alt, looks_like_image_filename

PATCH_DIR = ".artifact_edits"
TEXT_PATCH_FILE = "paper_text_patches.json"
IMAGE_PATCH_FILE = "image_patches.json"


def _edit_dir(work_dir: str) -> Path:
    path = Path(work_dir) / PATCH_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except Exception as exc:
        logger.warning(f"读取 artifact edit patch 失败 {path}: {exc}")
        return default


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _find_normalized_span(source: str, needle: str) -> tuple[int, int] | None:
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


def _safe_replace_once(source: str, selected_text: str, revised_text: str) -> tuple[str, bool, str]:
    selected = (selected_text or "").strip()
    revised = (revised_text or "").strip()
    if not source or not selected or not revised:
        return source, False, "缺少原文或修订文本"
    if revised in source and selected not in source:
        return source, False, "修订文本已存在，跳过重复应用"
    count = source.count(selected)
    if count == 1:
        return source.replace(selected, revised, 1), True, "精确匹配替换"
    if count == 0:
        span = _find_normalized_span(source, selected)
        if not span:
            return source, False, "未找到原文片段"
        start, end = span
        return source[:start] + revised + source[end:], True, "空白归一化匹配替换"
    return source, False, f"原文片段出现 {count} 次，跳过以避免误替换"


def record_text_patch(
    work_dir: str,
    *,
    task_id: str,
    selected_text: str,
    revised_text: str | None,
    instruction: str,
    scope: str,
    applied: bool,
    section_key: str | None = None,
    context: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    if not revised_text:
        return {}
    path = _edit_dir(work_dir) / TEXT_PATCH_FILE
    patches = _read_json(path, [])
    if not isinstance(patches, list):
        patches = []
    patch = {
        "patch_id": str(uuid.uuid4()),
        "task_id": task_id,
        "section_key": section_key,
        "selected_text": selected_text,
        "selected_norm": _normalize_text(selected_text),
        "revised_text": revised_text,
        "instruction": instruction,
        "scope": scope,
        "context": context,
        "message": message,
        "applied_immediately": applied,
        "status": "active",
        "created_at": _now_ms(),
    }
    patches.append(patch)
    _write_json(path, patches)
    return patch


def list_text_patches(work_dir: str) -> list[dict[str, Any]]:
    data = _read_json(_edit_dir(work_dir) / TEXT_PATCH_FILE, [])
    return data if isinstance(data, list) else []


def record_image_patch(
    work_dir: str,
    *,
    task_id: str,
    filename: str,
    instruction: str,
    updated_alt_text: str | None = None,
    updated_caption: str | None = None,
    revised_code: str | None = None,
    render_success: bool = False,
    message: str | None = None,
) -> dict[str, Any]:
    image_name = normalize_image_name(filename)
    path = _edit_dir(work_dir) / IMAGE_PATCH_FILE
    patches = _read_json(path, [])
    if not isinstance(patches, list):
        patches = []
    patch = {
        "patch_id": str(uuid.uuid4()),
        "task_id": task_id,
        "filename": image_name,
        "instruction": instruction,
        "updated_alt_text": updated_alt_text,
        "updated_caption": updated_caption,
        "revised_code": revised_code,
        "render_success": render_success,
        "message": message,
        "status": "active",
        "created_at": _now_ms(),
    }
    patches.append(patch)
    _write_json(path, patches)
    return patch


def list_image_patches(work_dir: str) -> list[dict[str, Any]]:
    data = _read_json(_edit_dir(work_dir) / IMAGE_PATCH_FILE, [])
    return data if isinstance(data, list) else []


def _apply_image_text_revision(
    paper_content: str,
    filename: str,
    updated_alt_text: str | None,
    updated_caption: str | None,
) -> tuple[str, bool]:
    if not paper_content or not (updated_alt_text or updated_caption):
        return paper_content, False
    image_name = normalize_image_name(filename)
    escaped = re.escape(image_name)
    pattern = rf"!\[([^\]]*)\]\(([^)]*{escaped})\)"
    match = re.search(pattern, paper_content, re.IGNORECASE)
    if not match:
        base = re.escape(image_name.split("/")[-1])
        pattern = rf"!\[([^\]]*)\]\(([^)]*{base})\)"
        match = re.search(pattern, paper_content, re.IGNORECASE)
        if not match:
            return paper_content, False

    raw_alt = (updated_alt_text or match.group(1)).strip()
    new_alt = clean_visible_image_alt(raw_alt, match.group(2), 1)
    new_ref = f"![{new_alt}]({match.group(2)})"
    updated = paper_content[: match.start()] + new_ref + paper_content[match.end() :]

    caption = (updated_caption or "").strip()
    if not caption or looks_like_image_filename(caption):
        return updated, updated != paper_content
    caption = clean_visible_image_alt(caption, match.group(2), 1) if not re.search(r"[\u4e00-\u9fff]", caption) else caption

    insert_at = match.start() + len(new_ref)
    caption_block = f"\n\n{caption}\n"
    paragraph_end = updated.find("\n\n", insert_at + 1)
    next_image = updated.find("![", insert_at + 1)
    if paragraph_end != -1 and (next_image == -1 or paragraph_end < next_image):
        existing = updated[insert_at:paragraph_end].strip()
        if existing:
            if caption in existing or looks_like_image_filename(existing):
                if looks_like_image_filename(existing):
                    updated = updated[:insert_at] + caption_block + updated[paragraph_end:]
                return updated, updated != paper_content
            updated = updated[:insert_at] + caption_block + updated[paragraph_end:]
        else:
            updated = updated[:insert_at] + caption_block + updated[paragraph_end + 2 :]
    else:
        if caption not in updated[insert_at : insert_at + 400]:
            updated = updated[:insert_at] + caption_block + updated[insert_at:]
    return updated, updated != paper_content


def apply_artifact_patches_to_markdown(text: str, work_dir: str) -> str:
    updated = text or ""

    for patch in list_text_patches(work_dir):
        if patch.get("status") != "active":
            continue
        if patch.get("scope") != "selection":
            continue
        selected = str(patch.get("selected_text") or "")
        revised = str(patch.get("revised_text") or "")
        updated, applied, note = _safe_replace_once(updated, selected, revised)
        if applied:
            patch["last_apply_note"] = note

    for patch in list_image_patches(work_dir):
        if patch.get("status") != "active":
            continue
        updated, _ = _apply_image_text_revision(
            updated,
            str(patch.get("filename") or ""),
            patch.get("updated_alt_text"),
            patch.get("updated_caption"),
        )

    return updated


def artifact_edit_summary(work_dir: str) -> dict[str, Any]:
    text_patches = list_text_patches(work_dir)
    image_patches = list_image_patches(work_dir)
    return {
        "text_patches": text_patches,
        "image_patches": image_patches,
        "text_patch_count": len([p for p in text_patches if p.get("status") == "active"]),
        "image_patch_count": len([p for p in image_patches if p.get("status") == "active"]),
    }