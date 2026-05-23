"""本地代码解释器模块，通过本地 Jupyter 内核执行 Python 代码。"""

import asyncio
from app.tools.base_interpreter import BaseCodeInterpreter
from app.tools.notebook_serializer import NotebookSerializer
from app.config.setting import settings
import jupyter_client
from app.utils.log_util import logger
import os
from app.services.redis_manager import redis_manager
from app.schemas.response import (
    OutputItem,
    ResultModel,
    StdErrModel,
    SystemMessage,
)
from app.utils.image_code_index import extract_saved_images, update_image_code_index
from app.utils.image_constants import is_image_file, validate_image_filename


class LocalCodeInterpreter(BaseCodeInterpreter):
    """基于本地 Jupyter 内核的代码解释器。"""
    def __init__(
        self,
        task_id: str,
        work_dir: str,
        notebook_serializer: NotebookSerializer,
    ):
        super().__init__(task_id, work_dir, notebook_serializer)
        self.km, self.kc = None, None
        self.interrupt_signal = False

    async def initialize(self):
        # 本地内核一般不需异步上传文件，直接切换目录即可
        # 初始化 Jupyter 内核管理器和客户端
        logger.info("初始化本地内核")
        # 设置 UTF-8 编码环境，避免 Windows 中文环境下 GBK 编码导致的乱码问题
        kernel_env = os.environ.copy()
        kernel_env["PYTHONIOENCODING"] = "utf-8"
        kernel_env["PYTHONUTF8"] = "1"
        self.km, self.kc = jupyter_client.manager.start_new_kernel(
            kernel_name="python3", env=kernel_env
        )
        self._pre_execute_code()

    def _pre_execute_code(self):
        init_code = (
            f"import os\n"
            f"work_dir = r'{self.work_dir}'\n"
            f"os.makedirs(work_dir, exist_ok=True)\n"
            f"os.chdir(work_dir)\n"
            f"print('当前工作目录:', os.getcwd())\n"
            # 加载中文字体，确保图表中文正常显示（跨平台兼容）
            # 先清除 matplotlib 字体缓存，避免旧缓存导致 addfont 失效
            f"import matplotlib\n"
            f"import matplotlib.pyplot as plt\n"
            f"from matplotlib import font_manager\n"
            f"import glob as _glob, pathlib as _pl\n"
            f"_cache_dir = _pl.Path(matplotlib.get_cachedir())\n"
            f"for _cache_file in _glob.glob(str(_cache_dir / 'fontlist*.json')):\n"
            f"    _pl.Path(_cache_file).unlink(missing_ok=True)\n"
            f"font_manager.fontManager.__init__()\n"
            f"_font_dir = work_dir\n"
            f"_loaded = False\n"
            f"for _f in os.listdir(_font_dir):\n"
            f"    if _f.lower().endswith(('.ttf', '.otf', '.ttc')):\n"
            f"        _fp = os.path.join(_font_dir, _f)\n"
            f"        font_manager.fontManager.addfont(_fp)\n"
            f"        _loaded = True\n"
            f"if _loaded:\n"
            f"    print(f'中文字体已加载，可用字体数: {{len(font_manager.fontManager.ttflist)}}')\n"
            f"plt.rcParams['font.sans-serif'] = ['SimHei', 'Heiti SC', 'STHeiti', 'PingFang SC', 'Noto Sans CJK SC', 'Noto Sans SC', 'WenQuanYi Micro Hei', 'Microsoft YaHei', 'sans-serif']\n"
            f"plt.rcParams['axes.unicode_minus'] = False\n"
            f"plt.rcParams['font.family'] = 'sans-serif'\n"
        )
        self.execute_code_(init_code)

    async def execute_code(self, code: str) -> tuple[str, bool, str]:
        logger.info(f"执行代码: {code}")
        #  添加代码到notebook
        cell_index = self.notebook_serializer.add_code_cell_to_notebook(code)

        text_to_gpt: list[str] = []
        content_to_display: list[OutputItem] | None = []
        error_occurred: bool = False
        error_message: str = ""

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="开始执行代码"),
        )
        # 执行 Python 代码
        logger.info("开始在本地执行代码...")
        execution = await asyncio.to_thread(self.execute_code_, code)
        logger.info("代码执行完成，开始处理结果...")

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="代码执行完成"),
        )

        for mark, out_str in execution:
            if mark in ("stdout", "execute_result_text", "display_text"):
                text_to_gpt.append(self._truncate_text(f"[{mark}]\n{out_str}"))
                #  添加text到notebook
                content_to_display.append(
                    ResultModel(res_type="result", format="text", msg=out_str)
                )
                self.notebook_serializer.add_code_cell_output_to_notebook(out_str)

            elif mark in (
                "execute_result_png",
                "execute_result_jpeg",
                "display_png",
                "display_jpeg",
            ):
                # TODO: 视觉模型解释图像
                text_to_gpt.append(f"[{mark} 图片已生成，内容为 base64，未展示]")

                #  添加image到notebook
                if "png" in mark:
                    self.notebook_serializer.add_image_to_notebook(out_str, "image/png")
                    content_to_display.append(
                        ResultModel(res_type="result", format="png", msg=out_str)
                    )
                else:
                    self.notebook_serializer.add_image_to_notebook(
                        out_str, "image/jpeg"
                    )
                    content_to_display.append(
                        ResultModel(res_type="result", format="jpeg", msg=out_str)
                    )

            elif mark == "error":
                error_occurred = True
                error_message = self.delete_color_control_char(out_str)
                error_message = self._truncate_text(error_message)
                logger.error(f"执行错误: {error_message}")
                text_to_gpt.append(error_message)
                #  添加error到notebook
                self.notebook_serializer.add_code_cell_error_to_notebook(out_str)
                content_to_display.append(StdErrModel(msg=out_str))

        logger.info(f"text_to_gpt: {text_to_gpt}")
        combined_text = "\n".join(text_to_gpt)

        if not error_occurred:
            has_images = False
            current_section = self.notebook_serializer.current_segmentation
            final_images: list[str] = []
            try:
                saved_images = extract_saved_images(code)
                if saved_images:
                    has_images = True
                    corrected_images = self.record_created_images(saved_images)
                    # 先移动图片到章节目录，拿到最终相对路径
                    final_images = self.move_images_to_section_dir(corrected_images)
                    # 用最终图片路径保存同名 .py
                    self.save_code_for_images(code, final_images)
                    # 更新 section 图片记录为最终路径
                    if current_section:
                        self.created_images_by_section[current_section] = set(final_images)
                    # 反馈命名违规信息给 Agent
                    naming_issues: list[str] = []
                    for i, image_name in enumerate(saved_images):
                        ok, reason = validate_image_filename(image_name)
                        corrected = corrected_images[i] if i < len(corrected_images) else image_name
                        if not ok:
                            logger.warning(f"图片命名不规范: {reason}")
                            if corrected != image_name:
                                naming_issues.append(
                                    f"【命名违规已自动修正】图片 `{image_name}` → `{corrected}` "
                                    f"（原名称不符合规范，已自动重命名）"
                                )
                            else:
                                naming_issues.append(
                                    f"【命名违规】图片 `{image_name}` 命名不符合规范：{reason}"
                                )
                    if naming_issues:
                        text_to_gpt.append("\n".join(naming_issues))
                else:
                    corrected_images = []
                update_image_code_index(
                    self.work_dir,
                    code,
                    cell_index=cell_index,
                    section=self.notebook_serializer.current_segmentation,
                    image_names=final_images if final_images else None,
                )
            except Exception as e:
                logger.warning(f"记录图片代码映射失败: {e}")

            # 追踪本 cell 代码到当前 section
            current_section = self.notebook_serializer.current_segmentation
            if current_section:
                self.append_section_code(current_section, code)
                # 非图片代码：保存为 5.1_step_01.py 等顺序编号文件
                if not has_images:
                    self.save_non_image_code(code)

        await self._push_to_websocket(content_to_display)

        return (
            combined_text,
            error_occurred,
            error_message,
        )

    def execute_code_(self, code) -> list[tuple[str, str]]:
        import time as _time

        assert self.kc is not None
        assert self.km is not None
        self.kc.execute(code)
        logger.info(f"执行代码: {code}")
        # Get the output of the code
        msg_list = []
        start_ts = _time.time()
        max_seconds = getattr(settings, "CODE_EXECUTION_TIMEOUT", 300)
        while True:
            is_timeout = _time.time() - start_ts > max_seconds
            try:
                iopub_msg = self.kc.get_iopub_msg(timeout=1)
                msg_list.append(iopub_msg)
                if (
                    iopub_msg["msg_type"] == "status"
                    and iopub_msg["content"].get("execution_state") == "idle"
                ):
                    break
            except Exception:
                if self.interrupt_signal or is_timeout:
                    self.km.interrupt_kernel()
                    self.interrupt_signal = False
                if is_timeout and not any(
                    m.get("msg_type") == "status"
                    and m.get("content", {}).get("execution_state") == "idle"
                    for m in msg_list
                ):
                    all_output_timeout: list[tuple[str, str]] = [
                        ("error", f"代码执行超时，超过 {max_seconds} 秒"),
                    ]
                    return all_output_timeout
                continue

        all_output: list[tuple[str, str]] = []
        for iopub_msg in msg_list:
            if iopub_msg["msg_type"] == "stream":
                if iopub_msg["content"].get("name") == "stdout":
                    output = iopub_msg["content"]["text"]
                    all_output.append(("stdout", output))
            elif iopub_msg["msg_type"] == "execute_result":
                if "data" in iopub_msg["content"]:
                    if "text/plain" in iopub_msg["content"]["data"]:
                        output = iopub_msg["content"]["data"]["text/plain"]
                        all_output.append(("execute_result_text", output))
                    if "text/html" in iopub_msg["content"]["data"]:
                        output = iopub_msg["content"]["data"]["text/html"]
                        all_output.append(("execute_result_html", output))
                    if "image/png" in iopub_msg["content"]["data"]:
                        output = iopub_msg["content"]["data"]["image/png"]
                        all_output.append(("execute_result_png", output))
                    if "image/jpeg" in iopub_msg["content"]["data"]:
                        output = iopub_msg["content"]["data"]["image/jpeg"]
                        all_output.append(("execute_result_jpeg", output))
            elif iopub_msg["msg_type"] == "display_data":
                if "data" in iopub_msg["content"]:
                    if "text/plain" in iopub_msg["content"]["data"]:
                        output = iopub_msg["content"]["data"]["text/plain"]
                        all_output.append(("display_text", output))
                    if "text/html" in iopub_msg["content"]["data"]:
                        output = iopub_msg["content"]["data"]["text/html"]
                        all_output.append(("display_html", output))
                    if "image/png" in iopub_msg["content"]["data"]:
                        output = iopub_msg["content"]["data"]["image/png"]
                        all_output.append(("display_png", output))
                    if "image/jpeg" in iopub_msg["content"]["data"]:
                        output = iopub_msg["content"]["data"]["image/jpeg"]
                        all_output.append(("display_jpeg", output))
            elif iopub_msg["msg_type"] == "error":
                # TODO: 正确返回格式
                if "traceback" in iopub_msg["content"]:
                    output = "\n".join(iopub_msg["content"]["traceback"])
                    cleaned_output = self.delete_color_control_char(output)
                    all_output.append(("error", cleaned_output))
        return all_output

    async def get_created_images(self, section: str) -> list[str]:
        """本 section 执行完毕时调用：返回已归档图片路径。

        统一模式：只返回 created_images_by_section 中已记录的最终路径。
        不再移动图片，不再扫描文件系统。
        """
        recorded = self.created_images_by_section.get(section, set())

        if not recorded:
            logger.info(f"[{section}] 无已记录图片。统一模式下不扫描文件系统。")
            self.save_section_code(section)
            return []

        logger.info(f"[{section}] 使用已归档图片: {recorded}")
        self.save_section_code(section)

        section_code = "\n\n".join(self.section_codes.get(section, []))
        if section_code:
            try:
                update_image_code_index(
                    self.work_dir,
                    section_code,
                    section=self.notebook_serializer.current_segmentation,
                    image_names=list(recorded),
                )
            except Exception as exc:
                logger.warning(f"[{section}] 补写图片索引失败: {exc}")

        return sorted(recorded)

    async def cleanup(self):
        # 关闭内核
        assert self.kc is not None
        assert self.km is not None
        self.kc.shutdown()
        logger.info("关闭内核")
        self.km.shutdown_kernel()

    def send_interrupt_signal(self):
        self.interrupt_signal = True

    def restart_jupyter_kernel(self):
        """Restart the Jupyter kernel and recreate the work directory."""
        assert self.kc is not None
        self.kc.shutdown()
        # 设置 UTF-8 编码环境，避免 Windows 中文环境下 GBK 编码导致的乱码问题
        kernel_env = os.environ.copy()
        kernel_env["PYTHONIOENCODING"] = "utf-8"
        kernel_env["PYTHONUTF8"] = "1"
        self.km, self.kc = jupyter_client.manager.start_new_kernel(
            kernel_name="python3", env=kernel_env
        )
        self.interrupt_signal = False
        self._create_work_dir()
        self._pre_execute_code()

    def _create_work_dir(self):
        """Ensure the working directory exists after a restart."""
        os.makedirs(self.work_dir, exist_ok=True)