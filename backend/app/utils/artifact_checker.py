"""Coder 产物检查：验证代码、图片、章节目录完整性。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.utils.image_constants import is_image_file, validate_image_filename
from app.utils.image_code_index import load_image_code_index


@dataclass
class ArtifactCheckResult:
    passed: bool
    issues: list[str]
    images: list[str]
    code_files: list[str]


def check_section_artifacts(
    work_dir: str,
    section_key: str,
    section_dir: str,
    created_images: list[str],
    require_image: bool = False,
    artifact_tag: str | None = None,
) -> ArtifactCheckResult:
    """检查指定章节的产物完整性。

    Args:
        work_dir: 任务工作目录。
        section_key: 章节标识（如 ``"ques1"``）。
        section_dir: 章节子目录名（如 ``"5.1_问题1的模型建立与求解"``）。
        created_images: 已创建的图片相对路径列表。
        require_image: 是否强制要求至少一张图片。
        artifact_tag: 当前尝试的产物标签（如 ``"b1"``、``"r1"``），
                      ``None`` 表示主力。

    Returns:
        ``ArtifactCheckResult``，``passed=True`` 表示所有检查通过。
    """
    issues: list[str] = []
    images: list[str] = []
    code_files: list[str] = []

    section_path = Path(work_dir) / section_dir

    if not section_path.exists():
        issues.append(f"章节目录不存在：{section_dir}")
        return ArtifactCheckResult(False, issues, images, code_files)

    # 检查图片
    for img in created_images or []:
        img_path = Path(work_dir) / img
        if not img_path.exists():
            img_path = section_path / Path(img).name
        if not img_path.exists():
            issues.append(f"图片文件不存在：{img}")
            continue
        if not is_image_file(img_path.name):
            issues.append(f"不是支持的图片文件：{img_path.name}")
            continue
        ok, reason = validate_image_filename(img_path.name)
        if not ok:
            issues.append(reason)
        images.append(str(img_path.relative_to(work_dir)).replace("\\", "/"))

    if require_image and not images:
        issues.append("本问未生成有效图片")

    # 检查代码文件（按 artifact_tag 严格过滤，避免主力残留"骗过"备用检查）
    if artifact_tag:
        expected_code_name = f"code_{artifact_tag}.py"
        expected_step_pat = f"_{artifact_tag}_step_"
    else:
        expected_code_name = "code.py"
        expected_step_pat = "_step_"

    for path in section_path.glob("*.py"):
        name = path.name
        if artifact_tag:
            if name == expected_code_name or expected_step_pat in name:
                code_files.append(str(path.relative_to(work_dir)).replace("\\", "/"))
        else:
            if name == expected_code_name or (expected_step_pat in name and "_b" not in name and "_r" not in name):
                code_files.append(str(path.relative_to(work_dir)).replace("\\", "/"))

    if not code_files:
        target = f"artifact_tag={artifact_tag or 'main'}"
        issues.append(f"章节目录内没有保存当前尝试的代码文件：{section_dir} ({target})")

    # 检查图片是否写入 .image_code_index.json
    index = load_image_code_index(work_dir)
    image_index = index.get("images", {})
    for img in images:
        img_name = Path(img).name
        if img_name not in image_index:
            issues.append(f"图片未写入 .image_code_index.json：{img_name}")

    return ArtifactCheckResult(
        passed=len(issues) == 0,
        issues=issues,
        images=images,
        code_files=code_files,
    )
