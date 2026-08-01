"""Regression tests for internal metric labels leaking into paper prose."""

import unittest

from app.models.user_output import clean_final_paper_markdown
from app.utils.paper_internal_label_cleanup import clean_internal_metric_labels


class TestPaperInternalLabelCleanup(unittest.TestCase):
    def test_removes_score_codes_and_normalizes_direction_labels(self):
        raw = """**亩均净利润 SC_1S**（极大型，单位：元/亩）：反映经济回报能力。

**产量稳定性 SC_2S**（极大型，无量纲）：衡量产量波动。

**市场需求匹配度 SC_5S**（极大型，无量纲）：反映市场潜力。
"""

        cleaned = clean_internal_metric_labels(raw)

        self.assertNotIn("SC_1S", cleaned)
        self.assertNotIn("SC_2S", cleaned)
        self.assertNotIn("SC_5S", cleaned)
        self.assertNotIn("极大型", cleaned)
        self.assertIn("亩均净利润**（正向指标，单位：元/亩）", cleaned)
        self.assertIn("产量稳定性**（正向指标，无量纲）", cleaned)

    def test_preserves_score_code_inside_display_formula(self):
        raw = """综合评分定义为：

$$
SC_1S = w_1 z_1
$$
"""

        cleaned = clean_internal_metric_labels(raw)

        self.assertIn("SC_1S = w_1 z_1", cleaned)

    def test_final_paper_pipeline_cleans_existing_paper(self):
        raw = """# 五、模型的建立与求解

**水资源利用效率 SC_3S**（极大型，单位：元/m³）：定义为产值与灌溉水量的比值。
"""

        cleaned = clean_final_paper_markdown(raw)

        self.assertNotIn("SC_3S", cleaned)
        self.assertIn("正向指标", cleaned)
        self.assertIn("单位：元/m³", cleaned)


if __name__ == "__main__":
    unittest.main()
