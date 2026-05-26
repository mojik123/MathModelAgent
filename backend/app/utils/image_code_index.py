"""Map generated image files back to the code cell that created them."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nbformat

from app.utils.image_constants import (
    IMAGE_EXTENSION_RE_FRAGMENT,
    SAVEFIG_RE,
    is_image_file,
    normalize_image_filename,
)

INDEX_FILENAME = ".image_code_index.json"
PLOT_TEXT_RE = re.compile(
    r"(?:[\w.]+\.)?(?:set_title|title|suptitle|set_xlabel|set_ylabel|xlabel|ylabel)\(\s*"
    r"(?P<quote>['\"])(?P<text>[^'\"]{3,160})(?P=quote)",
    re.IGNORECASE,
)
IMAGE_TITLE_RE = re.compile(
    r"print\(\s*['\"]##\s*图\d+(?:\.\d+)?(?:-\d+)?\s*[：:]\s*(?P<title>[^'\"]{2,60})\s*['\"]\s*\)",
    re.IGNORECASE,
)
IMAGE_ASSIGNMENT_RE = re.compile(
    rf"(?P<name>[A-Za-z_]\w*)\s*=\s*"
    rf"(?:[rubfRUBF]*)?(?P<quote>['\"])"
    rf"(?P<path>[^'\"]+\.{IMAGE_EXTENSION_RE_FRAGMENT})(?P=quote)",
    re.IGNORECASE,
)
SAVEFIG_VARIABLE_RE = re.compile(
    r"(?:[\w.]+\.)?savefig\(\s*(?P<name>[A-Za-z_]\w*)\b",
    re.IGNORECASE,
)


def normalize_image_name(filename: str) -> str:
    return normalize_image_filename(filename)


def normalize_image_key(filename: str) -> str:
    value = str(filename or "").replace("\\", "/").strip()
    value = re.sub(r"^[./]+", "", value)
    return value


def extract_saved_images(code: str) -> list[str]:
    images: list[str] = []
    for match in SAVEFIG_RE.finditer(code):
        image_name = normalize_image_name(match.group("path"))
        if image_name and image_name not in images:
            images.append(image_name)
    assigned_images = {
        match.group("name"): normalize_image_name(match.group("path"))
        for match in IMAGE_ASSIGNMENT_RE.finditer(code)
    }
    for match in SAVEFIG_VARIABLE_RE.finditer(code):
        image_name = assigned_images.get(match.group("name"))
        if image_name and image_name not in images:
            images.append(image_name)
    return images


def _humanize_image_title(filename: str) -> str:
    base = Path(normalize_image_name(filename)).stem
    match = re.match(
        r"^(\d+\.\d+|fig(?:ure)?\d+|fig_q\d+|fig_sens|fig_eda|图\d+|\d+)[_\-\s]*(.*)$",
        base,
        re.IGNORECASE,
    )
    figure_label = ""
    raw_title = base
    if match:
        figure_label = match.group(1)
        raw_title = match.group(2) or base
    words = re.split(
        r"[_\-\s]+|(?<=[a-z])(?=[A-Z])|(?<=\d)(?=[A-Za-z])|(?<=[A-Za-z])(?=\d)",
        raw_title,
    )
    title = " ".join(word.capitalize() for word in words if word)
    if figure_label and title:
        return f"{title} ({figure_label.lower()})"
    return title or base


def _extract_plot_texts(code: str) -> list[str]:
    texts: list[str] = []
    for match in PLOT_TEXT_RE.finditer(code or ""):
        text = re.sub(r"\s+", " ", match.group("text")).strip()
        if text and text not in texts:
            texts.append(text)
    return texts[:3]


def _extract_chinese_title(code: str) -> str:
    if not code:
        return ""
    for match in IMAGE_TITLE_RE.finditer(code):
        return match.group("title").strip()
    return ""


def build_image_description(
    filename: str,
    code: str = "",
    section: str | None = None,
) -> dict[str, str]:
    chinese_title = _extract_chinese_title(code)
    title = _humanize_image_title(filename)
    plot_texts = _extract_plot_texts(code)
    detail = "；".join(plot_texts) if plot_texts else title
    if section and section.startswith("image_revision"):
        section_text = "图片修改结果"
    else:
        section_text = section.strip() if section else "当前分析"
    display_name = chinese_title or title
    return {
        "alt_text": display_name,
        "caption": f"该图展示 {detail}，用于支撑{section_text}中的数据分析、趋势判断或模型结果解释。",
        "description": f"{display_name}：根据生成代码自动整理，展示 {detail} 相关结果。",
    }


def _ensure_entry_metadata(entry: dict[str, Any]) -> bool:
    metadata = build_image_description(
        str(entry.get("filename") or ""),
        str(entry.get("code") or ""),
        str(entry.get("section") or "") or None,
    )
    changed = False
    auto_metadata = entry.get("metadata_source") != "ai_revision"
    for key, value in metadata.items():
        if auto_metadata:
            if entry.get(key) != value:
                entry[key] = value
                changed = True
        elif not str(entry.get(key) or "").strip():
            entry[key] = value
            changed = True
    if auto_metadata and entry.get("metadata_source") != "auto":
        entry["metadata_source"] = "auto"
        changed = True
    return changed


def index_path(work_dir: str) -> Path:
    return Path(work_dir).resolve() / INDEX_FILENAME


def load_image_code_index(work_dir: str) -> dict[str, Any]:
    path = index_path(work_dir)
    if not path.exists():
        return {"version": 1, "images": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "images": {}}


def save_image_code_index(work_dir: str, index: dict[str, Any]) -> None:
    index["version"] = 1
    index["updated_at"] = datetime.now(timezone.utc).isoformat()
    index_path(work_dir).write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _notebook_paths(work_dir: str) -> list[Path]:
    root = Path(work_dir).resolve()
    main_notebook = root / "notebook.ipynb"
    paths: list[Path] = []
    if main_notebook.exists():
        paths.append(main_notebook)
    for path in sorted(root.glob("*.ipynb")):
        if path.name != main_notebook.name:
            paths.append(path)
    return paths


def _work_root(work_dir: str) -> Path:
    return Path(work_dir).resolve()


def _safe_relative_image_path(root: Path, candidate: Path) -> Path | None:
    try:
        resolved_root = root.resolve()
        resolved_candidate = candidate.resolve()
        resolved_candidate.relative_to(resolved_root)
    except Exception:
        return None
    if resolved_candidate.exists() and resolved_candidate.is_file() and is_image_file(resolved_candidate.name):
        return resolved_candidate
    return None


def _resolve_image_path(work_dir: str, filename: str) -> Path | None:
    """解析图片路径，统一处理绝对路径、章节相对路径和 basename 入参。

    先按原样解析；若前端或旧路由把章节路径裁成 basename，则在工作目录内
    查找唯一同名图片。返回值始终为 work_dir 内部的绝对 Path。
    """
    root = _work_root(work_dir)
    raw = str(filename or "").replace("\\", "/").strip()
    if not raw:
        return None

    raw_path = Path(raw)
    if raw_path.is_absolute():
        direct = _safe_relative_image_path(root, raw_path)
    else:
        image_key = normalize_image_key(raw)
        direct = _safe_relative_image_path(root, root / image_key)
    if direct:
        return direct

    basename = Path(raw).name
    if not basename:
        return None
    matches = sorted(
        path.resolve()
        for path in root.rglob(basename)
        if path.is_file() and is_image_file(path.name)
    )
    if len(matches) == 1:
        return matches[0]
    return None


def _rel_to_work_dir(work_dir: str, path: Path) -> str:
    root = _work_root(work_dir)
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        # 理论上不会发生；兜住异常，避免 API 500。
        rel = Path(resolved.name)
    return str(rel).replace("\\", "/")


def update_image_code_index(
    work_dir: str,
    code: str,
    *,
    cell_index: int | None = None,
    section: str | None = None,
    image_names: list[str] | None = None,
) -> list[str]:
    images = image_names if image_names is not None else extract_saved_images(code)
    if not images:
        return []

    index = load_image_code_index(work_dir)
    image_map = index.setdefault("images", {})
    now = datetime.now(timezone.utc).isoformat()
    for image in images:
        image_key = normalize_image_key(image)
        existing = image_map.get(image_key, {})
        metadata = build_image_description(image_key, code, section)
        preserve_metadata = existing.get("metadata_source") == "ai_revision"
        image_map[image_key] = {
            "filename": image_key,
            "basename": Path(image_key).name,
            "code": code,
            "cell_index": cell_index,
            "section": section or "",
            "description": existing.get("description") if preserve_metadata else metadata["description"],
            "alt_text": existing.get("alt_text") if preserve_metadata else metadata["alt_text"],
            "caption": existing.get("caption") if preserve_metadata else metadata["caption"],
            "metadata_source": "ai_revision" if preserve_metadata else "auto",
            "updated_at": now,
        }
    save_image_code_index(work_dir, index)
    return images


def rebuild_image_code_index_from_notebook(work_dir: str) -> dict[str, Any]:
    notebook_paths = _notebook_paths(work_dir)
    previous_images = load_image_code_index(work_dir).get("images", {})
    index: dict[str, Any] = {"version": 1, "images": {}}
    if not notebook_paths:
        save_image_code_index(work_dir, index)
        return index

    for notebook_path in notebook_paths:
        nb = nbformat.read(str(notebook_path), as_version=4)
        is_main = notebook_path.name == "notebook.ipynb"
        section = "" if is_main else notebook_path.stem
        code_cell_index = -1
        for cell in nb.cells:
            if cell.get("cell_type") != "code":
                continue
            code_cell_index += 1
            code = cell.get("source", "")
            for image in extract_saved_images(code):
                image_key = normalize_image_key(image)
                existing = previous_images.get(image_key) or index["images"].get(image_key, {})
                metadata = build_image_description(image_key, code, section)
                preserve_metadata = existing.get("metadata_source") == "ai_revision"
                resolved_cell_index = code_cell_index if is_main else existing.get("cell_index")
                index["images"][image_key] = {
                    "filename": image_key,
                    "basename": Path(image_key).name,
                    "code": code,
                    "cell_index": resolved_cell_index,
                    "section": section,
                    "description": existing.get("description") if preserve_metadata else metadata["description"],
                    "alt_text": existing.get("alt_text") if preserve_metadata else metadata["alt_text"],
                    "caption": existing.get("caption") if preserve_metadata else metadata["caption"],
                    "metadata_source": "ai_revision" if preserve_metadata else "auto",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }

    save_image_code_index(work_dir, index)
    return index


def get_image_code_entry(work_dir: str, filename: str) -> dict[str, Any] | None:
    """查找图片对应的代码条目。

    查找策略（按优先级）：
    1. 索引文件 `.image_code_index.json`（Coder 运行时写入）
    2. 同名 `.py` 配对文件
    3. 从 notebook 反向扫描 savefig 调用
    """
    image_path = _resolve_image_path(work_dir, filename)
    if not image_path:
        return None

    image_key = _rel_to_work_dir(work_dir, image_path)

    # 策略 1：从索引文件查找（最常见的命中路径）
    index = load_image_code_index(work_dir)
    image_map = index.get("images", {})
    # 尝试多种 key 格式匹配（完整相对路径、basename、normalize 后的 key）
    entry = (
        image_map.get(image_key)
        or image_map.get(normalize_image_key(filename))
        or image_map.get(image_path.name)
    )
    if entry and str(entry.get("code") or "").strip():
        _ensure_entry_metadata(entry)
        return entry

    # 策略 2：同名 .py 配对文件
    paired_code_path = image_path.with_suffix(".py")
    if paired_code_path.exists():
        code = paired_code_path.read_text(encoding="utf-8", errors="ignore")
        try:
            section = str(image_path.parent.resolve().relative_to(_work_root(work_dir))).replace("\\", "/")
        except ValueError:
            section = ""
        if section == ".":
            section = ""

        metadata = build_image_description(image_key, code, section)
        return {
            "filename": image_key,
            "basename": image_path.name,
            "code": code,
            "cell_index": None,
            "section": section,
            "description": metadata["description"],
            "alt_text": metadata["alt_text"],
            "caption": metadata["caption"],
            "metadata_source": "paired_py",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    # 策略 3：从 notebook 反向扫描
    basename = image_path.name
    for nb_path in _notebook_paths(work_dir):
        try:
            nb = nbformat.read(str(nb_path), as_version=4)
        except Exception:
            continue
        cell_index = -1
        for cell in nb.cells:
            if cell.get("cell_type") != "code":
                continue
            cell_index += 1
            code = cell.get("source", "")
            for img in extract_saved_images(code):
                if Path(img).name == basename or normalize_image_key(img) == image_key:
                    section = "" if nb_path.name == "notebook.ipynb" else nb_path.stem
                    metadata = build_image_description(image_key, code, section)
                    return {
                        "filename": image_key,
                        "basename": image_path.name,
                        "code": code,
                        "cell_index": cell_index,
                        "section": section,
                        "description": metadata["description"],
                        "alt_text": metadata["alt_text"],
                        "caption": metadata["caption"],
                        "metadata_source": "notebook_scan",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }

    return None


def update_image_metadata(
    work_dir: str,
    filename: str,
    *,
    description: str | None = None,
    alt_text: str | None = None,
    caption: str | None = None,
    metadata_source: str = "llm",
) -> dict[str, Any] | None:
    image_path = _resolve_image_path(work_dir, filename)
    if not image_path:
        return None

    image_key = _rel_to_work_dir(work_dir, image_path)
    index = load_image_code_index(work_dir)
    entry = index.setdefault("images", {}).get(image_key)
    if not entry:
        paired_code_path = image_path.with_suffix(".py")
        code = paired_code_path.read_text(encoding="utf-8", errors="ignore") if paired_code_path.exists() else ""
        try:
            section = str(image_path.parent.resolve().relative_to(_work_root(work_dir))).replace("\\", "/")
        except ValueError:
            section = ""
        metadata = build_image_description(image_key, code, section)
        entry = {
            "filename": image_key,
            "basename": image_path.name,
            "code": code,
            "cell_index": None,
            "section": section,
            "description": metadata["description"],
            "alt_text": metadata["alt_text"],
            "caption": metadata["caption"],
            "metadata_source": "auto",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        index["images"][image_key] = entry

    if description is not None:
        entry["description"] = description.strip()
    if alt_text is not None:
        entry["alt_text"] = alt_text.strip()
    if caption is not None:
        entry["caption"] = caption.strip()
    entry["metadata_source"] = metadata_source
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_image_code_index(work_dir, index)
    return entry


def get_notebook_code_cells(work_dir: str) -> list[str]:
    notebook_path = _work_root(work_dir) / "notebook.ipynb"
    if not notebook_path.exists():
        return []
    nb = nbformat.read(str(notebook_path), as_version=4)
    return [
        cell.get("source", "")
        for cell in nb.cells
        if cell.get("cell_type") == "code"
    ]


def image_exists(work_dir: str, filename: str) -> bool:
    return _resolve_image_path(work_dir, filename) is not None
