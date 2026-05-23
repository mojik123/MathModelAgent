"""图片相关常量与工具函数，作为全项目图片命名与扩展名的唯一权威来源。"""

from __future__ import annotations

import re
from pathlib import Path

# ---- 图片扩展名 ----

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg")

# 用于构建正则的扩展名片段，不含点号前缀
_IMAGE_EXT_NAMES = "|".join(ext.lstrip(".") for ext in IMAGE_EXTENSIONS)

# 匹配图片扩展名的正则片段（可嵌入其他正则）
IMAGE_EXTENSION_RE_FRAGMENT = rf"(?:{_IMAGE_EXT_NAMES})"

# 完整匹配图片文件名的正则
IMAGE_EXTENSION_RE = re.compile(rf"\.{IMAGE_EXTENSION_RE_FRAGMENT}$", re.IGNORECASE)

# savefig 调用中提取图片路径的正则
SAVEFIG_RE = re.compile(
    rf"(?:[\w.]+\.)?savefig\(\s*[^)]*?"
    rf"(?P<quote>['\"])(?P<path>[^'\"]+\.{IMAGE_EXTENSION_RE_FRAGMENT})(?P=quote)",
    re.IGNORECASE | re.DOTALL,
)

# Markdown 图片引用正则
MARKDOWN_IMAGE_RE = re.compile(
    rf"!\[(.*?)\]\((.*?\.{IMAGE_EXTENSION_RE_FRAGMENT}(?:[?#][^)]+)?)\)",
    re.IGNORECASE,
)

# ---- 图片命名规范（与 coder prompt 一致） ----

# Canonical generated-figure naming rule:
#   {short_english_slug}.png  — or  {tag}_{short_english_slug}.png
# The section/question information is already represented by the folder name
# (e.g. 5.1_问题1的模型建立与求解/), so image filenames must NOT include
# section numbers such as "5.1_".  The name must use only ASCII letters,
# digits, underscores, hyphens — NO Chinese characters, no spaces.
# For backup/racing agents, the filename may start with bN_ or rN_.
#
# Examples:
#   prediction_result.png
#   model_diagnostics.png
#   b1_prediction_result.png
#   r1_prediction_result.png
IMAGE_NAMING_PATTERN = re.compile(
    r"^(?:[A-Za-z0-9][A-Za-z0-9_\-]*|(?:b\d+|r\d+)_[A-Za-z0-9][A-Za-z0-9_\-]*)\.png$",
)


def is_image_file(filename: str | Path) -> bool:
    """判断文件名是否为支持的图片格式。"""
    return Path(str(filename)).suffix.lower() in IMAGE_EXTENSIONS


def validate_image_filename(filename: str) -> tuple[bool, str]:
    """校验图片文件名是否符合命名规范。

    Args:
        filename: 图片文件名（不含路径）。

    Returns:
        (是否合规, 不合规原因或空字符串)。
    """
    name = Path(str(filename)).name

    if not is_image_file(name):
        return False, f"扩展名不在支持列表中：{Path(name).suffix}"

    if not IMAGE_NAMING_PATTERN.match(name):
        return False, (
            "Invalid image filename. Expected {section_num}_{english_slug}.png "
            "(ASCII letters/digits/underscore/hyphen only, no Chinese), "
            "e.g. 4.2_data_distribution.png, 5.1_prediction_comparison.png, "
            "5.2_confusion_matrix.png, 6.1_sensitivity_regularization.png. "
            f"Got: {name}"
        )

    return True, ""


def normalize_image_filename(filename: str) -> str:
    """规范化图片文件名：去除路径，仅保留基本名。"""
    return Path(str(filename).replace("\\", "/")).name


# ---- 论文章节 → 子目录映射 ----

# 会生成图片的章节 → 论文编号
_SECTION_NUMBERING: dict[str, str] = {
    "eda": "4.2",
    "sensitivity_analysis": "6.1",
}

# 章节 key → 简短中文标签（拼接目录名用）
_SECTION_LABEL: dict[str, str] = {
    "eda": "描述性统计",
    "sensitivity_analysis": "灵敏度分析",
}


def section_dir_name(section_key: str, ques_count: int = 0) -> str:
    """将章节 key 转换为工作目录下的子目录名。

    格式为 ``{论文编号}_{简短标识}``，如 ``4.2_描述性统计``。

    Args:
        section_key: 章节标识（如 ``"ques1"``、``"eda"``）。
        ques_count: 问题总数，用于验证 quesN 的 N 是否合法。

    Returns:
        子目录名（不含父路径）。

    Raises:
        ValueError: section_key 不合法。
    """
    if section_key in _SECTION_NUMBERING:
        num = _SECTION_NUMBERING[section_key]
    elif section_key.startswith("ques"):
        try:
            n = int(section_key[4:])
        except ValueError:
            raise ValueError(f"无效的章节 key: {section_key}")
        if ques_count and n > ques_count:
            raise ValueError(f"问题编号超出范围: {section_key} (共 {ques_count} 个问题)")
        num = f"5.{n}"
    else:
        raise ValueError(f"未知的章节 key: {section_key}")

    label = _SECTION_LABEL.get(section_key)
    if not label:
        raise ValueError(f"缺少章节标签: {section_key}")
    return f"{num}_{label}"


def set_section_labels(ques_count: int) -> None:
    """根据问题数量填充 quesN 的目录标签。

    应在 CoordinatorAgent 返回问题数量后立即调用。

    Args:
        ques_count: 问题总数。
    """
    for i in range(1, ques_count + 1):
        key = f"ques{i}"
        _SECTION_NUMBERING[key] = f"5.{i}"
        _SECTION_LABEL[key] = f"问题{i}的模型建立与求解"


def get_all_section_keys(ques_count: int) -> list[str]:
    """返回所有会生成图片的章节 key 列表（按论文顺序）。"""
    keys: list[str] = ["eda"]
    for i in range(1, ques_count + 1):
        keys.append(f"ques{i}")
    keys.append("sensitivity_analysis")
    return keys


def get_section_num(section_key: str) -> str | None:
    """返回章节 key 对应的论文编号（如 "ques1" → "5.1"，"eda" → "4.2"）。

    主要供代码解释器在扫描根目录时按前缀过滤图片，防止并行 Agent 互相误拾取。

    Args:
        section_key: 章节标识（如 ``"ques1"``、``"eda"``、``"sensitivity_analysis"``）。

    Returns:
        论文编号字符串（如 ``"5.1"``），若 key 不在已注册列表中则返回 ``None``。
    """
    return _SECTION_NUMBERING.get(section_key)
