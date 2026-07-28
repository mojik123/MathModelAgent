"""Cleanup helpers for invalid or empty display-math placeholders."""

from __future__ import annotations

import re


def clean_empty_display_math_blocks(text: str) -> str:
    """Remove empty or unmatched display-math delimiters without touching valid formulas.

    LLM output occasionally contains blocks such as::

        $$

        $$

    or a single unmatched ``$$`` line. Markdown renderers then show the delimiters as
    ordinary text. This scanner removes only empty/unmatched delimiter blocks and keeps
    any block that contains real TeX content.
    """
    if not text:
        return ""

    lines = text.splitlines()
    output: list[str] = []
    index = 0

    while index < len(lines):
        if lines[index].strip() != "$$":
            output.append(lines[index])
            index += 1
            continue

        closing = index + 1
        while closing < len(lines) and lines[closing].strip() != "$$":
            closing += 1

        if closing >= len(lines):
            # A lone delimiter cannot form a valid display equation.
            index += 1
            continue

        body = "\n".join(lines[index + 1 : closing]).strip()
        if body:
            output.extend(lines[index : closing + 1])
        elif (
            output
            and output[-1].strip()
            and closing + 1 < len(lines)
            and lines[closing + 1].strip()
        ):
            output.append("")
        index = closing + 1

    cleaned = "\n".join(output)
    cleaned = re.sub(r"(?m)^[ \t]*\${4}[ \t]*$", "", cleaned)
    cleaned = re.sub(r"(?m)^[ \t]*\$\$[ \t]+\$\$[ \t]*$", "", cleaned)
    cleaned = re.sub(r"\\\[\s*\\\]", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + "\n" if cleaned.strip() else ""
