"""论文与代码执行证据的一致性检查。

该模块只使用任务目录中的实际 Python 代码进行确定性检查，避免 Writer
把建模方案中的预期做法误写成已经执行的事实。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from app.utils.image_constants import section_dir_name

_SOLVER_PATTERNS: dict[str, re.Pattern[str]] = {
    "Gurobi": re.compile(r"\b(?:gp|gurobipy)\.Model\s*\(|\bGUROBI_CMD\s*\(", re.I),
    "CBC": re.compile(r"\b(?:PULP_CBC_CMD|COIN_CMD)\s*\(", re.I),
    "SciPy linprog": re.compile(r"\blinprog\s*\(", re.I),
    "SciPy milp": re.compile(r"\bmilp\s*\(|scipy\.optimize\.milp\s*\(", re.I),
    "OR-Tools CP-SAT": re.compile(r"\bcp_model\.CpModel\s*\(", re.I),
}
_SOLVER_CLAIMS: dict[str, re.Pattern[str]] = {
    "Gurobi": re.compile(
        r"(?:采用|调用|使用|选用|通过)[^。；\n]{0,30}Gurobi"
        r"|Gurobi[^。；\n]{0,20}(?:求解|计算|获得)",
        re.I,
    ),
    "CBC": re.compile(
        r"(?:采用|调用|使用|选用|通过)[^。；\n]{0,30}(?:CBC|COIN)"
        r"|(?:CBC|COIN)[^。；\n]{0,20}(?:求解|计算|获得)",
        re.I,
    ),
    "SciPy linprog": re.compile(
        r"(?:采用|调用|使用|选用|通过)[^。；\n]{0,30}(?:linprog|HiGHS)"
        r"|(?:linprog|HiGHS)[^。；\n]{0,20}(?:求解|计算|获得)",
        re.I,
    ),
    "SciPy milp": re.compile(
        r"(?:采用|调用|使用|选用|通过)[^。；\n]{0,30}scipy[^。；\n]{0,15}milp",
        re.I,
    ),
    "OR-Tools CP-SAT": re.compile(
        r"(?:采用|调用|使用|选用|通过)[^。；\n]{0,30}(?:OR-Tools|CP-SAT)",
        re.I,
    ),
}
_DISCRETE_MODEL_RE = re.compile(
    r"LpBinary|LpInteger|cat\s*=\s*['\"](?:Binary|Integer)['\"]"
    r"|vtype\s*=\s*(?:GRB\.)?(?:BINARY|INTEGER)"
    r"|integrality\s*=|NewBoolVar\s*\(|NewIntVar\s*\(",
    re.I,
)
_MILP_CLAIM_RE = re.compile(r"混合整数(?:线性)?规划|(?<![A-Za-z])MILP(?![A-Za-z])", re.I)
_SCENARIO_NAME_RE = re.compile(
    r"(?:^s$|^s_|_s$|scenario|sample|simulation|n_scen|n_sim|情景)",
    re.I,
)
_PAPER_SCENARIO_PATTERNS = (
    re.compile(
        r"(?<!\d)(\d{2,6})\s*(?:个|组|条)?\s*"
        r"(?:LHS|蒙特卡洛|Copula|联合|训练|优化|随机|评估)?\s*情景",
        re.I,
    ),
    re.compile(r"情景(?:数|数量|规模)?\s*(?:为|=|取)?\s*(\d{2,6})(?!\d)", re.I),
    re.compile(r"\bS(?:_[A-Za-z]+)?\s*=\s*(\d{2,6})(?!\d)", re.I),
)
_CVAR_PERCENTILE_RE = re.compile(
    r"(?im)^\s*(?:cvar\w*|[A-Za-z_]\w+cvar\w*)\s*=\s*"
    r"(?:np\.)?(?:percentile|quantile)\s*\("
)
_HARDCODED_COMPARISON_RE = re.compile(
    r"(?im)^\s*(?:q\d+|model\d+|baseline|optimized|optimal)_values?\s*=\s*"
    r"\[\s*[-+]?\d+(?:\.\d+)?(?:\s*,\s*[-+]?\d+(?:\.\d+)?){2,}\s*\]"
)
_COPIED_RESULT_RE = re.compile(
    r"(?:从|根据)(?:之前|前面|上方)(?:的)?(?:输出|结果)(?:得知|可知)?"
    r"|手动(?:填写|录入|设定)(?:结果|指标)"
    r"|硬编码(?:结果|指标)",
    re.I,
)
_PROXY_SURFACE_RE = re.compile(
    r"def\s+\w*(?:profit|metric|objective)\w*(?:response|surface|proxy)\w*\s*\(",
    re.I,
)


def _canonical_code_files(work_dir: str, section_key: str) -> list[Path]:
    """返回某章节最终胜出尝试的代码文件。"""
    section_path = Path(work_dir) / section_dir_name(section_key)
    if not section_path.exists():
        return []

    main = section_path / "code.py"
    if main.exists():
        return [main]

    fallback_files = sorted(section_path.glob("code_*.py"))
    return [path for path in fallback_files if path.is_file()]


def _read_code_files(paths: list[Path]) -> str:
    return "\n\n".join(
        path.read_text(encoding="utf-8", errors="ignore") for path in paths
    )


def _assignment_name(target: ast.expr) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    return None


def _scenario_counts(code: str) -> list[int]:
    """从实际赋值中提取场景/样本规模，避免把注释数字当作证据。"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    counts: list[int] = []
    for node in ast.walk(tree):
        name: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = _assignment_name(node.targets[0])
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            name = _assignment_name(node.target)
            value = node.value
        if (
            name
            and value is not None
            and _SCENARIO_NAME_RE.search(name)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, int)
            and value.value > 0
        ):
            if value.value not in counts:
                counts.append(value.value)
    return counts


