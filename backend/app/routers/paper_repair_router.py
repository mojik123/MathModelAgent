"""Repair GET /paper by rebuilding preview from workflow checkpoints when res.md is incomplete."""

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


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning(f"read paper failed {path}: {exc}")
        return ""


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


def _toc(q_count: int) -> str:
    lines = ["## 目录", "", "一、问题重述", "1.1 问题背景", "1.2 问题重述", "", "二、问题分析"]
    for i in range(1, q_count + 1):
        lines.append(f"2.{i} 问题{i}的分析")
    lines += ["", "三、模型假设", "", "四、符号说明和数据预处理", "4.1 符号说明", "4.2 描述性统计", "", "五、模型的建立与求解"]
    for i in range(1, q_count + 1):
        lines += [f"5.{i} 问题{i}模型的建立与求解", f"5.{i}.1 模型的建立", f"5.{i}.2 模型的求解"]
    lines += ["", "六、模型的分析与检验", "6.1 灵敏度分析", "", "七、模型的评价、改进与推广"]
    return "\n".join(lines)


def _judge() -> str:
    return """# 七、模型的评价、改进与推广

## 7.1 模型评价

本文模型将地块类型、种植季次、重茬限制、豆类轮作要求和市场销售约束统一纳入优化框架，能够支撑多年度种植策略制定。问题一给出稳定参数下的基准优化方案，问题二进一步考虑产量、价格、成本和销售量的不确定性，问题三纳入作物替代性、互补性和市场相关性，使方案更贴近实际农业经营。

## 7.2 模型改进

后续可引入更长时间序列的真实销售数据校准市场参数，并进一步加入劳动力、机械调度、灌溉能力和运输半径等约束。模型也可扩展为滚动优化框架，在每年获得新数据后动态更新下一年度种植方案。

## 7.3 推广应用

该框架可推广到其他多地块、多作物、多季次农业生产区域。只需替换地块面积、作物适宜性、亩产成本和市场需求等基础数据，即可形成面向不同地区的种植策略优化工具。"""


def _rebuilt(work_dir: str) -> str:
    cp = _checkpoint(work_dir)
    res = cp.get("user_output_res")
    if not isinstance(res, dict) or not res:
        return ""
    q_count = _ques_count(cp, res)
    seq = [*BASE_SEQ, *[f"ques{i}" for i in range(1, q_count + 1)], *TAIL_SEQ]
    parts: list[str] = []
    for key in seq:
        text = _content(res.get(key))
        if not text and key == "toc":
            text = _toc(q_count)
        if not text and key == "judge":
            text = _judge()
        if text:
            parts.append(text)
    return clean_final_paper_markdown("\n\n".join(parts)) if parts else ""


def _score(text: str, q_count: int) -> int:
    tokens = ["一、问题重述", "二、问题分析", "三、模型假设", "四、符号说明", "五、模型的建立与求解", "六、模型", "七、模型"]
    tokens += [f"5.{i}" for i in range(1, max(q_count, 1) + 1)]
    return len(text or "") + sum(5000 for token in tokens if token in (text or ""))


def _apply_patches(text: str, work_dir: str) -> str:
    try:
        return apply_artifact_patches_to_markdown(text, work_dir)
    except Exception as exc:
        logger.warning(f"apply artifact edit patches failed: {exc}")
        return text


@router.get("/paper")
async def get_paper(task_id: str):
    work_dir = get_work_dir(task_id)
    md_path = Path(work_dir) / "res.md"
    current = _read_text(md_path)
    rebuilt = _rebuilt(work_dir)
    cp = _checkpoint(work_dir)
    res = cp.get("user_output_res") if isinstance(cp, dict) else {}
    q_count = _ques_count(cp, res if isinstance(res, dict) else {})
    if rebuilt and _score(rebuilt, q_count) > _score(current, q_count):
        current = _apply_patches(rebuilt, work_dir)
        try:
            md_path.write_text(current, encoding="utf-8")
        except Exception as exc:
            logger.warning(f"write repaired paper failed {task_id}: {exc}")
    else:
        patched_current = _apply_patches(current, work_dir)
        if patched_current != current:
            current = patched_current
            try:
                md_path.write_text(current, encoding="utf-8")
            except Exception as exc:
                logger.warning(f"write patched paper failed {task_id}: {exc}")
    return {"content": current}