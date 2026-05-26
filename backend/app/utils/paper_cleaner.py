"""Paper-level cleanup helpers.

The final paper is a Chinese mathematical-modeling paper. Runtime image paths may
contain English filenames, but visible text in the rendered paper should not degrade
into filenames or mixed English/Chinese labels.
"""

from __future__ import annotations

import os
import re

IMAGE_EXT = r"png|jpg|jpeg|svg|webp|gif|bmp|tiff"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)+)\s*(.*)$")

TOP_LEVEL_HEADINGS = {
    "一": "一、问题重述",
    "二": "二、问题分析",
    "三": "三、模型假设",
    "四": "四、符号说明和数据预处理",
    "五": "五、模型的建立与求解",
    "六": "六、模型的分析与检验",
    "七": "七、模型的评价、改进与推广",
}

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


def normalize_math_delimiters(text: str) -> str:
    """Convert LLM-friendly math delimiters into Pandoc/KaTeX-friendly Markdown."""
    if not text:
        return ""

    cleaned = text

    def display_repl(match: re.Match[str]) -> str:
        tex = match.group(1).strip()
        return f"\n$$\n{tex}\n$$\n" if tex else ""

    def inline_repl(match: re.Match[str]) -> str:
        tex = match.group(1).strip()
        return f"${tex}$" if tex else ""

    cleaned = re.sub(r"\\\[\s*([\s\S]*?)\s*\\\]", display_repl, cleaned)
    cleaned = re.sub(r"\\\(([^\n]+?)\\\)", inline_repl, cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def clean_strikethrough_markup(text: str) -> str:
    """Remove accidental deletion markup while preserving the visible words."""
    if not text:
        return ""
    cleaned = text
    cleaned = re.sub(r"<del>([\s\S]*?)</del>", r"\1", cleaned, flags=re.I)
    cleaned = re.sub(r"\\sout\{([^{}]*)\}", r"\1", cleaned)
    cleaned = re.sub(r"~~([^~\n][\s\S]*?[^~\n])~~", r"\1", cleaned)
    return cleaned


def _strip_heading_markup(title: str) -> str:
    title = (title or "").strip()
    title = re.sub(r"^\*\*(.*?)\*\*$", r"\1", title)
    title = re.sub(r"^#+\s*", "", title)
    return title.strip()


def _canonical_heading(title: str) -> tuple[str | None, str]:
    raw = _strip_heading_markup(title)
    compact = re.sub(r"\s+", "", raw)

    if compact == "摘要":
        return "abstract", "# 摘要"
    if compact == "目录":
        return "toc", "## 目录"
    if compact == "参考文献":
        return "refs", "# 参考文献"

    top_match = re.match(r"^([一二三四五六七])、", compact)
    if top_match:
        cn = top_match.group(1)
        return f"top:{cn}", f"# {TOP_LEVEL_HEADINGS.get(cn, raw)}"

    numbered_match = NUMBERED_HEADING_RE.match(raw)
    if numbered_match:
        number = numbered_match.group(1)
        rest = numbered_match.group(2).strip()
        depth = min(number.count(".") + 1, 6)
        heading_text = f"{number} {rest}".strip()
        return f"num:{number}", f"{'#' * depth} {heading_text}"

    return None, f"# {raw}" if raw == "摘要" else title.strip()


def _split_heading_blocks(text: str) -> list[tuple[str | None, list[str]]]:
    blocks: list[tuple[str | None, list[str]]] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        if HEADING_RE.match(line):
            blocks.append((current_heading, current_lines))
            current_heading = line
            current_lines = []
        else:
            current_lines.append(line)
    blocks.append((current_heading, current_lines))
    return blocks


def normalize_paper_structure(text: str) -> str:
    """Normalize final-paper headings and remove repeated section fragments.

    Parallel writers sometimes repeat parent sections inside a child section, e.g.
    EDA repeats "四、符号说明" or the first question downgrades "五、模型..." to
    ``##``. This pass keeps the original order, but canonicalizes section levels
    and drops duplicate heading blocks so later sections cannot be nested under
    the wrong parent.
    """
    if not text:
        return ""

    seen_keys: set[str] = set()
    output: list[str] = []
    for heading, body in _split_heading_blocks(text):
        if heading is None:
            if body:
                output.extend(body)
            continue

        match = HEADING_RE.match(heading)
        if not match:
            output.append(heading)
            output.extend(body)
            continue

        key, canonical = _canonical_heading(match.group(2))
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
            output.append(canonical)
        else:
            output.append(heading.rstrip())
        output.extend(body)

    cleaned = "\n".join(output)

    if "top:四" not in seen_keys and re.search(r"^##\s+4\.1\b", cleaned, re.M):
        cleaned = re.sub(
            r"(?m)^(##\s+4\.1\b)",
            "# 四、符号说明和数据预处理\n\n\\1",
            cleaned,
            count=1,
        )
    if "top:五" not in seen_keys and re.search(r"^##\s+5\.1\b", cleaned, re.M):
        cleaned = re.sub(
            r"(?m)^(##\s+5\.1\b)",
            "# 五、模型的建立与求解\n\n\\1",
            cleaned,
            count=1,
        )

    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _dedupe_repeated_paragraphs(text: str) -> str:
    if not text:
        return ""

    chunks = re.split(r"\n{2,}", text)
    seen: set[str] = set()
    output: list[str] = []
    for chunk in chunks:
        stripped = chunk.strip()
        if not stripped:
            continue
        norm = re.sub(r"\s+", "", stripped)
        norm = re.sub(r"[\*_`#>\-—，。；：,.!?！？、（）()\[\]{}]+", "", norm)
        should_check = len(norm) >= 120 and not stripped.startswith("|")
        if should_check and norm in seen:
            continue
        if should_check:
            seen.add(norm)
        output.append(stripped)
    return "\n\n".join(output)


def normalize_reference_definitions(text: str) -> str:
    """Move Markdown footnote definitions into a single references section."""
    if not text:
        return ""

    lines = text.splitlines()
    body: list[str] = []
    refs: list[str] = []
    seen_refs: set[str] = set()
    for line in lines:
        match = re.match(r"^\[\^(\d+)\]:\s*(.+?)\s*$", line.strip())
        if not match:
            body.append(line)
            continue
        ref_line = f"[^{match.group(1)}]: {match.group(2).strip()}"
        if ref_line not in seen_refs:
            refs.append(ref_line)
            seen_refs.add(ref_line)

    cleaned = "\n".join(body).strip()
    if not refs:
        return cleaned

    if re.search(r"^#{1,6}\s+参考文献\s*$", cleaned, re.M):
        return cleaned.rstrip() + "\n\n" + "\n\n".join(refs)
    return cleaned.rstrip() + "\n\n# 参考文献\n\n" + "\n\n".join(refs)


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
    cleaned = normalize_math_delimiters(text)
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
    cleaned = clean_strikethrough_markup(cleaned)
    cleaned = clean_duplicate_raw_math(cleaned)
    cleaned = clean_markdown_images(cleaned)
    cleaned = normalize_reference_definitions(cleaned)
    cleaned = normalize_paper_structure(cleaned)
    cleaned = _dedupe_repeated_paragraphs(cleaned)
    cleaned = _clean_common_english_labels(cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + "\n" if cleaned.strip() else ""
