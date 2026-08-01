"""Incomplete paper preview regression tests."""

import json
import tempfile
import unittest
from pathlib import Path

from app.routers.paper_repair_router import _assemble_from_checkpoint


class TestPaperRepairPreview(unittest.TestCase):
    """Verify that partial papers remain visibly incomplete and ordered."""

    def test_preview_inserts_missing_front_section_placeholders(self):
        """Only preview mode may show explicit placeholders before a saved EDA."""
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint = {
                "coordinator": {"ques_count": 3},
                "user_output_res": {
                    "eda": {
                        "response_content": "## 4.2 描述性统计\n\n已生成的 EDA。",
                        "footnotes": {},
                    }
                },
            }
            Path(temp_dir, "workflow_checkpoint.json").write_text(
                json.dumps(checkpoint, ensure_ascii=False),
                encoding="utf-8",
            )

            preview, included, missing = _assemble_from_checkpoint(
                temp_dir,
                include_missing_placeholders=True,
            )

            self.assertIn("# 一、问题重述", preview)
            self.assertIn("# 二、问题分析", preview)
            self.assertIn("# 三、模型假设", preview)
            self.assertIn("## 4.1 符号说明", preview)
            self.assertIn("## 4.2 描述性统计", preview)
            self.assertLess(preview.index("# 一、问题重述"), preview.index("## 4.2"))
            self.assertEqual(included, ["toc", "eda"])
            self.assertIn("RepeatQues", missing)
            self.assertIn("symbol", missing)

    def test_final_rebuild_never_persists_preview_placeholders(self):
        """Final assembly must not treat missing-section notices as paper content."""
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint = {
                "coordinator": {"ques_count": 1},
                "user_output_res": {
                    "eda": {
                        "response_content": "## 4.2 描述性统计\n\n已生成的 EDA。",
                        "footnotes": {},
                    }
                },
            }
            Path(temp_dir, "workflow_checkpoint.json").write_text(
                json.dumps(checkpoint, ensure_ascii=False),
                encoding="utf-8",
            )

            rebuilt, _, _ = _assemble_from_checkpoint(temp_dir)

            self.assertNotIn("本章节尚未生成", rebuilt)
            self.assertNotIn("标题、摘要与关键词尚未生成", rebuilt)


if __name__ == "__main__":
    unittest.main()
