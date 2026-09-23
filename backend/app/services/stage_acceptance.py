"""Deterministic, model-independent checks for workflow stage acceptance."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


Verdict = str
PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"


def _file(path: str) -> Callable[[Path], tuple[bool, str]]:
    def check(root: Path) -> tuple[bool, str]:
        candidate = root / path
        return (candidate.is_file(), path if candidate.is_file() else f"缺少文件：{path}")

    return check


def _directory_with_files(path: str) -> Callable[[Path], tuple[bool, str]]:
    def check(root: Path) -> tuple[bool, str]:
        candidate = root / path
        present = candidate.is_dir() and any(item.is_file() for item in candidate.rglob("*"))
        return (present, path if present else f"缺少目录或目录为空：{path}")

    return check


def _any_file(*paths: str) -> Callable[[Path], tuple[bool, str]]:
    def check(root: Path) -> tuple[bool, str]:
        for path in paths:
            if (root / path).is_file():
                return True, path
        return False, f"缺少文件之一：{', '.join(paths)}"

    return check


def _any_with_suffix(directory: str, suffixes: set[str]) -> Callable[[Path], tuple[bool, str]]:
    def check(root: Path) -> tuple[bool, str]:
        candidate = root / directory
        if candidate.is_dir():
            for path in candidate.rglob("*"):
                if path.is_file() and path.suffix.lower() in suffixes:
                    return True, path.relative_to(root).as_posix()
        return False, f"{directory} 中缺少可识别源文件"

    return check


def _result_json() -> Callable[[Path], tuple[bool, str]]:
    def check(root: Path) -> tuple[bool, str]:
        directory = root / "results"
        if not directory.is_dir():
            return False, "缺少目录：results/"
        paths = [path for path in directory.glob("*.json") if path.name != "summary.json"]
        if not paths:
            return False, "results/ 中缺少至少一个 q*.json 结果文件"
        for path in paths:
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                return False, f"结果 JSON 无法解析：{path.relative_to(root).as_posix()}"
        return True, ", ".join(path.relative_to(root).as_posix() for path in paths)

    return check


def _json_file(path: str) -> Callable[[Path], tuple[bool, str]]:
    def check(root: Path) -> tuple[bool, str]:
        candidate = root / path
        if not candidate.is_file():
            return False, f"缺少文件：{path}"
        try:
            json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False, f"JSON 无法解析：{path}"
        return True, path

    return check


def _valid_pdf() -> Callable[[Path], tuple[bool, str]]:
    def check(root: Path) -> tuple[bool, str]:
        candidates = [root / "paper" / "main.pdf", root / "res.pdf"]
        candidates.extend(sorted((root / "paper").glob("*.pdf")) if (root / "paper").is_dir() else [])
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                header = candidate.read_bytes()[:5]
                if header != b"%PDF-":
                    continue
                try:
                    import fitz  # type: ignore[import-not-found]

                    with fitz.open(candidate) as document:
                        if document.page_count < 1:
                            continue
                except ImportError:
                    pass
                return True, candidate.relative_to(root).as_posix()
            except (OSError, RuntimeError):
                continue
        return False, "缺少可打开的 PDF：paper/main.pdf 或 res.pdf"

    return check


STAGE_CHECKS: dict[str, tuple[tuple[str, Callable[[Path], tuple[bool, str]]], ...]] = {
    "00-intake": (
        ("RUN_CONTEXT.json", _json_file("RUN_CONTEXT.json")),
        ("INPUT_INVENTORY.json", _json_file("INPUT_INVENTORY.json")),
        ("CAPABILITY_REPORT.json", _json_file("CAPABILITY_REPORT.json")),
        ("TASK_CHECKLIST.md", _file("TASK_CHECKLIST.md")),
        ("STAGE_STATE.json", _json_file("STAGE_STATE.json")),
    ),
    "01-analysis": (
        ("PROBLEM_ANALYSIS.md", _file("PROBLEM_ANALYSIS.md")),
        ("PROBLEM_FACTS.json", _json_file("PROBLEM_FACTS.json")),
        ("CAPABILITY_CHECKLIST.json", _json_file("CAPABILITY_CHECKLIST.json")),
    ),
    "02-modeling": (
        ("MODELING_REPORT.md", _file("MODELING_REPORT.md")),
        ("MODEL_CONTRACT.json", _json_file("MODEL_CONTRACT.json")),
        ("CROSS_PROBLEM_LEDGER.json", _json_file("CROSS_PROBLEM_LEDGER.json")),
    ),
    "03-code": (
        ("code/", _directory_with_files("code")),
        ("results/", _directory_with_files("results")),
        ("results/summary.json", _json_file("results/summary.json")),
        ("results/q*.json", _result_json()),
        ("RESULTS.md", _file("RESULTS.md")),
        ("DELIVERABLES.json", _json_file("DELIVERABLES.json")),
    ),
    "04-validation": (
        ("validation/", _directory_with_files("validation")),
        ("VALIDATION_REPORT.md", _file("VALIDATION_REPORT.md")),
    ),
    "05-figures": (
        ("FIGURE_MANIFEST.json", _json_file("FIGURE_MANIFEST.json")),
        ("figures/", _directory_with_files("figures")),
        ("FIGURE_REPORT.md", _file("FIGURE_REPORT.md")),
    ),
    "06-paper": (
        ("paper/", _directory_with_files("paper")),
        ("paper source", _any_with_suffix("paper", {".tex", ".md", ".docx"})),
        ("PAPER_DATA_CHECKLIST.md", _file("PAPER_DATA_CHECKLIST.md")),
        ("PAPER_REPORT.md", _file("PAPER_REPORT.md")),
    ),
    "07-compile": (
        ("PDF", _valid_pdf()),
        ("COMPILE_REPORT.md", _file("COMPILE_REPORT.md")),
    ),
    "08-final-audit": (
        ("FINAL_AUDIT.md", _file("FINAL_AUDIT.md")),
        ("EVIDENCE_INDEX.md", _file("EVIDENCE_INDEX.md")),
        ("STAGE_STATE.json", _json_file("STAGE_STATE.json")),
    ),
}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _stage_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    history = state.get("history")
    if isinstance(history, list):
        records.extend(record for record in history if isinstance(record, dict))
    stages = state.get("stages")
    if isinstance(stages, list):
        records.extend(record for record in stages if isinstance(record, dict))
    elif isinstance(stages, dict):
        for stage_id, value in stages.items():
            if isinstance(value, dict):
                records.append({"stage": stage_id, **value})
            elif isinstance(value, str):
                records.append({"stage": stage_id, "status": value})
    current = state.get("current_stage")
    if current:
        records.append({"stage": current, "status": state.get("status")})
    return records


def _stage_record(state: dict[str, Any], stage_id: str) -> dict[str, Any] | None:
    found: dict[str, Any] | None = None
    for record in _stage_records(state):
        value = record.get("stage") or record.get("id")
        if value == stage_id or str(value).replace("_", "-").lower() == stage_id:
            found = record
    return found


def _evidence_paths(record: dict[str, Any] | None) -> list[str]:
    if not record:
        return []
    paths: list[str] = []
    for field in ("outputs", "artifacts", "evidence"):
        values = record.get(field, [])
        if isinstance(values, (str, dict)):
            values = [values]
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, str):
                paths.append(value)
            elif isinstance(value, dict):
                path = value.get("path") or value.get("filename")
                if isinstance(path, str):
                    paths.append(path)
    return paths


def validate_stage(task_dir: Path, stage_id: str) -> dict[str, Any]:
    """Return a deterministic verdict without invoking a model or a command."""

    checked_at = datetime.now(timezone.utc).isoformat()
    state_path = task_dir / "STAGE_STATE.json"
    state = _read_json(state_path)
    if state is None:
        return {
            "stage_id": stage_id,
            "verdict": BLOCKED,
            "checked_at": checked_at,
            "state_status": None,
            "missing": ["STAGE_STATE.json"],
            "invalid": [],
            "evidence": [],
            "reasons": ["缺少或无法解析 STAGE_STATE.json"],
        }
    checks = STAGE_CHECKS.get(stage_id)
    if checks is None:
        return {
            "stage_id": stage_id,
            "verdict": BLOCKED,
            "checked_at": checked_at,
            "state_status": None,
            "missing": [],
            "invalid": [],
            "evidence": [],
            "reasons": [f"未知阶段：{stage_id}"],
        }

    record = _stage_record(state, stage_id)
    state_status = str(record.get("status", "")).upper() if record else None
    missing: list[str] = []
    invalid: list[str] = []
    evidence: list[str] = []
    reasons: list[str] = []
    for label, checker in checks:
        ok, detail = checker(task_dir)
        if ok:
            evidence.append(detail)
        elif label == "PDF" or "JSON" in label or "source" in label:
            invalid.append(detail)
        else:
            missing.append(detail)

    if record is None:
        reasons.append("STAGE_STATE.json 中没有当前阶段记录")
    elif not _evidence_paths(record):
        reasons.append("当前阶段没有记录 outputs、artifacts 或 evidence 路径")

    if stage_id == "08-final-audit":
        previous_statuses: dict[str, str] = {}
        for item in _stage_records(state):
            value = item.get("stage") or item.get("id")
            if isinstance(value, str) and value != stage_id:
                previous_statuses[value.replace("_", "-").lower()] = str(item.get("status", "")).upper()
        non_pass = [
            value
            for value in previous_statuses.values()
            if value != PASS
        ]
        if non_pass:
            reasons.append("仍有前置阶段未通过独立验收")

    if state_status in {FAIL, BLOCKED}:
        verdict: Verdict = state_status
        reasons.append(f"阶段状态文件已标记为 {state_status}")
    elif missing or invalid:
        verdict = FAIL if state_status == PASS else BLOCKED
        reasons.append("阶段产物不完整或存在无法解析的文件")
    elif not record or state_status != PASS:
        verdict = BLOCKED
        reasons.append("产物存在，但没有明确的 PASS 状态和完整证据")
    elif stage_id == "08-final-audit" and any(
        reason == "仍有前置阶段未通过独立验收" for reason in reasons
    ):
        verdict = BLOCKED
    else:
        verdict = PASS

    return {
        "stage_id": stage_id,
        "verdict": verdict,
        "checked_at": checked_at,
        "state_status": state_status,
        "missing": missing,
        "invalid": invalid,
        "evidence": evidence,
        "reasons": reasons,
    }
