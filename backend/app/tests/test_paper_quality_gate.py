"""终稿质量门禁回归测试。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from app.core.workflow import MathModelWorkFlow
from app.schemas.A2A import CoderToWriter
from app.services.redis_manager import redis_manager
from app.tools.local_interpreter import LocalCodeInterpreter
from app.tools.notebook_serializer import NotebookSerializer
from app.utils.artifact_checker import check_section_artifacts
from app.utils.final_output_validator import validate_final_paper
from app.utils.image_code_index import (
    load_image_code_index,
    update_image_code_index,
)
from app.utils.image_constants import section_dir_name, set_section_labels
from app.utils.paper_evidence_validator import (
    inspect_code_evidence,
    validate_paper_evidence,
)
from app.utils.paper_validator import validate_markdown_image_refs


class TestPaperQualityGate(unittest.TestCase):
    """验证不可信代码、断图和占位符会阻断终稿。"""

    @classmethod
    def setUpClass(cls):
        """初始化测试所需的问题章节目录标签。"""
        set_section_labels(5)

    def test_final_paper_rejects_placeholders(self):
        """终稿中的待补字段不能只记录 warning。"""
        markdown = (
            "# 摘要\n关键词：模型\n"
            "# 一、问题重述\n正文\n"
            "# 二、问题分析\n正文\n"
            "# 三、模型假设\n正文\n"
            "# 四、符号说明\n正文\n"
            "# 五、模型的建立与求解\n"
            + "模型求解结果为【待补充最终利润】。\n"
            + "有效正文" * 800
        )

        issues = validate_final_paper(".", markdown)

        self.assertIn("存在待补充占位符", issues)

    def test_image_reference_must_be_unambiguous(self):
        """只写 basename 且命中多个文件时必须报错。"""
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            for folder in ("5.1_a", "5.2_b"):
                path = root / folder
                path.mkdir()
                (path / "same.png").write_bytes(b"png")

            issues = validate_markdown_image_refs(
                work_dir,
                "![结果](same.png)",
            )

            self.assertTrue(any("引用不明确" in issue for issue in issues))

    def test_code_evidence_rejects_fake_cvar_and_handwritten_metrics(self):
        """分位点冒充 CVaR、手写对比指标都属于阻断问题。"""
        evidence = inspect_code_evidence(
            """
import numpy as np
cvar_5 = np.percentile(profits, 5)
q2_values = [0.5, 0.5, 0.5]
q3_values = [0.6, 0.4, 0.7]
"""
        )

        self.assertEqual(len(evidence["issues"]), 2)
        self.assertTrue(any("CVaR" in issue for issue in evidence["issues"]))
        self.assertTrue(any("手写数值" in issue for issue in evidence["issues"]))

    def test_paper_claims_must_match_actual_solver_and_scenario_count(self):
        """论文不能把计划中的 Gurobi/MILP 和场景数写成执行事实。"""
        with tempfile.TemporaryDirectory() as work_dir:
            section_path = Path(work_dir) / section_dir_name("ques2")
            section_path.mkdir(parents=True)
            (section_path / "code.py").write_text(
                """
from scipy.optimize import linprog
S = 100
result = linprog(c, bounds=bounds, method="highs")
""",
                encoding="utf-8",
            )
            markdown = """
## 5.2 问题二模型的建立与求解

本文采用 Gurobi 求解混合整数线性规划，并使用 500 个随机情景。
"""

            issues = validate_paper_evidence(
                work_dir,
                markdown,
                section_keys=["ques2"],
            )

            self.assertTrue(any("Gurobi" in issue for issue in issues))
            self.assertTrue(any("未检测到整数或二元" in issue for issue in issues))
            self.assertTrue(any("500 个情景" in issue for issue in issues))

    def test_artifact_check_exposes_blocking_evidence_issues(self):
        """Coder 证据问题必须触发备用重跑，不能降级成普通 warning。"""
        with tempfile.TemporaryDirectory() as work_dir:
            section = section_dir_name("ques3")
            section_path = Path(work_dir) / section
            section_path.mkdir(parents=True)
            (section_path / "code.py").write_text(
                "q3_values = [0.54, 0.48, 0.70]\n",
                encoding="utf-8",
            )

            result = check_section_artifacts(
                work_dir,
                section_key="ques3",
                section_dir=section,
                created_images=[],
            )

            self.assertFalse(result.passed)
            self.assertTrue(result.blocking_issues)
            self.assertTrue(
                any("手写数值" in issue for issue in result.blocking_issues)
            )

    def test_bulk_index_update_uses_image_paired_code(self):
        """收尾补写索引时不得用整章代码覆盖单图代码和图题。"""
        with tempfile.TemporaryDirectory() as work_dir:
            section = section_dir_name("ques3")
            section_path = Path(work_dir) / section
            section_path.mkdir(parents=True)
            image_path = section_path / "5.3_multi_dim_radar.png"
            image_path.write_bytes(b"png")
            image_path.with_suffix(".py").write_text(
                """
