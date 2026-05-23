"""代码解释器抽象基类模块。"""

import abc
import os
import re
from app.tools.notebook_serializer import NotebookSerializer
from app.services.redis_manager import redis_manager
from app.utils.log_util import logger
from app.schemas.response import (
    OutputItem,
    InterpreterMessage,
)


class BaseCodeInterpreter(abc.ABC):
    """代码解释器抽象基类，定义代码执行、输出管理和资源清理的接口。"""
    def __init__(
        self,
        task_id: str,
        work_dir: str,
        notebook_serializer: NotebookSerializer,
    ):
        self.task_id = task_id
        self.work_dir = work_dir
        self.notebook_serializer = notebook_serializer
        self.section_output: dict[str, dict[str, list[str]]] = {}
        self.last_created_images = set()
        self.created_images_by_section: dict[str, set[str]] = {}
        # 各 section 执行的代码片段累积，用于收尾时写入子目录 code.py
        self.section_codes: dict[str, list[str]] = {}
        # 各 section 内非图片代码步数计数器，用于自动命名 5.1_step_01.py 等文件
        self._section_step_counter: dict[str, int] = {}
        # 产物标签：区分主力/备用/竞速 Coder 的产物文件（"" 表示主力）
        self.artifact_tag: str = ""

    @abc.abstractmethod
    async def initialize(self):
        """初始化解释器，必要时上传文件、启动内核等"""
        ...

    @abc.abstractmethod
    async def _pre_execute_code(self):
        """执行初始化代码"""
        ...

    @abc.abstractmethod
    async def execute_code(self, code: str) -> tuple[str, bool, str]:
        """执行一段代码，返回 (输出文本, 是否出错, 错误信息)"""
        ...

    @abc.abstractmethod
    async def cleanup(self):
        """清理资源，比如关闭沙箱或内核"""
        ...

    @abc.abstractmethod
    async def get_created_images(self, section: str) -> list[str]:
        """获取当前 section 创建的图片列表"""
        ...

    async def _push_to_websocket(self, content_to_display: list[OutputItem] | None):
        logger.info("执行结果已推送到WebSocket")

        agent_msg = InterpreterMessage(
            output=content_to_display,
        )
        logger.debug(f"发送消息: {agent_msg.model_dump_json()}")
        await redis_manager.publish_message(
            self.task_id,
            agent_msg,
        )

    def add_section(self, section_name: str) -> None:
        """确保添加的section结构正确，并同步到 notebook serializer。"""

        if section_name not in self.section_output:
            self.section_output[section_name] = {"content": [], "images": []}
        self.created_images_by_section.setdefault(section_name, set())
        self.notebook_serializer.current_segmentation = section_name

    def _auto_rename_image(self, filename: str) -> str:
        """将不合规的图片文件重命名为符合规范的名称。

        例如 ``fig1_OR_sensitivity.png`` → ``5.1_OR_sensitivity.png``（根据当前 section）。

        Args:
            filename: 图片基本名（不含路径）。

        Returns:
            重命名后的基本名（若无需重命名则返回原名）。
        """
        from pathlib import Path as _Path

        from app.utils.image_constants import IMAGE_NAMING_PATTERN

        # 已合规则跳过
        if IMAGE_NAMING_PATTERN.match(filename):
            return filename

        section = self.notebook_serializer.current_segmentation
        if not section:
            return filename

        # 从旧名称提取英文描述：去除 fig{N}_ / figure{N}_ / 章节号前缀
        stem = _Path(filename).stem
        cleaned = re.sub(
            r"^(fig(?:ure)?\d+[_\s]*)", "", stem, flags=re.IGNORECASE
        )
        # 也去除已有的章节号前缀，如 5.1_ / 4.2_ 等
        cleaned = re.sub(r"^\d+\.\d+_", "", cleaned)
        # 只保留 ASCII 字母、数字、下划线、短横线
        cleaned = re.sub(r"[^A-Za-z0-9_\-]", "", cleaned)
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        if not cleaned:
            return filename

        tag = f"{self.artifact_tag}_" if self.artifact_tag else ""
        base_name = f"{tag}{cleaned}"
        new_name = f"{base_name}.png"
        if new_name == filename:
            return filename

        # 覆盖策略：同名图片视为同一产物新版本，直接覆盖
        if os.path.exists(os.path.join(self.work_dir, new_name)):
            try:
                os.remove(os.path.join(self.work_dir, new_name))
            except OSError:
                pass

        src = os.path.join(self.work_dir, filename)
        dst = os.path.join(self.work_dir, new_name)
        if os.path.isfile(src):
            try:
                os.rename(src, dst)
                logger.info(f"图片已自动重命名: {filename} → {new_name}")
                return new_name
            except OSError as exc:
                logger.warning(f"自动重命名图片失败 {filename}: {exc}")
                return filename
        return filename

    def record_created_images(self, filenames: list[str]) -> list[str]:
        """记录本 section 创建的图片，对不合规命名的文件自动重命名。

        Args:
            filenames: 从代码中提取的图片基本名列表。

        Returns:
            修正后的图片基本名列表（已自动重命名不合规文件）。
        """
        section = self.notebook_serializer.current_segmentation
        if not section:
            return list(filenames)
        section_images = self.created_images_by_section.setdefault(section, set())
        corrected: list[str] = []
        for filename in filenames:
            if filename:
                new_name = self._auto_rename_image(filename)
                section_images.add(new_name)
                corrected.append(new_name)
        return corrected

    def add_content(self, section: str, text: str) -> None:
        """向指定section添加文本内容"""
        self.add_section(section)
        self.section_output[section]["content"].append(text)

    def get_code_output(self, section: str) -> str:
        """获取指定section的代码输出"""
        return "\n".join(self.section_output[section]["content"])

    def save_non_image_code(self, code: str) -> str | None:
        """保存非图片代码为 ``{section_num}_step_{NN}.py``。

        图片代码由 ``save_code_for_images`` 处理（与图片同名配对），
        本方法负责其他代码（数据加载、预处理、分析等），按顺序编号。

        Returns:
            保存的相对路径，若无法确定 section 则返回 ``None``。
        """
        import os as _os

        from app.utils.image_constants import get_section_num, section_dir_name

        section = self.notebook_serializer.current_segmentation
        if not section:
            return None

        section_num = get_section_num(section)
        if not section_num:
            return None

        try:
            sub_dir_name = section_dir_name(section)
        except ValueError:
            return None

        dest_dir = _os.path.join(self.work_dir, sub_dir_name)
        _os.makedirs(dest_dir, exist_ok=True)

        n = self._section_step_counter.get(section, 0) + 1
        self._section_step_counter[section] = n
        tag = f"_{self.artifact_tag}" if self.artifact_tag else ""
        code_fname = f"{section_num}{tag}_step_{n:02d}.py"
        code_path = _os.path.join(dest_dir, code_fname)
        try:
            with open(code_path, "w", encoding="utf-8") as f:
                f.write(code)
            rel = f"{sub_dir_name}/{code_fname}"
            logger.info(f"代码已保存: {rel}")
            return rel
        except OSError as exc:
            logger.warning(f"保存代码文件失败 {code_fname}: {exc}")
            return None

    def append_section_code(self, section: str, code: str) -> None:
        """将一段代码追加到指定 section 的累积代码列表中。

        Args:
            section: 章节标识，如 ``"ques1"``、``"eda"``。
            code: 本次执行的代码字符串。
        """
        if section not in self.section_codes:
            self.section_codes[section] = []
        self.section_codes[section].append(code)

    def save_section_code(self, section: str) -> str | None:
        """将指定 section 累积的代码写入对应子目录的 ``code.py`` 文件。

        Args:
            section: 章节标识，如 ``"ques1"``、``"eda"``。

        Returns:
            写入的相对路径（如 ``"5.1_问题1的模型建立与求解/code.py"``），
            若 section 无代码或子目录名解析失败则返回 ``None``。
        """
        from app.utils.image_constants import section_dir_name

        cells = self.section_codes.get(section)
        if not cells:
            return None

        try:
            sub_dir_name = section_dir_name(section)
        except ValueError:
            return None

        dest_dir = os.path.join(self.work_dir, sub_dir_name)
        os.makedirs(dest_dir, exist_ok=True)

        code_filename = f"code_{self.artifact_tag}.py" if self.artifact_tag else "code.py"
        code_path = os.path.join(dest_dir, code_filename)
        separator = "\n\n# " + "─" * 60 + "\n\n"
        full_code = separator.join(cells)
        try:
            with open(code_path, "w", encoding="utf-8") as f:
                f.write(full_code)
            rel_path = f"{sub_dir_name}/{code_filename}"
            logger.info(f"章节代码已保存: {rel_path}")
            return rel_path
        except OSError as exc:
            logger.warning(f"保存章节代码失败 {section}: {exc}")
            return None

    def save_code_for_images(
        self, code: str, image_filenames: list[str]
    ) -> None:
        """严格按图片最终相对路径保存同名 .py。

        输入:
         5.1_问题1的模型建立与求解/prediction_result.png

        输出:
         5.1_问题1的模型建立与求解/prediction_result.py

        Args:
            code: 生成图片的 Python 代码。
            image_filenames: 图片相对路径列表（含章节目录）。
        """
        import os as _os
        from pathlib import Path as _Path

        for fname in image_filenames:
            if not fname:
                continue

            normalized = fname.replace("\\", "/").lstrip("./")
            image_path = _Path(self.work_dir) / normalized

            if not image_path.exists():
                logger.warning(f"图片不存在，无法保存同名代码: {normalized}")
                continue

            code_path = image_path.with_suffix(".py")
            try:
                with open(code_path, "w", encoding="utf-8") as f:
                    f.write(code)
                rel_code = str(code_path.relative_to(_Path(self.work_dir))).replace("\\", "/")
                logger.info(f"图片同名代码已保存: {rel_code}")
            except OSError as exc:
                logger.warning(f"保存图片同名代码失败 {code_path}: {exc}")

    def move_images_to_section_dir(self, filenames: list[str]) -> list[str]:
        """将新图片从工作目录根移动到当前 section 对应的子目录。

        Args:
            filenames: 图片文件名列表（仅基本名，无路径）。

        Returns:
            移动后的相对路径列表（如 ``5.1_问题1/5.1_prediction_result.png``）。
        """
        import shutil

        from app.utils.image_constants import section_dir_name

        section = self.notebook_serializer.current_segmentation
        if not section:
            return list(filenames)

        try:
            sub_dir_name = section_dir_name(section)
        except ValueError:
            return list(filenames)

        dest_dir = os.path.join(self.work_dir, sub_dir_name)
        os.makedirs(dest_dir, exist_ok=True)

        result: list[str] = []
        for fname in filenames:
            normalized = fname.replace("\\", "/")

            # 如果已经是章节目录里的相对路径，直接返回，不再移动
            existing_rel_path = os.path.join(self.work_dir, normalized)
            if "/" in normalized and os.path.isfile(existing_rel_path):
                result.append(normalized)
                continue

            base_name = os.path.basename(normalized)
            src = os.path.join(self.work_dir, base_name)

            # 收敛策略：同名图片视为同一产物的新版本，直接覆盖旧图
            dst_name = base_name
            dst = os.path.join(dest_dir, dst_name)
            final_base_name = dst_name

            if os.path.isfile(src):
                try:
                    if os.path.exists(dst):
                        os.remove(dst)
                    shutil.move(src, dst)
                    rel_path = f"{sub_dir_name}/{final_base_name}"
                    result.append(rel_path)
                    logger.info(f"图片已归入目录: {rel_path}")
                except OSError as exc:
                    logger.warning(f"移动图片失败 {base_name}: {exc}")
                    result.append(normalized)
            else:
                result.append(normalized)
        return result

    def cleanup_attempt_artifacts(self, section: str) -> None:
        """清理当前 Coder attempt 在指定 section 下产生的图片、同名代码和章节代码。

        用于主力/备用 Coder 失败后丢弃本 attempt 产物，避免失败图片进入最终目录。
        """
        from pathlib import Path

        from app.utils.image_constants import section_dir_name
        from app.utils.image_code_index import load_image_code_index, save_image_code_index

        try:
            sub_dir_name = section_dir_name(section)
        except ValueError:
            return

        section_dir = Path(self.work_dir) / sub_dir_name
        if not section_dir.exists():
            return

        recorded = set(self.created_images_by_section.get(section, set()))
        tag = self.artifact_tag or ""
        deleted_image_keys: set[str] = set()

        for img in recorded:
            img_name = Path(str(img).replace("\\", "/")).name
            candidate_paths = [
                Path(self.work_dir) / img_name,
                section_dir / img_name,
            ]
            if "/" in str(img).replace("\\", "/"):
                candidate_paths.append(Path(self.work_dir) / str(img).replace("\\", "/"))

            for img_path in candidate_paths:
                if img_path.exists() and img_path.is_file():
                    rel = str(img_path.relative_to(self.work_dir)).replace("\\", "/")
                    deleted_image_keys.add(rel)
                    deleted_image_keys.add(img_path.name)
                    try:
                        img_path.unlink()
                    except OSError:
                        pass

                    py_path = img_path.with_suffix(".py")
                    if py_path.exists() and py_path.is_file():
                        try:
                            py_path.unlink()
                        except OSError:
                            pass

        if tag:
            code_name = f"code_{tag}.py"
        else:
            code_name = "code.py"

        code_path = section_dir / code_name
        if code_path.exists() and code_path.is_file():
            try:
                code_path.unlink()
            except OSError:
                pass

        if tag:
            step_pattern = f"*_{tag}_step_*.py"
        else:
            step_pattern = "*_step_*.py"

        for path in section_dir.glob(step_pattern):
            if not tag and ("_b" in path.name or "_r" in path.name):
                continue
            try:
                path.unlink()
            except OSError:
                pass

        try:
            index = load_image_code_index(self.work_dir)
            image_map = index.setdefault("images", {})
            for key in list(image_map.keys()):
                entry = image_map.get(key, {})
                filename = str(entry.get("filename") or key)
                basename = str(entry.get("basename") or Path(filename).name)
                if key in deleted_image_keys or filename in deleted_image_keys or basename in deleted_image_keys:
                    image_map.pop(key, None)
            save_image_code_index(self.work_dir, index)
        except Exception:
            pass

        self.created_images_by_section.pop(section, None)
        self.section_codes.pop(section, None)

    def delete_color_control_char(self, string):
        ansi_escape = re.compile(r"(\x9B|\x1B\[)[0-?]*[ -\/]*[@-~]")
        return ansi_escape.sub("", string)

    def _truncate_text(self, text: str, max_length: int = 1000) -> str:
        """截断文本，保留开头和结尾的重要信息"""
        if len(text) <= max_length:
            return text

        half_length = max_length // 2
        return text[:half_length] + "\n... (内容已截断) ...\n" + text[-half_length:]
