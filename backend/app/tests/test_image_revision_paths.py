"""图片修订产物路径单元测试。"""

import tempfile
import unittest
from pathlib import Path

from app.routers.files_router import _resolve_task_artifact_path, _task_image_url


class TestImageRevisionPaths(unittest.TestCase):
    """验证修图结果始终落在原图片路径且 URL 保留目录。"""

    def test_resolve_nested_image_path(self):
        """相对目录应被完整保留。"""
        with tempfile.TemporaryDirectory() as work_dir:
            resolved = _resolve_task_artifact_path(
                work_dir,
                "4.2_描述性统计/planting_heatmap_2023.png",
            )

            self.assertEqual(
                resolved,
                (
                    Path(work_dir)
                    / "4.2_描述性统计"
                    / "planting_heatmap_2023.png"
                ).resolve(),
            )

    def test_reject_path_traversal(self):
        """禁止修订结果越出任务工作目录。"""
        with tempfile.TemporaryDirectory() as work_dir:
            with self.assertRaises(ValueError):
                _resolve_task_artifact_path(work_dir, "../outside.png")

    def test_image_url_keeps_encoded_relative_path(self):
        """静态 URL 应保留目录层级并编码中文。"""
        url = _task_image_url(
            "task-1",
            "4.2_描述性统计/planting_heatmap_2023.png",
        )

        self.assertEqual(
            url,
            "http://localhost:8000/static/task-1/"
            "4.2_%E6%8F%8F%E8%BF%B0%E6%80%A7%E7%BB%9F%E8%AE%A1/"
            "planting_heatmap_2023.png",
        )


if __name__ == "__main__":
    unittest.main()