def inspect_code_evidence(code: str) -> dict[str, Any]:
    """提取代码中的可审计证据并识别会污染论文结论的写法。"""
    solvers = [
        solver for solver, pattern in _SOLVER_PATTERNS.items() if pattern.search(code)
    ]
    issues: list[str] = []

    if _CVAR_PERCENTILE_RE.search(code):
        issues.append(
            "代码把单一分位点标记为 CVaR；CVaR 必须计算尾部样本的条件均值"
        )
    if _HARDCODED_COMPARISON_RE.search(code):
        issues.append(
            "比较图指标使用手写数值数组，必须从本次执行结果或结果文件计算"
        )
    if _COPIED_RESULT_RE.search(code):
        issues.append(
            "代码包含从先前输出手工抄录结果的痕迹，结果缺少可重复计算链路"
        )
    if _PROXY_SURFACE_RE.search(code):
        issues.append(
            "代码用手写代理响应面代替原模型重算，不能作为灵敏度分析证据"
        )

    return {
        "solvers": solvers,
        "scenario_counts": _scenario_counts(code),
        "has_discrete_variables": bool(_DISCRETE_MODEL_RE.search(code)),
        "issues": issues,
    }


def inspect_section_evidence(work_dir: str, section_key: str) -> dict[str, Any]:
    """提取指定论文章节对应的代码证据。"""
    root = Path(work_dir)
    code_files = _canonical_code_files(work_dir, section_key)
    code = _read_code_files(code_files)
    evidence = inspect_code_evidence(code)
    evidence["section_key"] = section_key
    evidence["code_files"] = [
        str(path.relative_to(root)).replace("\\", "/") for path in code_files
    ]
    return evidence


def build_writer_evidence_context(work_dir: str, section_key: str) -> str:
    """生成给 Writer 的只读证据摘要。"""
    evidence = inspect_section_evidence(work_dir, section_key)
    solvers = "、".join(evidence["solvers"]) or "未检测到明确求解器调用"
    counts = "、".join(str(value) for value in evidence["scenario_counts"]) or "未检测到"
    issues = evidence["issues"]
    issue_text = "；".join(issues) if issues else "无"
    files = "、".join(evidence["code_files"]) or "无"
    return f"""

【系统提取的可审计执行证据】
- 最终代码文件：{files}
- 实际求解器调用：{solvers}
- 代码中实际赋值的情景/样本规模：{counts}
- 代码证据风险：{issue_text}

写作时只能把上述实际调用写成“本研究采用/调用”的事实。建模方案中提到、
但实际代码未调用的方法只能写成备选或改进方向。所有数值必须来自本次代码输出，
不得补写、估算或从先前回复手工抄录；证据缺失时应明确说明未验证。
"""


def _section_markdown(markdown: str, section_key: str) -> str:
    if section_key.startswith("ques"):
        number = section_key.removeprefix("ques")
        marker = re.compile(rf"\b5\.{re.escape(number)}(?:\D|$)")
    elif section_key == "eda":
        marker = re.compile(r"\b4\.2(?:\D|$)|描述性统计|数据预处理")
    elif section_key == "sensitivity_analysis":
        marker = re.compile(r"\b6(?:\.\d+)?(?:\D|$)|灵敏度分析")
    else:
        return markdown

    headings = list(re.finditer(r"^(#{1,6})\s+(.+?)\s*$", markdown, re.MULTILINE))
    for index, heading in enumerate(headings):
        if not marker.search(heading.group(2)):
            continue
        level = len(heading.group(1))
        end = len(markdown)
        for following in headings[index + 1 :]:
            if len(following.group(1)) <= level:
                end = following.start()
                break
        return markdown[heading.start() : end]
    return ""


def _claimed_scenario_counts(text: str) -> list[int]:
    counts: list[int] = []
    for pattern in _PAPER_SCENARIO_PATTERNS:
        for match in pattern.finditer(text):
            value = int(match.group(1))
            if value not in counts:
                counts.append(value)
    return counts


def validate_paper_evidence(
    work_dir: str,
    markdown: str,
    section_keys: list[str] | None = None,
) -> list[str]:
    """校验论文中的求解事实是否能由对应章节代码支撑。"""
    keys = section_keys or [
        "eda",
        "ques1",
        "ques2",
        "ques3",
        "ques4",
        "ques5",
        "sensitivity_analysis",
    ]
    issues: list[str] = []

    for key in keys:
        evidence = inspect_section_evidence(work_dir, key)
        if not evidence["code_files"]:
            continue
        section_text = _section_markdown(markdown, key)
        if not section_text:
            continue

        for code_issue in evidence["issues"]:
            issues.append(f"{key} 代码证据不合格：{code_issue}")

        actual_solvers = set(evidence["solvers"])
        for solver, claim_pattern in _SOLVER_CLAIMS.items():
            if claim_pattern.search(section_text) and solver not in actual_solvers:
                issues.append(
                    f"{key} 声称实际使用 {solver}，但对应代码没有该求解器调用"
                )

        if (
            _MILP_CLAIM_RE.search(section_text)
            and not evidence["has_discrete_variables"]
        ):
            issues.append(
                f"{key} 声称建立 MILP，但对应代码未检测到整数或二元决策变量"
            )

        code_counts = set(evidence["scenario_counts"])
        for count in _claimed_scenario_counts(section_text):
            if code_counts and count not in code_counts:
                issues.append(
                    f"{key} 声称使用 {count} 个情景，但代码赋值记录仅有 "
                    + "、".join(str(value) for value in sorted(code_counts))
                )

    return list(dict.fromkeys(issues))
