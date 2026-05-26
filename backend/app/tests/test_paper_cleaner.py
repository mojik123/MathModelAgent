"""Paper cleanup regression tests."""

import unittest

from app.utils.paper_cleaner import clean_chinese_paper_markdown


class TestPaperCleaner(unittest.TestCase):
    def test_removes_duplicate_symbol_section_and_restores_parent_heading(self):
        raw = """# 题目

# 四、符号说明和数据预处理

## 4.1 符号说明

表1 符号说明

## 四、符号说明和数据预处理

### 4.1 符号说明

重复符号表

### 4.2 描述性统计

这里是 EDA。

## 五、模型的建立与求解

## 5.1 问题一模型的建立与求解

正文。
"""
        cleaned = clean_chinese_paper_markdown(raw)

        self.assertEqual(cleaned.count("四、符号说明和数据预处理"), 1)
        self.assertNotIn("重复符号表", cleaned)
        self.assertIn("# 五、模型的建立与求解", cleaned)
        self.assertIn("## 5.1 问题一模型的建立与求解", cleaned)

    def test_normalizes_math_and_deletion_markup(self):
        raw = """# 摘要

包含删除线 ~~这段文字~~。

\\[
x_{i,j} = 1
\\]

行内公式 \\(x_{i,j}\\)。
"""
        cleaned = clean_chinese_paper_markdown(raw)

        self.assertNotIn("~~", cleaned)
        self.assertNotIn("\\[", cleaned)
        self.assertNotIn("\\(", cleaned)
        self.assertIn("$$\nx_{i,j} = 1\n$$", cleaned)
        self.assertIn("$x_{i,j}$", cleaned)

    def test_moves_inline_footnote_definitions_to_references(self):
        raw = """# 一、问题重述

正文引用[^1]。

[^1]: 张三. 示例文献.

# 二、问题分析

分析正文。
"""
        cleaned = clean_chinese_paper_markdown(raw)

        self.assertIn("# 参考文献", cleaned)
        self.assertTrue(cleaned.rstrip().endswith("[^1]: 张三. 示例文献."))
        self.assertLess(cleaned.index("# 二、问题分析"), cleaned.index("# 参考文献"))


if __name__ == "__main__":
    unittest.main()
