"""Regression tests for empty display-math placeholder cleanup."""

import unittest

from app.models.user_output import clean_final_paper_markdown
from app.utils.paper_math_cleanup import clean_empty_display_math_blocks


class TestPaperMathCleanup(unittest.TestCase):
    def test_removes_empty_and_unmatched_delimiters(self):
        raw = """步骤三：构建标准化矩阵。

$$

$$

保留正文。

$$
"""

        cleaned = clean_empty_display_math_blocks(raw)

        self.assertNotIn("$$", cleaned)
        self.assertIn("保留正文。", cleaned)

    def test_preserves_valid_display_formula(self):
        raw = """目标函数为：

$$
Z = \\sum_i x_i
$$
"""

        cleaned = clean_empty_display_math_blocks(raw)

        self.assertIn("$$\nZ = \\sum_i x_i\n$$", cleaned)

    def test_final_paper_pipeline_removes_placeholders(self):
        raw = """# 五、模型的建立与求解

### 5.1.3 求解方法与参数

$$

$$

正文继续。
"""

        cleaned = clean_final_paper_markdown(raw)

        self.assertNotIn("\n$$\n", cleaned)
        self.assertIn("### 5.1.3 求解方法与参数", cleaned)
        self.assertIn("正文继续。", cleaned)


if __name__ == "__main__":
    unittest.main()