plt.savefig("5.3_multi_dim_radar.png")
print("## 图5.3：多维方案对比雷达图")
""",
                encoding="utf-8",
            )
            accumulated_code = """
print("## 图5.3：错误的Copula散点矩阵标题")
plt.savefig("5.3_copula_scatter.png")
""" * 20

            update_image_code_index(
                work_dir,
                accumulated_code,
                section="ques3",
                image_names=[f"{section}/5.3_multi_dim_radar.png"],
            )
            entry = load_image_code_index(work_dir)["images"][
                f"{section}/5.3_multi_dim_radar.png"
            ]

            self.assertEqual(entry["alt_text"], "多维方案对比雷达图")
            self.assertNotIn("Copula", entry["code"])


class TestLocalInterpreterCodePersistence(unittest.IsolatedAsyncioTestCase):
    """验证本地解释器始终保存成功执行的章节代码。"""

    async def test_successful_cell_is_persisted_without_index_error(self):
        """图片索引正常时也必须累计代码，不能只在异常分支中保存。"""
        with tempfile.TemporaryDirectory() as work_dir:
            serializer = NotebookSerializer(work_dir)
            serializer.current_segmentation = "eda"
            interpreter = LocalCodeInterpreter("task-test", work_dir, serializer)
            interpreter.execute_code_ = Mock(return_value=[("stdout", "ok")])
            interpreter._push_to_websocket = AsyncMock()

            with patch.object(
                redis_manager,
                "publish_message",
                new=AsyncMock(),
            ):
                _, error_occurred, _ = await interpreter.execute_code(
                    "values = [1, 2, 3]\nprint(sum(values))"
                )

            self.assertFalse(error_occurred)
            self.assertEqual(
                interpreter.section_codes["eda"],
                ["values = [1, 2, 3]\nprint(sum(values))"],
            )

            await interpreter.get_created_images("eda")
            section_path = Path(work_dir) / section_dir_name("eda")
            self.assertIn("print(sum(values))", (section_path / "code.py").read_text())

    def test_artifact_check_accepts_current_image_paired_code(self):
        """已生成图片的同名代码足以证明当前尝试存在真实代码产物。"""
        with tempfile.TemporaryDirectory() as work_dir:
            section = section_dir_name("eda")
            section_path = Path(work_dir) / section
            section_path.mkdir(parents=True)
            image_path = section_path / "land_area_distribution.png"
            image_path.write_bytes(b"png")
            code = (
                "import matplotlib.pyplot as plt\n"
                "values = [1, 2, 3]\n"
                'plt.plot(values)\nplt.savefig("land_area_distribution.png")\n'
            )
            image_path.with_suffix(".py").write_text(code, encoding="utf-8")
            image_name = f"{section}/{image_path.name}"
            update_image_code_index(
                work_dir,
                code,
                section="eda",
                image_names=[image_name],
            )

            result = check_section_artifacts(
                work_dir,
                section_key="eda",
                section_dir=section,
                created_images=[image_name],
            )

            self.assertTrue(result.passed, result.issues)
            self.assertEqual(
                result.code_files,
                [f"{section}/land_area_distribution.py"],
            )

    def test_shared_stage_restores_verified_coder_checkpoint(self):
        """Writer 失败后应复用已核验的代码产物，不重新执行共享阶段。"""
        with tempfile.TemporaryDirectory() as work_dir:
            section = section_dir_name("eda")
            section_path = Path(work_dir) / section
            section_path.mkdir(parents=True)
            image_path = section_path / "land_area_distribution.png"
            image_path.write_bytes(b"png")
            code = (
                "import matplotlib.pyplot as plt\n"
                "values = [1, 2, 3]\n"
                'plt.plot(values)\nplt.savefig("land_area_distribution.png")\n'
            )
            image_path.with_suffix(".py").write_text(code, encoding="utf-8")
            image_name = f"{section}/{image_path.name}"
            update_image_code_index(
                work_dir,
                code,
                section="eda",
                image_names=[image_name],
            )

            serializer = NotebookSerializer(work_dir)
            interpreter = LocalCodeInterpreter("task-test", work_dir, serializer)
            workflow = MathModelWorkFlow()
            workflow.task_id = "task-test"
            workflow.work_dir = work_dir
            checkpoint = {
                "coder_stage_cache": {
                    "eda": {
                        "response": CoderToWriter(
                            code_response="EDA 已完成",
                            created_images=[image_name],
                        ).model_dump(),
                        "code_output": "地块面积统计已完成",
                    }
                }
            }

            restored = workflow._restore_coder_stage_checkpoint(
                checkpoint,
                "eda",
                interpreter,
            )

            self.assertIsNotNone(restored)
            self.assertEqual(restored.created_images, [image_name])
            self.assertEqual(
                interpreter.get_code_output("eda"),
                "地块面积统计已完成",
            )
            self.assertEqual(interpreter.section_codes["eda"], [code])


if __name__ == "__main__":
    unittest.main()
