"""Paper-level cleanup helpers.

The final paper is a Chinese mathematical-modeling paper. Runtime image paths may
contain English filenames, but visible text in the rendered paper should not degrade
into filenames or mixed English/Chinese labels.
"""

from __future__ import annotations

import os
import re

IMAGE_EXT = r"png|jpg|jpeg|svg|webp|gif|bmp|tiff"

COMMON_EN_TO_CN = {
    "Abstract": "摘要",
    "Keywords": "关键词",
    "Keyword": "关键词",
    "Problem Restatement": "问题重述",
    "Problem Analysis": "问题分析",
    "Model Assumptions": "模型假设",
    "Assumptions": "模型假设",
    "Symbol Description": "符号说明",
    "Data Preprocessing": "数据预处理",
    "Exploratory Data Analysis": "描述性统计分析",
    "EDA": "描述性统计分析",
    "Model Establishment": "模型建立",
    "Model Solution": "模型求解",
    "Sensitivity Analysis": "灵敏度分析",
    "Model Evaluation": "模型评价",
    "References": "参考文献",
    "Figure": "图",
    "Fig.": "图",
    "Table": "表",
    "Caption": "图注",
    "Description": "说明",
    "Conclusion": "结论",
    "Results": "结果",
    "Discussion": "讨论",
}

FILENAME_TOKEN_MAP = {
    "crop": "作物",
    "crops": "作物",
    "land": "地块",
    "field": "地块",
    "area": "面积",
    "profit": "利润",
    "revenue": "收益",
    "cost": "成本",
    "yield": "产量",
    "sales": "销量",
    "sale": "销售",
    "price": "价格",
    "ratio": "比率",
    "comparison": "对比",
    "compare": "对比",
    "distribution": "分布",
    "histogram": "分布",
    "heatmap": "热力图",
    "timeline": "时间变化",
    "trend": "趋势",
    "sensitivity": "灵敏度",
    "analysis": "分析",
    "matrix": "矩阵",
    "correlation": "相关性",
    "rotation": "轮作",
    "bean": "豆类",
    "beans": "豆类",
    "optimal": "最优",
    "optimization": "优化",
    "suitability": "适宜性",
    "overproduction": "超产",
    "forecast": "预测",
    "prediction": "预测",
    "breakdown": "分解",
}


def has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def looks_like_image_filename(text: str) -> bool:
    s = (text or "").strip().strip("`*_ ")
    if not s:
        return False
    if re.search(rf"\.(?:{IMAGE_EXT})(?:[?#].*)?$", s, re.I):
        return True
    if "/" in s or "\\" in s:
        return True
    if not has_chinese(s) and re.search(r"[A-Za-z]", s) and re.search(r"[_\-]", s):
        return True
    return False


def _filename_to_cn_title(src: str, fallback_index: int | None = None) -> str:
    base = os.path.splitext(os.path.basename((src or "").split("?")[0].split("#")[0]))[0]
    base = re.sub(r"^\d+(?:\.\d+)?[_\-\s]*", "", base)
    tokens = [t for t in re.split(r"[_\-\s]+", base.lower()) if t]
    cn_tokens: list[str] = []
    for token in tokens:
        if token.isdigit() or re.fullmatch(r"[a-f0-9]{6,}", token):
            continue
        mapped = FILENAME_TOKEN_MAP.get(token)
        if mapped and mapped not in cn_tokens:
            cn_tokens.append(mapped)
    title = "".join(cn_tokens[:6])
    if not title:
        title = "结果图"
    if fallback_index is not None:
        return f"图{fallback_index} {title}"
    return title


def clean_visible_image_alt(alt: str, src: str, index: int) -> str:
    value = (alt or "").strip()
    if not value or looks_like_image_filename(value):
        return _filename_to_cn_title(src, index)
    value = re.sub(r"`[^`]*\.(?:" + IMAGE_EXT + r")`", "", value, flags=re.I)
    value = re.sub(r"\([^)]*\.(?:" + IMAGE_EXT + r")[^)]*\)", "", value, flags=re.I)
    value = value.strip(" ：:，,。；;、")
    if not has_chinese(value):
        return _filename_to_cn_title(src, index)
    if not re.match(r"^图\s*\d+", value):
        value = f"图{index} {value}"
    return re.sub(r"\s+", " ", value).strip()


def _line_is_filename_caption(line: str) -> bool:
    stripped = line.strip().strip("> ").strip()
    if not stripped:
        return False
    if looks_like_image_filename(stripped):
        return True
    if re.fullmatch(rf"(?:图\s*\d+\s*)?[^\n\u4e00-\u9fff]*\.(?:{IMAGE_EXT})", stripped, re.I):
        return True
    return False


def _clean_common_english_labels(text: str) -> str:
    cleaned = text
    for en, cn in sorted(COMMON_EN_TO_CN.items(), key=lambda item: -len(item[0])):
        cleaned = re.sub(rf"\b{re.escape(en)}\b", cn, cleaned)
    cleaned = re.sub(r"\bAs illustrated in 图\s*([0-9.]+)\b", r"如图\1所示", cleaned)
    cleaned = re.sub(r"\b图\s*([0-9.]+)\s+shows that\b", r"图\1表明", cleaned, flags=re.I)
    cleaned = re.sub(r"\b图\s*([0-9.]+)\s+depicts that\b", r"图\1表明", cleaned, flags=re.I)
    cleaned = re.sub(r"\bCompared with\b", "与其相比", cleaned, flags=re.I)
    return cleaned


def clean_markdown_images(text: str) -> str:
    if not text:
        return ""
    image_index = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal image_index
        image_index += 1
        alt = match.group(1)
        src = match.group(2).strip()
        cleaned_alt = clean_visible_image_alt(alt, src, image_index)
        return f"![{cleaned_alt}]({src})"

    cleaned = re.sub(
        rf"!\[([^\]]*)\]\(([^)]*\.(?:{IMAGE_EXT})(?:[?#][^)]+)?)\)",
        repl,
        text,
        flags=re.I,
    )

    lines = cleaned.splitlines()
    out: list[str] = []
    previous_nonempty_was_image = False
    for line in lines:
        stripped = line.strip()
        current_is_image = bool(re.fullmatch(rf"!\[[^\]]*\]\([^)]*\.(?:{IMAGE_EXT})(?:[?#][^)]+)?\)", stripped, re.I))
        if previous_nonempty_was_image and _line_is_filename_caption(line):
            continue
        out.append(line)
        if stripped:
            previous_nonempty_was_image = current_is_image
    return "\n".join(out)


def clean_duplicate_raw_math(text: str) -> str:
    if not text:
        return ""
    cleaned = text
    cleaned = re.sub(r"\$\$([\s\S]*?)\$\$\s*\\\[\s*\1\s*\\\]", r"$$\1$$", cleaned)
    cleaned = re.sub(r"\\\[([\s\S]*?)\\\]\s*\$\$\s*\1\s*\$\$", r"\[\1\]", cleaned)
    cleaned = re.sub(
        r"(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\])\s*\n\s*([A-Za-z_\\][^\n\u4e00-\u9fff]{8,})\s*(?=\n|$)",
        r"\1\n",
        cleaned,
    )
    return cleaned


def clean_chinese_paper_markdown(text: str) -> str:
    """Clean visible paper text for Chinese-only presentation."""
    cleaned = text or ""
    cleaned = clean_duplicate_raw_math(cleaned)
    cleaned = clean_markdown_images(cleaned)
    cleaned = _clean_common_english_labels(cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + "\n" if cleaned.strip() else ""
