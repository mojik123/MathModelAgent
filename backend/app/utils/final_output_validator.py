from __future__ import annotations

import re
from pathlib import Path


def validate_final_paper(work_dir: str, markdown: str) -> list[str]:
    """检查终稿 Markdown 的章节完整性和基本质量。"""
    issues: list[str] = []

    required_markers = [
        "摘要",
        "关键词",
        "问题重述",
        "问题分析",
        "模型假设",
        "符号",
        "模型",
    ]

    for marker in required_markers:
        if marker not in markdown:
            issues.append(f"终稿缺少关键章节或关键词：{marker}")

    # 仅在存在引用标号（[^1]、[^2] 等）时才要求参考文献章节
    has_citation = bool(re.search(r"\[\^\d+\]", markdown))
    if has_citation and "参考文献" not in markdown:
        issues.append("终稿存在引用标号，但缺少参考文献章节")

    if len(markdown.strip()) < 1500:
        issues.append("终稿内容过短，可能生成不完整")

    if "![ " in markdown or "![]()" in markdown:
        issues.append("存在异常 Markdown 图片引用（空格或空 alt）")

    if re.search(r"^#{1,4}\s*$", markdown, re.MULTILINE):
        issues.append("存在空的 Markdown 标题行")

    duplicate_headings: set[str] = set()
    seen_headings: set[str] = set()
    for match in re.finditer(r"^#{1,6}\s+(.+?)\s*$", markdown, re.MULTILINE):
        title = re.sub(r"\s+", "", match.group(1).strip())
        numbered = re.match(r"^(\d+(?:\.\d+)+)", title)
        chinese = re.match(r"^([一二三四五六七])、", title)
        key = None
        if numbered:
            key = f"num:{numbered.group(1)}"
        elif chinese:
            key = f"top:{chinese.group(1)}"
        elif title in {"摘要", "参考文献"}:
            key = title
        if key and key in seen_headings:
            duplicate_headings.add(title)
        if key:
            seen_headings.add(key)

    if duplicate_headings:
        issues.append(
            "存在重复章节标题："
            + "、".join(sorted(duplicate_headings)[:5])
        )

    if re.search(r"^#{2,6}\s+[一二三四五六七]、", markdown, re.MULTILINE):
        issues.append("一级中文章节被降级为二级或更低标题")

    if re.search(r"~~[^~]+~~|<del>.*?</del>|\\sout\{", markdown, re.DOTALL | re.I):
        issues.append("存在删除线标记，可能导致正文显示为删除状态")

    if re.search(r"\\\[|\\\]|\\\(|\\\)", markdown):
        issues.append("存在未规范化的反斜杠数学定界符，可能导致 LaTeX/PDF 乱码")

    return issues


def validate_saved_files(work_dir: str) -> list[str]:
    """检查 res.md 和 res.json 是否都已保存。"""
    issues: list[str] = []
    root = Path(work_dir)

    if not (root / "res.md").exists():
        issues.append("res.md 缺失")
    if not (root / "res.json").exists():
        issues.append("res.json 缺失")

    return issues
