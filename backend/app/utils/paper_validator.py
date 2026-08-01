from __future__ import annotations

from pathlib import Path
from app.utils.image_constants import MARKDOWN_IMAGE_RE


def validate_markdown_image_refs(work_dir: str, markdown: str) -> list[str]:
    """校验 Markdown 中的本地图片路径存在且指向唯一文件。"""
    issues: list[str] = []
    root = Path(work_dir).resolve()

    for match in MARKDOWN_IMAGE_RE.finditer(markdown or ""):
        raw_path = match.group(2).split("#")[0].split("?")[0].strip()
        if not raw_path:
            issues.append("存在空图片路径")
            continue
        if raw_path.startswith(("http://", "https://", "data:")):
            continue

        img_path = (root / raw_path).resolve()
        try:
            img_path.relative_to(root)
        except ValueError:
            issues.append(f"Markdown 图片引用越出任务目录：{raw_path}")
            continue

        if not img_path.exists():
            # 兼容只写 basename 的情况：先查根目录，再递归查子目录
            basename_path = root / Path(raw_path).name
            if not basename_path.exists():
                candidates = [
                    path
                    for path in root.rglob(Path(raw_path).name)
                    if path.is_file()
                ]
                if not candidates:
                    issues.append(f"Markdown 图片引用不存在：{raw_path}")
                elif len(candidates) > 1:
                    issues.append(
                        f"Markdown 图片引用不明确：{raw_path} 匹配到 "
                        f"{len(candidates)} 个文件，请使用章节相对路径"
                    )

    return list(dict.fromkeys(issues))
