"""Safe GET /paper preview and final-paper repair.

Design rule:
- `res.md` is the final output file and must not be overwritten by partial checkpoints.
- While the workflow is still running, this route returns a generated preview from completed
  sections only, with a clear "generating" banner.
- Only after checkpoint.completed=True may this route repair/write `res.md`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from app.models.user_output import clean_final_paper_markdown
from app.utils.artifact_edits import apply_artifact_patches_to_markdown
from app.utils.common_utils import get_work_dir
from app.utils.log_util import logger

router = APIRouter()

BASE_SEQ = ["firstPage", "toc", "RepeatQues", "analysisQues", "modelAssumption", "symbol", "eda"]
TAIL_SEQ = ["sensitivity_analysis", "judge"]
SECTION_LABELS = {
    "firstPage": "标题、摘要、关键词",
    "toc": "目录",
    "RepeatQues": "问题重述",
    "analysisQues": "问题分析",
    "modelAssumption": "模型假设",
    "symbol": "符号说明和数据预处理",
    "eda": "描述性统计 / EDA",
    "sensitivity_analysis": "模型分析与检验",
    "judge": "模型评价、改进与推广",
}


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning(f"read paper failed {path}: {exc}")
        return ""


def _write_text(path: Path, text: str) -> None:
    try:
        path.write_text(text, encoding="utf-8")
    except Exception as exc:
        logger.warning(f"write paper failed {path}: {exc}")


def _checkpoint(work_dir: str) -> dict[str, Any]:
    path = Path(work_dir) / "workflow_checkpoint.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning(f"read checkpoint failed {path}: {exc}")
        return {}


def _content(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("response_content") or "").strip()
    return str(value or "").strip()


def _ques_count(checkpoint: dict[str, Any], res: dict[str, Any]) -> int:
    coord = checkpoint.get("coordinator")
    if isinstance(coord, dict):
        try:
            return int(coord.get("ques_count") or 0)
        except Exception:
            pass
    nums = [int(k[4:]) for k in res if k.startswith("ques") and k[4:].isdigit()]
    return max(nums) if nums else 0


def _expected_seq(q_count: int) -> list[str]:
    return [*BASE_SEQ, *[f"ques{i}" for i in range(1, q_count + 1)], *TAIL_SEQ]


def _section_label(key: str) -> str:
    if key.startswith("ques") and key[4:].isdigit():
        return f"问题{int(key[4:])}模型建立与求解"
    return SECTION_LABELS.get(key, key)


def _toc(q_count: int) -> str:
    lines = ["## 目录", "", "一、问题重述", "1.1 问题背景", "1.2 问题重述", "", "二、问题分析"]
    for i in range(1, q_count + 1):
        lines.append(f"2.{i} 问题{i}的分析")
    lines += ["", "三、模型假设", "", "四、符号说明和数据预处理", "4.1 符号说明", "4.2 描述性统计", "", "五、模型的建立与求解"]
    for i in range(1, q_count + 1):
        lines += [f"5.{i} 问题{i}模型的建立与求解", f"5.{i}.1 模型的建立", f"5.{i}.2 模型的求解"]
    lines += ["", "六、模型的分析与检验", "6.1 灵敏度分析", "", "七、模型的评价、改进与推广"]
    return "\n".join(lines)


def _available_sections(res: dict[str, Any], q_count: int) -> list[str]:
    available: list[str] = []
    for key in _expected_seq(q_count):
        if key == "toc":
            # TOC can be deterministically previewed once the task has been parsed.
            available.append(key)
            continue
        if _content(res.get(key)):
            available.append(key)
    return available


def _missing_sections(res: dict[str, Any], q_count: int) -> list[str]:
    missing: list[str] = []
    for key in _expected_seq(q_count):
        if key == "toc":
            continue
        if not _content(res.get(key)):
            missing.append(key)
    return missing


def _assemble_from_checkpoint(
    work_dir: str,
    *,
    include_toc: bool = True,
) -> tuple[str, list[str], list[str]]:
    cp = _checkpoint(work_dir)
    res = cp.get("user_output_res")
    if not isinstance(res, dict) or not res:
        return "", [], []

    q_count = _ques_count(cp, res)
    seq = _expected_seq(q_count)
    parts: list[str] = []
    included: list[str] = []
    for key in seq:
        text = _content(res.get(key))
        if not text and key == "toc" and include_toc:
            text = _toc(q_count)
        # Important: do NOT synthesize judge, assumptions, question sections, etc.
        # Fake sections made incomplete papers look complete and polluted res.md.
        if text:
            included.append(key)
            parts.append(text)

    if not parts:
        return "", [], _missing_sections(res, q_count)

    return clean_final_paper_markdown("\n\n".join(parts)), included, _missing_sections(res, q_count)


def _apply_patches(text: str, work_dir: str) -> str:
    try:
        return apply_artifact_patches_to_markdown(text, work_dir)
    except Exception as exc:
        logger.warning(f"apply artifact edit patches failed: {exc}")
        return text


def _is_complete_checkpoint(checkpoint: dict[str, Any]) -> bool:
    return bool(checkpoint.get("completed"))


def _status_banner(included: list[str], missing: list[str]) -> str:
    included_labels = "、".join(_section_label(k) for k in included[:12]) or "暂无"
    missing_labels = "、".join(_section_label(k) for k in missing[:12]) or "暂无"
    if len(missing) > 12:
        missing_labels += f" 等 {len(missing)} 项"
    return (
        "> **当前为生成中预览，不是最终论文。**\n"
        f"> 已生成章节：{included_labels}。\n"
        f"> 待生成章节：{missing_labels}。\n\n"
    )


def _final_candidate_from_checkpoint(checkpoint: dict[str, Any]) -> str:
    final = checkpoint.get("final_paper_review")
    return final if isinstance(final, str) and final.strip() else ""


@router.get("/paper")
async def get_paper(task_id: str):
    work_dir = get_work_dir(task_id)
    md_path = Path(work_dir) / "res.md"
    cp = _checkpoint(work_dir)
    completed = _is_complete_checkpoint(cp)

    # Final mode: only completed workflows are allowed to repair/write res.md.
    if completed:
        current = _read_text(md_path)
        final_from_checkpoint = _final_candidate_from_checkpoint(cp)
        rebuilt, included, missing = _assemble_from_checkpoint(work_dir)
        candidate = final_from_checkpoint or current or rebuilt
        candidate = _apply_patches(candidate, work_dir)
        if candidate and candidate != current:
            _write_text(md_path, candidate)
        return {
            "content": candidate,
            "complete": True,
            "preview": False,
            "included_sections": included,
            "missing_sections": missing,
        }

    # Running / incomplete mode: return preview only. Never write res.md here.
    preview, included, missing = _assemble_from_checkpoint(work_dir)
    if preview:
        preview = _apply_patches(preview, work_dir)
        return {
            "content": _status_banner(included, missing) + preview,
            "complete": False,
            "preview": True,
            "included_sections": included,
            "missing_sections": missing,
        }

    # If no checkpoint section has been produced yet, keep current res.md read-only.
    # This preserves old finished files without letting partial repair pollute them.
    current = _read_text(md_path)
    if current:
        return {
            "content": _status_banner([], []) + current,
            "complete": False,
            "preview": True,
            "included_sections": [],
            "missing_sections": [],
        }

    return {
        "content": "> **当前论文还未生成。**\n\n请等待 EDA、各问题求解和写作阶段完成后再查看完整论文。\n",
        "complete": False,
        "preview": True,
        "included_sections": [],
        "missing_sections": [],
    }
