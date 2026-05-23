from __future__ import annotations

from pathlib import Path
from app.utils.image_constants import MARKDOWN_IMAGE_RE


def validate_markdown_image_refs(work_dir: str, markdown: str) -> list[str]:
    issues: list[str] = []
    root = Path(work_dir)

    for match in MARKDOWN_IMAGE_RE.finditer(markdown or ""):
        raw_path = match.group(2).split("#")[0].split("?")[0].strip()
        if not raw_path:
            issues.append("存在空图片路径")
            continue

        img_path = root / raw_path
        if not img_path.exists():
            # 兼容只写 basename 的情况
            basename_path = root / Path(raw_path).name
            if not basename_path.exists():
                issues.append(f"Markdown 图片引用不存在：{raw_path}")

    return issues
