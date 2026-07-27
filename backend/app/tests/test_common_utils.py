"""通用工具函数单元测试。"""

import unittest

from app.utils.common_utils import (
    _replace_markdown_front_matter_for_latex,
    create_work_dir,
    get_work_dir,
    split_footnotes,
)


class TestCommonUtils(unittest.TestCase):
    """测试 common_utils 模块的核心函数。"""

    def test_split_footnotes(self):
        """测试脚注分离功能。"""
        text = "Example[^1]\n\n[^1]: Footnote content"
        main, notes = split_footnotes(text)
        self.assertEqual(main, "Example")
        self.assertEqual(notes, [("1", "Footnote content")])

    def test_latex_export_replaces_static_toc_with_real_toc_command(self):
        """LaTeX 导出必须移除静态目录正文，并保留后续正式章节。"""
        markdown = """# 示例论文

# 摘要

摘要正文。

# 目录

一、问题重述 1
1.1 问题背景 1

# 一、问题重述

## 1.1 问题背景

正文。
"""

        converted = _replace_markdown_front_matter_for_latex(markdown)

        self.assertIn(r"\paperabstractheading", converted)
        self.assertIn(r"\papermaintoc", converted)
        self.assertNotIn("一、问题重述 1", converted)
        self.assertIn("# 一、问题重述", converted)
        self.assertIn("## 1.1 问题背景", converted)

    def test_work_dir_rejects_path_traversal(self):
        """任务目录入口必须统一拒绝路径穿越。"""
        with self.assertRaises(ValueError):
            create_work_dir("../outside")
        with self.assertRaises(ValueError):
            get_work_dir("../outside")


if __name__ == "__main__":
    unittest.main()
