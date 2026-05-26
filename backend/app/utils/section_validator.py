"""论文章节输出校验模块。

在 Writer 完成后立即校验章节内容是否合规，
提供多层检查机制，确保终稿结构完整。
"""

from __future__ import annotations

CN_NUM = {1: '一', 2: '二', 3: '三', 4: '四', 5: '五', 6: '六', 7: '七', 8: '八', 9: '九', 10: '十'}


def validate_section_output(
    key: str,
    content: str,
    ques_count: int,
    available_images: list[str] | None = None,
) -> list[str]:
    """校验单个章节输出的内容和结构合规性。

    Args:
        key: 章节标识（如 ``"ques1"``、``"toc"``、``"firstPage"``）。
        content: 章节 Markdown 正文。
        ques_count: 总问题数。
        available_images: 可用图片列表（可选，将来校验图片引用）。

    Returns:
        问题描述列表，空列表表示校验通过。
    """
    issues: list[str] = []
    text = (content or "").strip()

    # ── 基础长度检查 ──
    if len(text) < 300 and key not in ("firstPage", "toc"):
        issues.append(f"{key} 内容过短（{len(text)} 字符，至少 300）")

    # ── 最大长度检查（防止章节过于冗长）──
    max_chars = {
        "ques1": 50000, "ques2": 50000, "ques3": 50000, "ques4": 50000, "ques5": 50000,
        "analysisQues": 30000, "sensitivity_analysis": 30000, "judge": 20000,
        "toc": 15000, "firstPage": 10000, "modelAssumption": 15000, "symbol": 10000,
        "eda": 20000, "RepeatQues": 5000,
    }

    limit = max_chars.get(key, 30000)
    if len(text) > limit:
        issues.append(f"{key} 内容过长（{len(text)} 字符，超过限制 {limit}）")

    # ── 子问题章节检查 ──
    if key.startswith("ques"):
        try:
            n = int(key[4:])
        except ValueError:
            return issues

        cn = CN_NUM.get(n, str(n))
        heading_candidates = [f"5.{n}", f"问题{n}", f"第{n}问", f"问题{cn}", f"第{cn}问"]
        required_tokens = [
            *heading_candidates,
            "模型",
            "求解",
        ]
        heading_ok = any(h in text for h in heading_candidates)
        if not heading_ok:
            issues.append(f"{key} 缺少章节标题标识（5.{n}/问题{n}/问题{cn}）")
        for token in ["模型", "求解"]:
            if token not in text:
                issues.append(f"{key} 缺少必要标识：{token}")

        forbidden_tokens = [
            "一、问题重述",
            "二、问题分析",
            "三、模型假设",
            "七、模型的评价",
        ]
        for token in forbidden_tokens:
            if token in text:
                issues.append(f"{key} 混入其他章节标识：{token}")

    # ── 问题分析章节检查 ──
    if key == "analysisQues":
        for i in range(1, ques_count + 1):
            cn = CN_NUM.get(i, str(i))
            candidates = [
                f"问题{i}",
                f"问题 {i}",
                f"问题{cn}",
                f"问题 {cn}",
                f"第{i}问",
                f"第{cn}问",
            ]
            if not any(token in text for token in candidates):
                issues.append(f"问题分析缺少「问题{i}/问题{cn}」")

    # ── 目录检查 ──
    if key == "toc":
        for i in range(1, ques_count + 1):
            if f"5.{i}" not in text:
                issues.append(f"目录缺少 5.{i} 问题{i}")

    # ── 图片引用检查（简单版） ──
    if available_images:
        for img in available_images:
            import os

            basename = os.path.basename(img)
            if img not in text and basename not in text:
                # 这是 warning 级别的，不阻塞
                pass

    return issues
