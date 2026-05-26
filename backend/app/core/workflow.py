"""工作流模块，编排多 Agent 协作完成数学建模任务。

并行架构：每个子问题绑定独立的 (SubCoordinator + Modeler + Coder + Writer) 组，
多组并行运行。每个子问题 Coder 使用独立 Jupyter kernel，信号量只限制并发上限。
EDA 和 sensitivity_analysis 作为独立阶段顺序执行。
"""

import asyncio
import hashlib
import json
import os
from app.core.agents import WriterAgent, CoderAgent, CoordinatorAgent, ModelerAgent
from app.schemas.request import Problem
from app.schemas.response import SystemMessage, ProgressMessage, SubCoordinatorMessage
from app.tools.openalex_scholar import OpenAlexScholar
from app.utils.log_util import logger
from app.utils.common_utils import create_work_dir, get_config_template
from app.models.user_output import UserOutput, clean_final_paper_markdown
from app.utils.paper_validator import validate_markdown_image_refs
from app.utils.final_output_validator import validate_final_paper, validate_saved_files
from app.schemas.A2A import CoordinatorToModeler, ModelerToCoder
from app.config.setting import settings
from app.tools.interpreter_factory import create_interpreter
from app.services.redis_manager import redis_manager
from app.services.task_state import mark_task_running, mark_task_terminal
from app.tools.notebook_serializer import NotebookSerializer
from app.core.flows import Flows
from app.core.llm.llm import LLM
from app.core.llm.llm_factory import LLMFactory
from app.utils.image_code_index import update_image_metadata
from app.utils.image_describer import generate_image_description
from app.utils.section_validator import validate_section_output
from app.utils.image_constants import get_all_section_keys, section_dir_name, set_section_labels


class WorkFlow:
    """工作流基类。"""

    def __init__(self):
        pass

    def execute(self) -> None:
        """执行工作流。"""
        pass


class MathModelWorkFlow(WorkFlow):
    """数学建模工作流，协调多 Agent 并行完成建模、求解与写作任务。

    架构说明：
    - 全局 CoordinatorAgent：拆解问题
    - 全局 ModelerAgent：生成整体建模方案
    - 并行子问题组（每问一组）：SubCoordinator#i → ModelerAgent#i → CoderAgent#i + WriterAgent#i
    - Coder 通过独立 Jupyter kernel 并发执行（信号量限制并发上限）
    - EDA / sensitivity_analysis 独立顺序执行
    - 最终写作阶段并行（firstPage、RepeatQues 等）
    - 集成 CoordinatorAgent 进行终稿审查
    """

    QUESTION_REQUIRED_FILES = {
        "ques1": ["result1_1.xlsx", "result1_2.xlsx"],
        "ques2": ["result2.xlsx"],
        "ques3": [],
    }

    def _has_required_result_files(self, key: str) -> bool:
        from pathlib import Path

        required = self.QUESTION_REQUIRED_FILES.get(key, [])
        if not required:
            return True
        work = Path(self.work_dir)
        for filename in required:
            matches = list(work.rglob(filename))
            if not matches:
                return False
        return True

    task_id: str
    work_dir: str
    ques_count: int = 0
    questions: dict[str, str | int]
    cancel_event: asyncio.Event | None = None
    question_ready_event: asyncio.Event | None = None  # 等待用户确认问题划分
    question_selections: list[dict] | None = None  # 用户确认的问题划分
    modeling_ready_event: asyncio.Event | None = None  # 等待用户确认建模方案
    modeling_selections: dict | None = None  # 用户选择的建模方案
    checkpoint_filename = "workflow_checkpoint.json"

    def _checkpoint_path(self) -> str:
        return os.path.join(self.work_dir, self.checkpoint_filename)

    def _load_checkpoint(self) -> dict:
        path = self._checkpoint_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning(f"读取任务断点失败 {self.task_id}: {e}")
            return {}

    def _save_checkpoint(self, checkpoint: dict) -> None:
        path = self._checkpoint_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(checkpoint, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存任务断点失败 {self.task_id}: {e}")

    def _save_writer_checkpoint(
        self,
        checkpoint: dict,
        key: str,
        writer_response,
    ) -> None:
        checkpoint.setdefault("user_output_res", {})[key] = {
            "response_content": writer_response.response_content,
            "footnotes": writer_response.footnotes,
        }
        self._save_checkpoint(checkpoint)

    def _create_llm(
        self,
        api_type,
        api_key,
        model,
        base_url,
        max_tokens,
        agent_index: int | None = None,
    ) -> LLM:
        """创建带有编组标识的 LLM 实例。"""
        return LLM(
            api_type=api_type,
            api_key=api_key,
            model=model,
            base_url=base_url,
            task_id=self.task_id,
            max_tokens=max_tokens,
            agent_index=agent_index,
        )

    def _create_writer_agent(
        self,
        problem: Problem,
        agent_index: int | None = None,
    ) -> WriterAgent:
        """创建独立写作 Agent，用于并行写作时隔离对话历史。

        Args:
            problem: 问题配置对象。
            agent_index: 所属并行组编号，None 表示全局单例。
        """
        writer_llm = self._create_llm(
            api_type=settings.WRITER_API_TYPE,
            api_key=settings.WRITER_API_KEY,
            model=settings.WRITER_MODEL,
            base_url=settings.WRITER_BASE_URL,
            max_tokens=settings.WRITER_MAX_TOKENS,
            agent_index=agent_index,
        )
        assert settings.OPENALEX_EMAIL is not None, "OPENALEX_EMAIL 未配置"
        scholar = OpenAlexScholar(
            task_id=self.task_id,
            email=settings.OPENALEX_EMAIL,
            api_key=settings.OPENALEX_API_KEY,
        )
        return WriterAgent(
            task_id=problem.task_id,
            model=writer_llm,
            comp_template=problem.comp_template,
            format_output=problem.format_output,
            scholar=scholar,
            context_window=settings.WRITER_CONTEXT_WINDOW,
            cancel_event=self.cancel_event,
        )

    def _create_coder_agent(
        self,
        problem: Problem,
        code_interpreter,
        agent_index: int | None = None,
    ) -> CoderAgent:
        """创建独立代码手 Agent。

        Args:
            problem: 问题配置对象。
            code_interpreter: 共享的代码解释器实例。
            agent_index: 所属并行组编号。
        """
        coder_llm = self._create_llm(
            api_type=settings.CODER_API_TYPE,
            api_key=settings.CODER_API_KEY,
            model=settings.CODER_MODEL,
            base_url=settings.CODER_BASE_URL,
            max_tokens=settings.CODER_MAX_TOKENS,
            agent_index=agent_index,
        )
        return CoderAgent(
            task_id=problem.task_id,
            model=coder_llm,
            work_dir=self.work_dir,
            max_retries=settings.CODER_MAX_RETRIES,
            code_interpreter=code_interpreter,
            context_window=settings.CODER_CONTEXT_WINDOW,
            cancel_event=self.cancel_event,
        )

    async def _create_code_interpreter(
        self, key: str, worker_suffix: str = "", artifact_tag: str = "",
    ):
        """创建代码解释器。

        Args:
            key: 章节标识（如 "ques1"、"eda"）。
            worker_suffix: 竞速 worker 后缀（如 "_w0"、"_w1"），
                           确保每个竞速 worker 写入不同的 notebook 文件，避免并发覆盖。
            artifact_tag: 产物标签（如 "b1"、"r1"），用于区分主力/备用/竞速 Coder 的产物文件。
        """
        if key == "eda":
            notebook_name = "notebook.ipynb"
        else:
            notebook_name = f"{key}{worker_suffix}.ipynb"
        notebook_serializer = NotebookSerializer(
            work_dir=self.work_dir,
            notebook_name=notebook_name,
        )
        interpreter = await create_interpreter(
            kind="local",
            task_id=self.task_id,
            work_dir=self.work_dir,
            notebook_serializer=notebook_serializer,
            timeout=3000,
        )
        interpreter.artifact_tag = artifact_tag
        return interpreter

    def _section_image_prefix(self, key: str) -> str:
        try:
            return section_dir_name(key).split("_", 1)[0]
        except ValueError:
            return key

    def _with_image_position_hint(
        self,
        coder_prompt: str,
        key: str,
        group_index: int | None,
        artifact_tag: str | None = None,
    ) -> str:
        tag_prefix = f"{artifact_tag}_" if artifact_tag else ""
        examples = (
            f"{tag_prefix}prediction_result.png, "
            f"{tag_prefix}model_diagnostics.png"
        )
        return f"""{coder_prompt}

[Artifact naming rule — MANDATORY]
- For the current subtask `{key}`, saved image filenames MUST NOT include section numbers such as `5.1_`, `5.2_`, `6.1_`.
- The section/question information is already represented by the folder name.
- Filename format: `{tag_prefix}short_english_name.png`
- The descriptive part MUST use ONLY ASCII letters, digits, underscores and hyphens.
- NO Chinese characters, NO spaces, NO special chars.
- Examples: {examples}
- Do NOT use names such as `5.1_prediction_result.png`, `图1_预测结果.png`, `fig1_result.png`.
- Images violating this naming rule may be automatically renamed or may fail artifact check.

REMINDER: Before EVERY execute_code call, you MUST still output the ## 代码介绍 block
(所属阶段 / 功能说明 / 预期产出) as required by the system prompt.
"""

    def _build_fallback_repair_prompt(
        self,
        *,
        key: str,
        original_prompt: str,
        failure_reason: str,
    ) -> str:
        from pathlib import Path

        existing_files = "\n".join(
            str(p.relative_to(Path(self.work_dir))).replace("\\", "/")
            for p in Path(self.work_dir).rglob("*")
            if p.is_file()
            and p.suffix.lower() in {".xlsx", ".csv", ".png", ".py", ".json"}
        )

        return f"""你是备用 Coder。主力 Coder 已失败，失败原因如下：

{failure_reason}

当前工作区已有文件：
{existing_files}

要求：
1. 先检查是否已有该小问核心结果文件。
2. 若核心结果文件已存在，不允许重新完整求解，只允许：
   - 修复缺失表格；
   - 补齐必要图片；
   - 修正文件命名；
   - 输出简短核验代码。
3. 只有核心结果文件不存在时，才允许重新求解。
4. 本次任务必须控制计算量，禁止大规模穷举、禁止 5000 次以上循环。

原始任务：
{original_prompt}
"""

    async def _describe_images(
        self,
        image_filenames: list[str],
        section_label: str,
        writer_llm: LLM,
    ) -> None:
        """为每张新图片调用 LLM Vision 生成专业描述并写入索引。

        Args:
            image_filenames: 新生成图片的文件名列表（不含路径）。
            section_label: 图片所属章节的中文描述（如"问题1的模型建立与求解"）。
            writer_llm: 复用 WriterAgent 的 LLM 实例（通常具备视觉能力）。
        """
        if not image_filenames:
            return

        for filename in image_filenames:
            image_path = os.path.join(self.work_dir, filename)
            try:
                description = await generate_image_description(
                    image_path=image_path,
                    section_label=section_label,
                    provider=writer_llm.provider,
                    model=writer_llm.model or "",
                    api_key=writer_llm.api_key or "",
                    base_url=writer_llm.base_url,
                    api_type=writer_llm.api_type,
                )
                if description:
                    update_image_metadata(
                        self.work_dir,
                        filename,
                        description=description,
                        caption=description,
                        metadata_source="llm",
                    )
                    await redis_manager.publish_message(
                        self.task_id,
                        SystemMessage(content=f"已生成图片描述：{filename}"),
                    )
            except Exception as exc:
                logger.warning(f"图片描述生成失败 {filename}: {exc}")

    async def _check_cancelled(self) -> None:
        """检查是否收到取消信号，若已取消则发布通知并抛出 CancelledError。"""
        if self.cancel_event and self.cancel_event.is_set():
            raise asyncio.CancelledError("任务被用户停止")

    async def _publish_progress(self, current: int, total: int, description: str) -> None:
        """发布结构化进度消息到前端。"""
        pct = round(current / total * 100) if total > 0 else 0
        await mark_task_running(
            self.task_id,
            description,
            current_step=description,
            progress=pct,
        )
        await redis_manager.publish_message(
            self.task_id,
            ProgressMessage(
                current=current,
                total=total,
                percentage=pct,
                description=description,
            ),
        )

    async def _publish_sub_coordinator(
        self,
        group_index: int,
        content: str,
    ) -> None:
        """发布子问题组协调消息，标注组编号。

        Args:
            group_index: 并行组编号（1-based）。
            content: 协调消息内容。
        """
        msg = SubCoordinatorMessage(
            content=content,
            agent_index=group_index,
        )
        msg.question_index = group_index
        msg.agent_instance_id = f'q{group_index}.sub_coordinator'
        msg.group_id = f'q{group_index}.sub_coordinator'
        msg.phase = 'coordinating'

        await redis_manager.publish_message(self.task_id, msg)

    async def _publish_agent_stop_reason(
        self,
        *,
        group_idx: int | None,
        key: str,
        agent_name: str,
        reason: str,
        detail: str = "",
        level: str = "error",
    ) -> None:
        group_text = f"[组#{group_idx}] " if group_idx is not None else ""
        clean_detail = str(detail or "").strip()
        if len(clean_detail) > 1200:
            clean_detail = (
                clean_detail[:600]
                + "\n...（中间省略）...\n"
                + clean_detail[-500:]
            )

        content = (
            f"{group_text}{agent_name} 已停止：{reason}\n"
            f"子任务：{key}"
        )
        if clean_detail:
            content += f"\n停止详情：{clean_detail}"

        msg = SystemMessage(content=content, type=level)
        if group_idx is not None:
            msg.question_index = group_idx
            msg.group_id = f"q{group_idx}"
            msg.phase = "stopped"
        await redis_manager.publish_message(self.task_id, msg)

    async def _run_solution_step(
        self,
        key: str,
        coder_prompt: str,
        problem: Problem,
        flows: Flows,
        code_interpreter,
        config_template: dict,
        writer_llm: LLM,
        solution_label_map: dict[str, str],
        coder_semaphore: asyncio.Semaphore,
        write_lock: asyncio.Lock,
        checkpoint: dict,
        user_output: UserOutput,
        group_index: int | None,
        coder_agent: CoderAgent,
        writer_agent: WriterAgent,
        step_counter: list[int],
        total_steps: int,
    ) -> None:
        """执行单个子问题的 Coder + Writer 流水线。

        Coder 执行受 coder_semaphore 约束（限制并发上限，每组使用独立 kernel）；
        Writer 在 Coder 返回后立即在同一协程中执行（无需等待其他组）。

        Args:
            key: 子任务键（如 "ques1"、"eda"）。
            coder_prompt: 传给 CoderAgent 的求解提示。
            problem: 原始 Problem 对象。
            flows: 流程配置。
            code_interpreter: 当前组的代码解释器。
            config_template: 论文模板配置。
            writer_llm: 复用的 writer LLM（用于图片描述）。
            solution_label_map: key → 中文章节描述映射。
            coder_semaphore: 限制 Coder 并发数的信号量。
            write_lock: 保护 user_output 写入的锁。
            checkpoint: 可变 checkpoint dict（用于持久化断点）。
            user_output: 任务输出对象。
            group_index: 并行组编号（None=共享阶段，1-based=子问题组）。
            coder_agent: 该组专属 CoderAgent。
            writer_agent: 该组专属 WriterAgent。
            step_counter: 单元素列表，通过引用传递 current_step。
            total_steps: 总步数（用于进度计算）。
        """
        label = solution_label_map.get(key, key)
        group_tag = f"[组#{group_index}] " if group_index is not None else ""

        await self._check_cancelled()

        # Coder 阶段：并发执行受上限约束，每组使用独立 kernel
        async with coder_semaphore:
            await self._check_cancelled()

            step_counter[0] += 1
            await self._publish_progress(
                step_counter[0], total_steps, f"{group_tag}正在求解: {key}"
            )
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content=f"{group_tag}代码手开始求解{key}"),
            )

            coder_response = await coder_agent.run(
                prompt=self._with_image_position_hint(coder_prompt, key, group_index),
                subtask_title=key,
            )

            step_counter[0] += 1
            await self._publish_progress(
                step_counter[0], total_steps, f"{group_tag}求解完成: {key}，正在撰写"
            )
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content=f"{group_tag}代码手求解成功{key}", type="success"),
            )

        # 产物检查（覆盖 EDA / sensitivity_analysis 等共享阶段）
        from app.utils.artifact_checker import check_section_artifacts

        section_dir = section_dir_name(key)
        artifact_check = check_section_artifacts(
            self.work_dir,
            section_key=key,
            section_dir=section_dir,
            created_images=coder_response.created_images,
            require_image=False,
            artifact_tag=None,
        )
        if not artifact_check.passed:
            raise RuntimeError(
                f"{key} 产物检查失败：" + "；".join(artifact_check.issues)
            )

        # 图片描述（在 coder_semaphore 外执行，不阻塞下一个 coder）
        if (
            coder_response.created_images
            and getattr(settings, "IMAGE_DESCRIPTION_ENABLED", False)
        ):
            desc_coro_eda = self._describe_images(
                image_filenames=coder_response.created_images,
                section_label=label,
                writer_llm=writer_llm,
            )

            if getattr(settings, "IMAGE_DESCRIPTION_BACKGROUND", True):
                asyncio.create_task(desc_coro_eda)
            else:
                await desc_coro_eda

        # Writer 阶段：立即执行，无需等待其他组
        writer_prompt = flows.get_writer_prompt(
            key, coder_response.code_response or "", code_interpreter, config_template
        )

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content=f"{group_tag}论文手开始写{key}部分"),
        )

        writer_response = await writer_agent.run(
            writer_prompt,
            available_images=coder_response.created_images,
            sub_title=key,
        )

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content=f"{group_tag}论文手完成{key}部分"),
        )

        # 检查 Coder 生成的图片是否被 Writer 引用，缺图则自动修复一次
        missing_images = []
        for img in (coder_response.created_images or []):
            basename = os.path.basename(img)
            if img not in writer_response.response_content and basename not in writer_response.response_content:
                missing_images.append(img)

        if missing_images:
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=(
                        f"{group_tag}Writer 未引用部分生成图片："
                        + "、".join(missing_images[:5])
                    ),
                    type="warning",
                ),
            )

            repair_prompt = f"""
你上一版没有引用以下已经生成的图片：

{chr(10).join(f"- {img}" for img in missing_images)}

请在不改变原有模型结果、公式和结论的前提下，重新输出本章节 Markdown。
必须把这些图片插入到最相关的结果分析段落附近，并给出简短图注和解释。

原章节内容：
{writer_response.response_content}
"""
            try:
                repaired_response = await writer_agent.run(
                    repair_prompt,
                    available_images=missing_images,
                    sub_title=key,
                )
                if repaired_response.response_content.strip():
                    writer_response = repaired_response
                    await redis_manager.publish_message(
                        self.task_id,
                        SystemMessage(
                            content=f"{group_tag}Writer 已自动修复缺图",
                            type="success",
                        ),
                    )
            except Exception as exc:
                logger.warning(f"{key} Writer 缺图修复失败: {exc}")

        # 章节校验（EDA / sensitivity_analysis）
        section_issues = validate_section_output(
            key,
            writer_response.response_content or "",
            self.ques_count,
            available_images=coder_response.created_images,
        )

        # 检查是否内容过长，如果过长则自动修复一次
        length_issues = [issue for issue in section_issues if "内容过长" in issue]
        if length_issues:
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=f"{group_tag}检测到 {key} 内容过长，正在自动精简",
                    type="warning",
                ),
            )

            trim_prompt = f"""
你之前生成的"{key}"章节内容过长了。请精简内容，使其更加精炼，但保留所有关键模型结论、数值结果和图片引用。

要求：
1. 删除冗余的过程描述和重复的解释
2. 保留模型的核心思想、主要假设、关键公式和最终结果
3. 保留所有数值预测、对比分析和重要图表引用
4. 删除过多的中间步骤细节和冗长的背景介绍
5. 合并同义段落，精简过长的案例说明

输出格式仍为 Markdown，不要输出解释、检查报告或代码块围栏。

原章节内容：
{writer_response.response_content}
"""
            try:
                trimmed_response = await writer_agent.run(
                    trim_prompt,
                    available_images=coder_response.created_images,
                    sub_title=key,
                )
                if trimmed_response.response_content.strip():
                    # 验证修剪后的内容是否仍然过长
                    trimmed_issues = validate_section_output(
                        key,
                        trimmed_response.response_content,
                        self.ques_count,
                        available_images=coder_response.created_images,
                    )
                    if not any("内容过长" in issue for issue in trimmed_issues):
                        writer_response = trimmed_response
                        await redis_manager.publish_message(
                            self.task_id,
                            SystemMessage(
                                content=f"{group_tag}已自动精简 {key}，从 {len(writer_response.response_content or '')} 字符优化至 {len(trimmed_response.response_content or '')}",
                                type="success",
                            ),
                        )
                        section_issues = trimmed_issues
            except Exception as exc:
                logger.warning(f"{key} 内容精简失败: {exc}")

        async with write_lock:
            user_output.set_res(key, writer_response)
            self._save_writer_checkpoint(checkpoint, key, writer_response)
        checkpoint["section_ledger"][key] = {
            "title": solution_label_map.get(key, key),
            "owner": f"{key}.writer",
            "status": "invalid" if section_issues else "valid",
            "attempts": 1,
            "content_chars": len(writer_response.response_content or ""),
            "issues": section_issues,
            "last_action": "generated",
        }
        self._save_checkpoint(checkpoint)

    async def execute(self, problem: Problem):  # type: ignore[reportIncompatibleMethodOverride]
        """执行数学建模工作流（并行多组架构）。

        Args:
            problem: 包含题目信息、模板配置等的 Problem 对象。
        """
        self.task_id = problem.task_id
        self.work_dir = create_work_dir(self.task_id)
        checkpoint = self._load_checkpoint()
        checkpoint.setdefault("section_ledger", {})

        llm_factory = LLMFactory(self.task_id)
        coordinator_llm, modeler_llm, coder_llm, writer_llm = llm_factory.get_all_llms()

        # 广播各 Agent 使用的模型配置
        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content=(
                "Agent 模型配置：\n"
                f"Coordinator: {coordinator_llm.api_type.value if coordinator_llm.api_type else '?'} / {coordinator_llm.model}\n"
                f"Modeler:     {modeler_llm.api_type.value if modeler_llm.api_type else '?'} / {modeler_llm.model}\n"
                f"Coder:       {coder_llm.api_type.value if coder_llm.api_type else '?'} / {coder_llm.model}\n"
                f"Writer:      {writer_llm.api_type.value if writer_llm.api_type else '?'} / {writer_llm.model}"
            )),
        )

        coordinator_agent = CoordinatorAgent(
            self.task_id, coordinator_llm,
            context_window=settings.COORDINATOR_CONTEXT_WINDOW,
            cancel_event=self.cancel_event,
        )

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="识别用户意图和拆解问题ing..."),
        )

        await self._check_cancelled()

        # ── 阶段 1：全局协调者拆解问题 ─────────────────────────────────────
        if checkpoint.get("coordinator"):
            coordinator_response = CoordinatorToModeler(**checkpoint["coordinator"])
            self.questions = coordinator_response.questions
            self.ques_count = coordinator_response.ques_count
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="从断点恢复：已复用问题拆解结果"),
            )
        else:
            try:
                coordinator_response = await coordinator_agent.run(problem.ques_all)
                self.questions = coordinator_response.questions
                self.ques_count = coordinator_response.ques_count
                checkpoint["coordinator"] = coordinator_response.model_dump()
                self._save_checkpoint(checkpoint)
            except Exception as e:
                logger.error(f"CoordinatorAgent 执行失败: {e}")
                raise e

        # 总步骤计算：
        # coordinator(1) + modeler(1) + eda coder+writer(2)
        # + N*[sub_coord_start + modeler + coder + writer + sub_coord_end](5 per group)
        # + sensitivity coder+writer(2) + write_flows(6) + final_review(1) + save(1)
        n = self.ques_count
        write_flow_count = 7  # firstPage, toc, RepeatQues, analysisQues, modelAssumption, symbol, judge
        total_steps = (
            1                       # coordinator
            + 1                     # modeler
            + 2                     # EDA coder + writer
            + n * 5                 # per-group: sub_coord_start + modeler + coder + writer + sub_coord_end
            + 2                     # sensitivity coder + writer
            + write_flow_count      # final write sections
            + 2                     # final review + save
        )
        step_counter = [1]  # coordinator done; mutable container for closures

        await self._publish_progress(step_counter[0], total_steps, "问题拆解完成，开始问题划分讨论")
        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="识别用户意图和拆解问题完成，等待用户确认问题划分"),
        )

        # ── 等待用户确认问题划分 ─────────────────────────────────────────────
        if not checkpoint.get("question_selections"):
            await self._publish_progress(step_counter[0], total_steps, "等待用户确认问题划分")
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="等待用户确认问题划分"),
            )

            from app.routers.modeling_router import _active_tasks

            entry = _active_tasks.setdefault(self.task_id, {})
            self.question_ready_event = asyncio.Event()
            entry["question_ready_event"] = self.question_ready_event
            entry["question_selections_ref"] = self

            try:
                tasks = [asyncio.create_task(self.question_ready_event.wait())]
                if self.cancel_event:
                    tasks.append(asyncio.create_task(self.cancel_event.wait()))
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                if self.cancel_event and self.cancel_event.is_set():
                    raise asyncio.CancelledError("任务被用户停止")
            finally:
                _active_tasks[self.task_id].pop("question_ready_event", None)
                _active_tasks[self.task_id].pop("question_selections_ref", None)

            checkpoint["question_selections"] = self.question_selections
            self._save_checkpoint(checkpoint)

            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="问题划分已确认，开始进入建模思路讨论"),
            )
        else:
            self.question_selections = checkpoint["question_selections"]
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="从断点恢复：已复用问题划分"),
            )

        # 将用户确认的问题划分写回 coordinator_response
        if self.question_selections:
            confirmed_questions: dict[str, str | int] = {
                "ques_count": len(self.question_selections),
            }
            for idx, item in enumerate(self.question_selections, start=1):
                confirmed_questions[f"ques{idx}"] = str(item.get("questionText", ""))
            coordinator_response.questions.update(confirmed_questions)
            coordinator_response.ques_count = len(self.question_selections)
            self.questions = coordinator_response.questions
            self.ques_count = coordinator_response.ques_count
            checkpoint["coordinator"] = coordinator_response.model_dump()
            self._save_checkpoint(checkpoint)

        # ── 等待用户确认建模方案 ─────────────────────────────────────────────
        if not checkpoint.get("modeling_selections"):
            await self._publish_progress(step_counter[0], total_steps, "等待用户确认各问建模方案")
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="等待用户确认各问建模方案"),
            )
            from app.routers.modeling_router import _active_tasks

            # 防御：确保 _active_tasks 中有当前任务的条目（可能在异常恢复中缺失）
            entry = _active_tasks.setdefault(self.task_id, {})
            self.modeling_ready_event = asyncio.Event()
            entry["modeling_ready_event"] = self.modeling_ready_event
            entry["modeling_selections_ref"] = self

            try:
                tasks = [asyncio.create_task(self.modeling_ready_event.wait())]
                if self.cancel_event:
                    tasks.append(asyncio.create_task(self.cancel_event.wait()))
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                if self.cancel_event and self.cancel_event.is_set():
                    raise asyncio.CancelledError("任务被用户停止")
            finally:
                _active_tasks[self.task_id].pop("modeling_ready_event", None)
                _active_tasks[self.task_id].pop("modeling_selections_ref", None)

            checkpoint["modeling_selections"] = self.modeling_selections
            self._save_checkpoint(checkpoint)

            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="建模方案已确认，开始执行建模"),
            )
            await self._publish_progress(step_counter[0], total_steps, "建模方案已确认，开始建模分析")
        else:
            self.modeling_selections = checkpoint["modeling_selections"]
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="从断点恢复：已复用建模方案选择"),
            )

        await self._check_cancelled()

        # ── 阶段 2：全局建模手生成整体方案 ───────────────────────────────────
        # 为建模手创建文献检索客户端
        modeler_scholar = None
        if settings.OPENALEX_EMAIL:
            modeler_scholar = OpenAlexScholar(
                task_id=self.task_id,
                email=settings.OPENALEX_EMAIL,
                api_key=settings.OPENALEX_API_KEY,
            )
        modeler_agent = ModelerAgent(
            self.task_id, modeler_llm,
            context_window=settings.MODELER_CONTEXT_WINDOW,
            cancel_event=self.cancel_event,
            scholar=modeler_scholar,
        )

        if checkpoint.get("modeler"):
            modeler_response = ModelerToCoder(**checkpoint["modeler"])
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="从断点恢复：已复用建模方案"),
            )
        else:
            modeler_response = await modeler_agent.run(
                coordinator_response,
                modeling_selections=self.modeling_selections,
            )
            checkpoint["modeler"] = modeler_response.model_dump()
            self._save_checkpoint(checkpoint)

        step_counter[0] += 1
        await self._publish_progress(step_counter[0], total_steps, "建模分析完成，准备并行求解")

        user_output = UserOutput(work_dir=self.work_dir, ques_count=self.ques_count)
        for key, value in checkpoint.get("user_output_res", {}).items():
            if isinstance(value, dict):
                user_output.res[key] = value

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="正在创建代码沙盒环境"),
        )

        notebook_serializer = NotebookSerializer(work_dir=self.work_dir)
        code_interpreter = await create_interpreter(
            kind="local",
            task_id=self.task_id,
            work_dir=self.work_dir,
            notebook_serializer=notebook_serializer,
            timeout=3000,
        )

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="创建完成"),
        )

        flows = Flows(self.questions)
        config_template = get_config_template(problem.comp_template)

        # 注册章节标签并预创建图片/代码子目录
        set_section_labels(self.ques_count)
        for key in get_all_section_keys(self.ques_count):
            sub_dir = os.path.join(self.work_dir, section_dir_name(key))
            os.makedirs(sub_dir, exist_ok=True)
            logger.info(f"预创建章节目录: {sub_dir}")

        # 章节 key → 中文描述（用于图片生成描述）
        solution_label_map: dict[str, str] = {
            "eda": "数据预处理与探索性分析",
            "sensitivity_analysis": "模型灵敏度分析与检验",
        }
        for _i in range(1, self.ques_count + 1):
            solution_label_map[f"ques{_i}"] = f"问题{_i}的模型建立与求解"

        solution_flows = flows.get_solution_flows(self.questions, modeler_response)

        # 并发控制：QUESTION_PARALLELISM <= 0 表示所有子问题组一起并行。
        configured_question_parallelism = int(
            getattr(settings, "QUESTION_PARALLELISM", 0) or 0
        )
        question_parallelism = (
            self.ques_count or 1
            if configured_question_parallelism <= 0
            else max(1, min(self.ques_count or 1, configured_question_parallelism))
        )

        question_semaphore = asyncio.Semaphore(question_parallelism)
        coder_semaphore = asyncio.Semaphore(question_parallelism)
        # 写入锁：保护 user_output.set_res 并发写入
        write_lock = asyncio.Lock()

        # ── 阶段 3：EDA 数据预处理（必须先于各问求解） ──────────────────────────
        eda_key = "eda"
        if eda_key not in user_output.res:
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="全局协调者：启动 EDA 数据探索阶段"),
            )
            eda_coder = self._create_coder_agent(problem, code_interpreter, agent_index=None)
            eda_writer = self._create_writer_agent(problem, agent_index=None)
            await self._run_solution_step(
                key=eda_key,
                coder_prompt=solution_flows[eda_key]["coder_prompt"],
                problem=problem,
                flows=flows,
                code_interpreter=code_interpreter,
                config_template=config_template,
                writer_llm=writer_llm,
                solution_label_map=solution_label_map,
                coder_semaphore=coder_semaphore,
                write_lock=write_lock,
                checkpoint=checkpoint,
                user_output=user_output,
                group_index=None,
                coder_agent=eda_coder,
                writer_agent=eda_writer,
                step_counter=step_counter,
                total_steps=total_steps,
            )
        else:
            step_counter[0] += 2
            await self._publish_progress(step_counter[0], total_steps, "从断点恢复：EDA 已完成")

        await self._check_cancelled()

        # ── 阶段 4：并行子问题组 ─────────────────────────────────────────────
        question_keys = [k for k in solution_flows if k.startswith("ques")]

        if question_keys:
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=(
                        f"全局协调者：启动 {len(question_keys)} 个子问题并行组，"
                        "每问单 Coder，失败自动启动备用"
                    )
                ),
            )

        async def run_question_group(group_idx: int, key: str) -> None:
            """运行单个子问题组。

            默认每问单 Coder，主力失败后自动启动备用 Coder。
            产物检查保证图片、代码、论文引用可靠。
            """
            label = solution_label_map.get(key, key)
            if key in user_output.res:
                step_counter[0] += 5
                await self._publish_progress(
                    step_counter[0], total_steps, f"从断点恢复：[组#{group_idx}] {key} 已完成"
                )
                return

            await self._publish_sub_coordinator(
                group_idx,
                f"子问题组#{group_idx} 启动 · 负责：{label}",
            )
            step_counter[0] += 1
            await self._publish_progress(
                step_counter[0], total_steps, f"[组#{group_idx}] 启动子问题组：{key}"
            )

            await self._publish_sub_coordinator(
                group_idx,
                f"子问题组#{group_idx} 协调：将使用全局建模方案求解 {label}",
            )
            step_counter[0] += 1

            # ── Coder 构建 helper ──
            async def _build_coder(
                worker_suffix: str,
                artifact_tag: str,
                race_index: int | None,
            ):
                interp = await self._create_code_interpreter(
                    key,
                    worker_suffix=worker_suffix,
                    artifact_tag=artifact_tag,
                )
                coder = self._create_coder_agent(
                    problem, interp, agent_index=group_idx
                )
                coder.model.question_index = group_idx
                coder.model.race_index = race_index
                coder.model.agent_instance_id = (
                    f"q{group_idx}.coder.{artifact_tag}"
                    if artifact_tag
                    else f"q{group_idx}.coder.main"
                )
                coder.model.group_id = f"q{group_idx}.coder"
                coder.model.phase = "coding"
                return interp, coder

            # ── 公共产物检查 helper ──
            async def _check_coder_artifacts(result, attempt_name: str, artifact_tag: str = ""):
                from app.utils.artifact_checker import check_section_artifacts

                section_dir = section_dir_name(key)
                check = check_section_artifacts(
                    self.work_dir,
                    section_key=key,
                    section_dir=section_dir,
                    created_images=result.created_images,
                    require_image=False,
                    artifact_tag=artifact_tag or None,
                )

                # 产物检查结果写入 checkpoint，方便诊断
                checkpoint.setdefault("artifact_checks", {}).setdefault(key, {})[
                    artifact_tag or "main"
                ] = {
                    "attempt_name": attempt_name,
                    "passed": check.passed,
                    "issues": check.issues,
                    "images": check.images,
                    "code_files": check.code_files,
                }
                self._save_checkpoint(checkpoint)

                if not check.passed:
                    core_ok = self._has_required_result_files(key)
                    issue_text = "；".join(check.issues[:8])

                    if core_ok and not getattr(settings, "ARTIFACT_STRICT_FATAL", False):
                        await redis_manager.publish_message(
                            self.task_id,
                            SystemMessage(
                                content=(
                                    f"[组#{group_idx}] Coder {attempt_name} 核心结果已生成，"
                                    f"产物检查存在非致命问题，继续进入 Writer。\n"
                                    f"问题：{issue_text}"
                                ),
                                type="warning",
                            ),
                        )
                        return

                    raise RuntimeError(
                        f"Coder {attempt_name} 产物检查失败：{issue_text}"
                    )

            # ── 单次 Coder 尝试（含产物检查） ──
            async def _run_single_coder_attempt(
                *,
                attempt_name: str,
                worker_suffix: str,
                artifact_tag: str,
                race_index: int | None = None,
                prompt_override: str | None = None,
            ):
                interp, coder = await _build_coder(
                    worker_suffix, artifact_tag, race_index
                )
                try:
                    async with coder_semaphore:
                        await self._check_cancelled()
                        await redis_manager.publish_message(
                            self.task_id,
                            SystemMessage(
                                content=(
                                    f"[组#{group_idx}] Coder {attempt_name} 开始求解 {key}"
                                )
                            ),
                        )
                        base_prompt = prompt_override or solution_flows[key]["coder_prompt"]
                        attempt_prompt = self._with_image_position_hint(
                            base_prompt,
                            key,
                            group_idx,
                            artifact_tag=artifact_tag or None,
                        )
                        attempt_timeout = int(
                            getattr(settings, "CODER_ATTEMPT_TIMEOUT", 1200)
                        )
                        result = await asyncio.wait_for(
                            coder.run(
                                prompt=attempt_prompt, subtask_title=key
                            ),
                            timeout=attempt_timeout,
                        )

                    await _check_coder_artifacts(result, attempt_name, artifact_tag)

                    return interp, result

                except asyncio.TimeoutError as exc:
                    await self._publish_agent_stop_reason(
                        group_idx=group_idx,
                        key=key,
                        agent_name=f"Coder {attempt_name}",
                        reason="运行超时",
                        detail=str(exc),
                        level="error",
                    )
                    try:
                        interp.cleanup_attempt_artifacts(key)
                    except Exception as cleanup_exc:
                        logger.warning(
                            f"[组#{group_idx}] 清理超时 Coder 产物失败: {cleanup_exc}"
                        )
                    try:
                        await interp.cleanup()
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"Coder {attempt_name} 超时：{attempt_timeout}s 内未完成 {key}"
                    ) from exc

                except Exception as exc:
                    await self._publish_agent_stop_reason(
                        group_idx=group_idx,
                        key=key,
                        agent_name=f"Coder {attempt_name}",
                        reason="求解失败",
                        detail=str(exc),
                        level="error",
                    )
                    try:
                        interp.cleanup_attempt_artifacts(key)
                    except Exception as cleanup_exc:
                        logger.warning(
                            f"[组#{group_idx}] 清理失败 Coder 产物失败: {cleanup_exc}"
                        )
                    try:
                        await interp.cleanup()
                    except Exception:
                        pass
                    raise

            # ── 普通模式：主力 → 备用 ──
            async def _run_coder_with_fallback():
                failures: list[str] = []

                # 主力 Coder
                try:
                    return await _run_single_coder_attempt(
                        attempt_name="主力",
                        worker_suffix="_main",
                        artifact_tag="",
                        race_index=1,
                    )
                except Exception as exc:
                    failures.append(f"主力失败：{exc}")
                    logger.warning(
                        f"[组#{group_idx}] 主力 Coder 失败: {exc}"
                    )
                    await self._publish_agent_stop_reason(
                        group_idx=group_idx,
                        key=key,
                        agent_name="Coder 主力",
                        reason="主力尝试失败，准备切换备用",
                        detail=str(exc),
                        level="warning",
                    )

                # 固定一层备用，使用轻量 repair prompt 避免完整重跑
                try:
                    fallback_prompt = self._build_fallback_repair_prompt(
                        key=key,
                        original_prompt=solution_flows[key]["coder_prompt"],
                        failure_reason="；".join(failures),
                    )
                    await redis_manager.publish_message(
                        self.task_id,
                        SystemMessage(
                            content=f"[组#{group_idx}] 启动备用 Coder 1/1 (轻量修复)",
                            type="warning",
                        ),
                    )
                    return await _run_single_coder_attempt(
                        attempt_name="备用1",
                        worker_suffix="_b1",
                        artifact_tag="b1",
                        race_index=2,
                        prompt_override=fallback_prompt,
                    )
                except Exception as exc:
                    failures.append(f"备用1失败：{exc}")
                    logger.warning(
                        f"[组#{group_idx}] 备用 Coder 1 失败: {exc}"
                    )
                    await self._publish_agent_stop_reason(
                        group_idx=group_idx,
                        key=key,
                        agent_name="Coder 备用1",
                        reason="备用尝试失败",
                        detail=str(exc),
                        level="error",
                    )

                final_reason = "；".join(failures)
                await self._publish_agent_stop_reason(
                    group_idx=group_idx,
                    key=key,
                    agent_name="Coder",
                    reason="所有 Coder 尝试均失败，子问题终止",
                    detail=final_reason,
                    level="error",
                )
                raise RuntimeError(
                    f"[组#{group_idx}] 所有 Coder 尝试均失败：" + final_reason
                )

            # ── 入口：固定主力 → 备用1 ──
            winner_interp, winner_coder_response = (
                await _run_coder_with_fallback()
            )

            step_counter[0] += 1
            await self._publish_progress(
                step_counter[0], total_steps,
                f"[组#{group_idx}] 求解完成: {key}，正在撰写",
            )
            # 确定胜出 Coder 标识
            winner_tag = getattr(winner_interp, "artifact_tag", "") or "主力"  # 可能为 "b1" 备用
            winner_label = {
                "": "主力",
                **{f"b{i}": f"备用{i}" for i in range(1, 10)},

            }.get(winner_tag, winner_tag)

            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=(
                        f"[组#{group_idx}] 代码手求解成功 {key}，"
                        f"胜出：{winner_label}"
                    ),
                    type="success",
                ),
            )

            # 图片描述（在 coder_semaphore 外执行，不阻塞其他 Coder）
            if (
                winner_coder_response.created_images
                and getattr(settings, "IMAGE_DESCRIPTION_ENABLED", False)
            ):
                desc_coro = self._describe_images(
                    image_filenames=winner_coder_response.created_images,
                    section_label=label,
                    writer_llm=writer_llm,
                )

                if getattr(settings, "IMAGE_DESCRIPTION_BACKGROUND", True):
                    asyncio.create_task(desc_coro)
                else:
                    await desc_coro

            # Writer 阶段：立即执行
            writer_prompt = flows.get_writer_prompt(
                key,
                winner_coder_response.code_response or "",
                winner_interp,
                config_template,
            )
            group_writer = self._create_writer_agent(problem, agent_index=group_idx)

            group_writer.model.question_index = group_idx
            group_writer.model.agent_instance_id = f'q{group_idx}.writer'
            group_writer.model.group_id = f'q{group_idx}'
            group_writer.model.phase = 'writing'

            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content=f"[组#{group_idx}] 论文手开始写 {key} 部分"),
            )
            writer_timeout = int(getattr(settings, "WRITER_ATTEMPT_TIMEOUT", None) or 0) or None
            try:
                writer_response = await asyncio.wait_for(
                    group_writer.run(
                        writer_prompt,
                        available_images=winner_coder_response.created_images,
                        sub_title=key,
                    ),
                    timeout=writer_timeout,
                )
            except asyncio.TimeoutError:
                await self._publish_agent_stop_reason(
                    group_idx=group_idx,
                    key=key,
                    agent_name="Writer",
                    reason=f"写作超时，超过 {writer_timeout} 秒",
                    detail="已终止该小问 Writer。建议降低章节内容长度或关闭缺图修复。",
                    level="error",
                )
                raise
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content=f"[组#{group_idx}] 论文手完成 {key} 部分"),
            )

            # 检查 Coder 生成的图片是否被 Writer 引用，缺图则自动修复一次
            missing_images = []
            for img in (winner_coder_response.created_images or []):
                basename = os.path.basename(img)
                if img not in writer_response.response_content and basename not in writer_response.response_content:
                    missing_images.append(img)

            if (
                missing_images
                and getattr(settings, "WRITER_IMAGE_REPAIR_ENABLED", False)
            ):
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=(
                            f"[组#{group_idx}] Writer 未引用部分生成图片："
                            + "、".join(missing_images[:5])
                        ),
                        type="warning",
                    ),
                )

                repair_prompt = f"""
你上一版没有引用以下已经生成的图片：

{chr(10).join(f"- {img}" for img in missing_images)}

请在不改变原有模型结果、公式和结论的前提下，重新输出本章节 Markdown。
必须把这些图片插入到最相关的结果分析段落附近，并给出简短图注和解释。

原章节内容：
{writer_response.response_content}
"""
                try:
                    repaired_response = await group_writer.run(
                        repair_prompt,
                        available_images=missing_images,
                        sub_title=key,
                    )
                    if repaired_response.response_content.strip():
                        writer_response = repaired_response
                        await redis_manager.publish_message(
                            self.task_id,
                            SystemMessage(
                                content=f"[组#{group_idx}] Writer 已自动修复缺图",
                                type="success",
                            ),
                        )
                        # 修复后重新检查
                        still_missing = []
                        for img in missing_images:
                            basename = os.path.basename(img)
                            if (
                                img not in writer_response.response_content
                                and basename not in writer_response.response_content
                            ):
                                still_missing.append(img)
                        if still_missing:
                            await redis_manager.publish_message(
                                self.task_id,
                                SystemMessage(
                                    content=(
                                        f"[组#{group_idx}] 修复后仍缺图："
                                        + "、".join(still_missing[:5])
                                    ),
                                    type="warning",
                                ),
                            )
                except Exception as exc:
                    logger.warning(f"[组#{group_idx}] Writer 缺图修复失败: {exc}")
            elif missing_images:
                checkpoint.setdefault("writer_missing_images", {})[key] = missing_images
                self._save_checkpoint(checkpoint)
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=(
                            f"[组#{group_idx}] Writer 未引用部分图片，已记录为非致命问题，"
                            f"不阻塞小问完成：{', '.join(missing_images[:5])}"
                        ),
                        type="warning",
                    ),
                )

            # 检查是否内容过长，如果过长则自动精简一次
            initial_content_check = validate_section_output(
                key,
                writer_response.response_content or "",
                self.ques_count,
                available_images=winner_coder_response.created_images,
            )
            length_issues = [issue for issue in initial_content_check if "内容过长" in issue]
            if length_issues:
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=f"[组#{group_idx}] 检测到 {key} 内容过长，正在自动精简",
                        type="warning",
                    ),
                )

                trim_prompt = f"""
你之前生成的"{key}"章节内容过长了。请精简内容，使其更加精炼，但保留所有关键模型结论、数值结果和图片引用。

要求：
1. 删除冗余的过程描述和重复的解释
2. 保留模型的核心思想、主要假设、关键公式和最终结果
3. 保留所有数值预测、对比分析和重要图表引用
4. 删除过多的中间步骤细节和冗长的背景介绍
5. 合并同义段落，精简过长的案例说明

输出格式仍为 Markdown，不要输出解释、检查报告或代码块围栏。

原章节内容：
{writer_response.response_content}
"""
                try:
                    trimmed_response = await asyncio.wait_for(
                        group_writer.run(
                            trim_prompt,
                            available_images=winner_coder_response.created_images,
                            sub_title=key,
                        ),
                        timeout=writer_timeout,
                    )
                    if trimmed_response.response_content.strip():
                        # 验证修剪后的内容是否仍然过长
                        trimmed_issues = validate_section_output(
                            key,
                            trimmed_response.response_content,
                            self.ques_count,
                            available_images=winner_coder_response.created_images,
                        )
                        if not any("内容过长" in issue for issue in trimmed_issues):
                            writer_response = trimmed_response
                            await redis_manager.publish_message(
                                self.task_id,
                                SystemMessage(
                                    content=f"[组#{group_idx}] 已自动精简 {key}，从 {len(writer_response.response_content or '')} 字符优化至 {len(trimmed_response.response_content or '')}",
                                    type="success",
                                ),
                            )
                except Exception as exc:
                    logger.warning(f"[组#{group_idx}] {key} 内容精简失败: {exc}")

            async with write_lock:
                user_output.set_res(key, writer_response)
                self._save_writer_checkpoint(checkpoint, key, writer_response)

            # 章节校验（子问题 Writer）
            section_issues = validate_section_output(
                key,
                writer_response.response_content or "",
                self.ques_count,
                available_images=winner_coder_response.created_images,
            )
            checkpoint["section_ledger"][key] = {
                "title": f"Question {group_idx}",
                "owner": f"q{group_idx}.writer",
                "status": "invalid" if section_issues else "valid",
                "attempts": 1,
                "content_chars": len(writer_response.response_content or ""),
                "issues": section_issues,
                "last_action": "generated",
            }
            if section_issues:
                logger.warning(f"[Group#{group_idx}] {key} section issues: {section_issues}")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=f"[Group#{group_idx}] {key} section validation: {'; '.join(section_issues[:3])}",
                        type="warning",
                    ),
                )
            self._save_checkpoint(checkpoint)

            # 胜者 interpreter 在 Writer 完成后清理
            try:
                await winner_interp.cleanup()
            except Exception as e:
                logger.warning(f"Question {key} winner interpreter cleanup failed: {e}")

            await self._publish_sub_coordinator(
                group_idx,
                f"子问题组#{group_idx} 完成 · {label} 建模、求解与写作全部完毕",
            )
            step_counter[0] += 1
            await self._publish_progress(
                step_counter[0], total_steps, f"[组#{group_idx}] 完成：{key}"
            )

        # 所有子问题组并发启动（无上限，有多少问就跑多少组）
        async def run_question_group_limited(group_idx: int, key: str) -> None:
            async with question_semaphore:
                group_timeout = int(getattr(settings, "QUESTION_GROUP_TIMEOUT", 1800))
                try:
                    await asyncio.wait_for(
                        run_question_group(group_idx, key),
                        timeout=group_timeout,
                    )
                except asyncio.TimeoutError:
                    await self._publish_agent_stop_reason(
                        group_idx=group_idx,
                        key=key,
                        agent_name="SubQuestionGroup",
                        reason=f"子问题组运行超时，超过 {group_timeout} 秒",
                        detail="可能卡在 Coder 自我修复、Writer 重写或产物检查。",
                        level="error",
                    )
                    checkpoint.setdefault("question_groups", {})[key] = {
                        "group_idx": group_idx,
                        "status": "timeout",
                        "reason": f"Exceeded {group_timeout}s",
                    }
                    self._save_checkpoint(checkpoint)
                    raise RuntimeError(
                        f"[组#{group_idx}] {key} 运行超时，超过 {group_timeout} 秒"
                    )

        group_tasks = [
            asyncio.create_task(run_question_group_limited(idx + 1, key))
            for idx, key in enumerate(question_keys)
        ]
        if group_tasks:
            try:
                await asyncio.gather(*group_tasks)
            except Exception:
                for t in group_tasks:
                    t.cancel()
                await asyncio.gather(*group_tasks, return_exceptions=True)
                raise

        await self._check_cancelled()

        # ── 阶段 5：全局协调者汇总，执行 sensitivity_analysis ────────────────
        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="全局协调者：所有子问题组已完成，开始灵敏度分析"),
        )

        sa_key = "sensitivity_analysis"
        if sa_key not in user_output.res:
            sa_coder = self._create_coder_agent(problem, code_interpreter, agent_index=None)
            sa_writer = self._create_writer_agent(problem, agent_index=None)
            await self._run_solution_step(
                key=sa_key,
                coder_prompt=solution_flows[sa_key]["coder_prompt"],
                problem=problem,
                flows=flows,
                code_interpreter=code_interpreter,
                config_template=config_template,
                writer_llm=writer_llm,
                solution_label_map=solution_label_map,
                coder_semaphore=coder_semaphore,
                write_lock=write_lock,
                checkpoint=checkpoint,
                user_output=user_output,
                group_index=None,
                coder_agent=sa_coder,
                writer_agent=sa_writer,
                step_counter=step_counter,
                total_steps=total_steps,
            )
        else:
            step_counter[0] += 2
            await self._publish_progress(
                step_counter[0], total_steps, "从断点恢复：灵敏度分析已完成"
            )

        # 关闭沙盒
        try:
            await code_interpreter.cleanup()
        except Exception as e:
            logger.warning(f"代码解释器清理失败: {e}")
        logger.info(user_output.get_res())

        await self._check_cancelled()

        # ── 阶段 6：并行写作（论文框架章节） ──────────────────────────────────
        write_flows = flows.get_write_flows(
            user_output, config_template, problem.ques_all
        )
        # TOC 确定性生成（不交给 LLM，确保覆盖所有小问）
        def _build_deterministic_toc(q_count: int) -> str:
            lines = [
                "## 目录",
                "",
                "一、问题重述",
                "1.1 问题背景",
                "1.2 问题重述",
                "",
                "二、问题分析",
            ]
            for i in range(1, q_count + 1):
                lines.append(f"2.{i} 问题{i}的分析")
            lines.extend([
                "",
                "三、模型假设",
                "",
                "四、符号说明和数据预处理",
                "4.1 符号说明",
                "4.2 描述性统计",
                "",
                "五、模型的建立与求解",
            ])
            for i in range(1, q_count + 1):
                lines.extend([
                    f"5.{i} 问题{i}模型的建立与求解",
                    f"5.{i}.1 模型的建立",
                    f"5.{i}.2 模型的求解",
                ])
            lines.extend([
                "",
                "六、模型的分析与检验",
                "6.1 灵敏度分析",
                "",
                "七、模型的评价、改进与推广",
            ])
            return "\n".join(lines).strip() + "\n"

        if "toc" not in user_output.res:
            from app.schemas.A2A import WriterResponse

            toc_content = _build_deterministic_toc(self.ques_count)
            toc_response = WriterResponse(
                response_content=toc_content,
                footnotes={},
            )
            user_output.set_res("toc", toc_response)
            self._save_writer_checkpoint(checkpoint, "toc", toc_response)
            checkpoint["section_ledger"]["toc"] = {
                "title": "TOC",
                "owner": "deterministic",
                "status": "valid",
                "attempts": 1,
                "content_chars": len(toc_content),
                "issues": [],
                "last_action": "generated_from_template",
            }
            self._save_checkpoint(checkpoint)
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="目录已按问题数量确定性生成，覆盖所有小问"),
            )

        pending_write_flows: list[tuple[str, str]] = []
        for key, value in write_flows.items():
            await self._check_cancelled()
            if key in user_output.res:
                step_counter[0] += 1
                await self._publish_progress(
                    step_counter[0], total_steps, f"从断点恢复：已完成 {key}"
                )
                continue
            # 跳过 toc（已确定性生成）
            if key == "toc":
                continue
            pending_write_flows.append((key, value))

        # 所有写作章节完全并行
        write_parallelism = max(1, len(pending_write_flows) or 1)
        write_semaphore = asyncio.Semaphore(write_parallelism)

        if pending_write_flows:
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=f"论文手并行写作启动，最多 {write_parallelism} 个章节同时进行"
                ),
            )

        async def run_write_flow(key: str, value: str, write_idx: int) -> None:
            nonlocal step_counter
            async with write_semaphore:
                await self._check_cancelled()
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content=f"论文写作组：开始写 {key} 部分"),
                )

                section_writer = self._create_writer_agent(problem, agent_index=None)

                # 关键：最后论文写作 Agent 不再使用 writer_7 / writer_8 这种会被误判成子问题的编号
                section_writer.model.agent_instance_id = f"paper.writer.{key}"
                section_writer.model.group_id = "paper.writing"
                section_writer.model.phase = "paper_writing"

                writer_response = await section_writer.run(prompt=value, sub_title=key)
                await self._check_cancelled()

                async with write_lock:
                    user_output.set_res(key, writer_response)
                    self._save_writer_checkpoint(checkpoint, key, writer_response)

                # 章节校验（论文写作 Writer）
                paper_issues = validate_section_output(
                    key,
                    writer_response.response_content or "",
                    self.ques_count,
                )
                checkpoint["section_ledger"][key] = {
                    "title": key,
                    "owner": f"paper.writer.{key}",
                    "status": "invalid" if paper_issues else "valid",
                    "attempts": 1,
                    "content_chars": len(writer_response.response_content or ""),
                    "issues": paper_issues,
                    "last_action": "generated",
                }
                if paper_issues:
                    logger.warning(f"paper writing {key} issues: {paper_issues}")
                self._save_checkpoint(checkpoint)

                async with write_lock:
                    step_counter[0] += 1
                    completed = step_counter[0]

                await self._publish_progress(completed, total_steps, f"完成撰写: {key}")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content=f"论文写作组：完成 {key} 部分"),
                )

        write_tasks = [
            asyncio.create_task(run_write_flow(key, value, i))
            for i, (key, value) in enumerate(pending_write_flows)
        ]
        if write_tasks:
            try:
                await asyncio.gather(*write_tasks)
            except Exception:
                for t in write_tasks:
                    t.cancel()
                await asyncio.gather(*write_tasks, return_exceptions=True)
                raise

        logger.info(user_output.get_res())

        # ── 阶段 7：终稿审计 + 必要时轻量 review ──────────────────────────────
        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="集成协调者：开始整合各组写作结果，启动终稿审计"),
        )

        final_paper = checkpoint.get("final_paper_review")

        _paper_source_sig = hashlib.sha256(
            json.dumps(user_output.res, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest() if hasattr(json, "dumps") else ""

        if (
            isinstance(final_paper, str)
            and final_paper.strip()
            and checkpoint.get("final_paper_source_signature") == _paper_source_sig
        ):
            pass  # valid cache, reuse
        else:
            final_paper = None

        section_label_map = {
            "firstPage": "标题、摘要、关键词",
            "toc": "目录",
            "RepeatQues": "问题重述",
            "analysisQues": "问题分析",
            "modelAssumption": "模型假设",
            "symbol": "符号说明和数据预处理",
            "eda": "探索性数据分析",
            "sensitivity_analysis": "模型检验和灵敏度分析",
            "judge": "模型评价、改进与推广",
        }
        section_order = [
            f"{key}: {section_label_map.get(key, key)}"
            for key in user_output.seq
        ]

        if isinstance(final_paper, str) and final_paper.strip():
            step_counter[0] += 1
            await self._publish_progress(
                step_counter[0], total_steps, "从断点恢复：已完成论文终稿检查"
            )
        else:
            step_counter[0] += 1
            await self._publish_progress(
                step_counter[0], total_steps, "论文手正在进行终稿审计"
            )
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="论文手开始终稿审计：检查章节重复、串位、图片引用"),
            )

            # ── Layer 2: Section ledger check + missing/invalid repair ──
            async def _repair_missing_or_invalid_sections() -> None:
                """Check section_ledger and attempt local repair for missing/invalid sections."""
                missing_keys = []
                invalid_keys = []

                for k in user_output.seq:
                    entry = checkpoint["section_ledger"].get(k)
                    if not entry or entry.get("status") == "missing":
                        missing_keys.append(k)
                    elif entry.get("status") == "invalid":
                        invalid_keys.append((k, entry.get("issues", [])))

                missing_set = set(missing_keys)
                invalid_set = {k for k, _ in invalid_keys}

                if not missing_keys and not invalid_keys:
                    return

                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=f"Section ledger: {len(missing_keys)} missing, {len(invalid_keys)} invalid, starting local repair"
                    ),
                )

                # TOC missing/invalid -> deterministic regeneration
                if "toc" in missing_keys or "toc" in [k for k, _ in invalid_keys]:
                    from app.schemas.A2A import WriterResponse

                    toc_content = _build_deterministic_toc(self.ques_count)
                    toc_response = WriterResponse(
                        response_content=toc_content,
                        footnotes={},
                    )
                    user_output.set_res("toc", toc_response)
                    self._save_writer_checkpoint(checkpoint, "toc", toc_response)
                    checkpoint["section_ledger"]["toc"] = {
                        "title": "TOC",
                        "owner": "deterministic",
                        "status": "valid",
                        "attempts": 1,
                        "content_chars": len(toc_content),
                        "issues": [],
                        "last_action": "regenerated_from_template",
                    }
                    await redis_manager.publish_message(
                        self.task_id,
                        SystemMessage(content="TOC regenerated deterministically"),
                    )

                # quesN missing/invalid -> rerun qN.writer with existing coder results
                repair_targets = list(dict.fromkeys(
                    missing_keys + [k for k, _ in invalid_keys]
                ))
                # toc 已在前面确定性修复，跳过
                repair_targets = [k for k in repair_targets if k != "toc"]

                for k in repair_targets:
                    repair_writer = self._create_writer_agent(problem, agent_index=None)
                    if k.startswith("ques"):
                        group_idx = int(k[4:])
                        await redis_manager.publish_message(
                            self.task_id,
                            SystemMessage(content=f"Repair: regenerating {k}"),
                        )
                        coder_result = checkpoint.get("coder_results", {}).get(k, {})
                        code_text = ""
                        images = []
                        if isinstance(coder_result, dict):
                            code_text = str(coder_result.get("code_response") or "")
                            images = coder_result.get("created_images") or []
                        question_text = str(self.questions.get(k, "")) if hasattr(self, "questions") else ""
                        model_summary = user_output.get_model_build_solve()
                        repair_prompt = f"""You are the dedicated Writer for Question {group_idx}.

[Task]
Regenerate the model building and solving chapter for {k}.

[Original Question]
{question_text}

[Model Solution Summary]
{model_summary}

[Requirements]
- Write ONLY Section 5.{group_idx} (model building and solving for Question {group_idx}).
- Must include the 5.{group_idx} section heading.
- Must include model formulation, solution method, and results interpretation.
- Do NOT write question restatement, question analysis, model assumptions, or model evaluation.
- Do NOT write content for other questions.
"""
                        repair_writer.model.question_index = group_idx
                        repair_writer.model.agent_instance_id = f"q{group_idx}.writer"
                        repair_writer.model.group_id = f"q{group_idx}"
                        repair_writer.model.phase = "question_writing"
                        try:
                            wr = await repair_writer.run(
                                repair_prompt,
                                available_images=images,
                                sub_title=k,
                            )
                            user_output.set_res(k, wr)
                            self._save_writer_checkpoint(checkpoint, k, wr)
                            re_issues = validate_section_output(
                                k, wr.response_content or "", self.ques_count, images
                            )
                            checkpoint["section_ledger"][k] = {
                                "title": f"Question {group_idx}",
                                "owner": f"q{group_idx}.writer",
                                "status": "invalid" if re_issues else "valid",
                                "attempts": 2,
                                "content_chars": len(wr.response_content or ""),
                                "issues": re_issues,
                                "last_action": "regenerated",
                            }
                            await redis_manager.publish_message(
                                self.task_id,
                                SystemMessage(content=f"Repaired: {k} regenerated"),
                            )
                        except Exception as exc:
                            logger.error(f"Repair {k} failed: {exc}")
                            checkpoint["section_ledger"][k] = (
                                checkpoint["section_ledger"].get(k) or {}
                            )
                            checkpoint["section_ledger"][k]["last_action"] = "repair_failed"
                            checkpoint["section_ledger"][k]["status"] = "missing"

                    else:
                        # 只有"缺账本但 user_output 已有内容"的旧断点场景，才允许补 ledger 不重跑
                        if k in missing_set and k not in invalid_set:
                            value = user_output.res.get(k)
                            content = ""
                            if isinstance(value, dict):
                                content = str(value.get("response_content") or "").strip()
                            if content:
                                issues = validate_section_output(k, content, self.ques_count)
                                checkpoint["section_ledger"][k] = {
                                    "title": k,
                                    "owner": "restored",
                                    "status": "invalid" if issues else "valid",
                                    "attempts": 0,
                                    "content_chars": len(content),
                                    "issues": issues,
                                    "last_action": "ledger_restored_from_user_output",
                                }
                                await redis_manager.publish_message(
                                    self.task_id,
                                    SystemMessage(content=f"Ledger: {k} restored from existing content"),
                                )
                                continue

                    if k in ("analysisQues", "modelAssumption", "symbol", "judge", "firstPage", "RepeatQues"):
                        repair_writer.model.agent_instance_id = f"paper.writer.{k}"
                        repair_writer.model.group_id = "paper.writing"
                        repair_writer.model.phase = "paper_writing"
                        try:
                            wr = await repair_writer.run(
                                prompt=write_flows.get(k, ""),
                                sub_title=k,
                            )
                            user_output.set_res(k, wr)
                            self._save_writer_checkpoint(checkpoint, k, wr)
                            re_issues = validate_section_output(
                                k, wr.response_content or "", self.ques_count
                            )
                            checkpoint["section_ledger"][k] = {
                                "title": k,
                                "owner": f"paper.writer.{k}",
                                "status": "invalid" if re_issues else "valid",
                                "attempts": 2,
                                "content_chars": len(wr.response_content or ""),
                                "issues": re_issues,
                                "last_action": "regenerated",
                            }
                        except Exception as exc:
                            logger.error(f"Repair {k} failed: {exc}")

                self._save_checkpoint(checkpoint)

            # Execute section repair loop
            await _repair_missing_or_invalid_sections()
            # 终稿前必备章节检查
            def _missing_required_sections() -> list:
                missing: list = []
                for k in user_output.seq:
                    value = user_output.res.get(k)
                    c = ""
                    if isinstance(value, dict):
                        c = str(value.get("response_content") or "").strip()
                    if not c:
                        missing.append(k)
                return missing

            # 终稿前 invalid section 检查
            invalid_sections = []
            for k in user_output.seq:
                value = user_output.res.get(k)
                content = ""
                if isinstance(value, dict):
                    content = str(value.get("response_content") or "").strip()
                issues = validate_section_output(k, content, self.ques_count)
                if issues:
                    invalid_sections.append({"key": k, "issues": issues})

            if invalid_sections:
                checkpoint["invalid_required_sections_before_final"] = invalid_sections
                self._save_checkpoint(checkpoint)
                raise RuntimeError(
                    "终稿生成前发现章节结构不合格，停止保存："
                    + "；".join(
                        f"{x['key']}: {','.join(x['issues'][:2])}"
                        for x in invalid_sections[:5]
                    )
                )

            missing_sections = _missing_required_sections()
            if missing_sections:
                checkpoint["missing_required_sections_before_final"] = missing_sections
                self._save_checkpoint(checkpoint)
                raise RuntimeError(
                    "终稿生成前发现章节缺失，停止保存不完整论文："
                    + "、".join(missing_sections)
                )

            # 按 seq 拼接原始草稿（走 get_result_to_save 包含脚注/参考文献处理）
            raw_draft = user_output.get_result_to_save()

            final_review_writer = self._create_writer_agent(problem, agent_index=None)

            try:
                # 第一步：audit（只检查，不重写）
                audit_result = await final_review_writer.audit_full_paper(
                    paper_markdown=raw_draft,
                    section_order=section_order,
                )

                checkpoint["final_paper_audit"] = audit_result
                self._save_checkpoint(checkpoint)

                high_issues = [
                    item for item in audit_result.get("issues", [])
                    if str(item.get("severity", "")).lower() in ("medium", "high")
                ]

                if not high_issues:
                    final_paper = clean_final_paper_markdown(raw_draft)
                    checkpoint["final_paper_source_signature"] = _paper_source_sig
                    await redis_manager.publish_message(
                        self.task_id,
                        SystemMessage(content="终稿审计通过，无需全文重写", type="success"),
                    )
                else:
                    await redis_manager.publish_message(
                        self.task_id,
                        SystemMessage(
                            content=f"终稿审查发现 {len(high_issues)} 个中高风险问题，启动全文轻量修正",
                            type="warning",
                        ),
                    )

                    repair_response = await final_review_writer.repair_full_paper_by_audit(
                        paper_markdown=raw_draft,
                        audit_issues=high_issues,
                        section_order=section_order,
                    )
                    repaired = clean_final_paper_markdown(repair_response.response_content)

                    # 终稿轻量修正保护：不应大幅删减或丢失章节
                    required_tokens = [
                        "一、问题重述",
                        "二、问题分析",
                        "三、模型假设",
                        "四、符号说明",
                        "五、模型的建立与求解",
                        "六、模型",
                        "七、模型",
                    ]
                    for _i in range(1, self.ques_count + 1):
                        required_tokens.append(f"5.{_i}")

                    _missing_tokens = [
                        token for token in required_tokens if token not in repaired
                    ]

                    if _missing_tokens or len(repaired) < len(raw_draft) * 0.75:
                        checkpoint["final_repair_rejected"] = {
                            "missing_tokens": _missing_tokens,
                            "raw_len": len(raw_draft),
                            "repaired_len": len(repaired),
                        }
                        self._save_checkpoint(checkpoint)
                        await redis_manager.publish_message(
                            self.task_id,
                            SystemMessage(
                                content="终稿轻量修正疑似删减章节，已拒绝修正版，保留原始拼接稿",
                                type="warning",
                            ),
                        )
                        final_paper = clean_final_paper_markdown(raw_draft)
                    else:
                        final_paper = repaired
                        await redis_manager.publish_message(
                            self.task_id,
                            SystemMessage(content="论文手完成终稿轻量修正"),
                        )

                checkpoint["final_paper_review"] = final_paper
                checkpoint["final_paper_source_signature"] = _paper_source_sig
                self._save_checkpoint(checkpoint)

            except Exception as e:
                logger.warning(f"论文终稿检查失败，使用原始拼接稿: {e}")
                final_paper = user_output.get_result_to_save()
                checkpoint["final_paper_review_failed"] = str(e)
                self._save_checkpoint(checkpoint)

        # 图片引用校验
        image_ref_issues = validate_markdown_image_refs(self.work_dir, final_paper)
        if image_ref_issues:
            checkpoint["final_image_ref_issues"] = image_ref_issues
            self._save_checkpoint(checkpoint)
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content="终稿图片引用检查发现问题：" + "；".join(image_ref_issues[:5]),
                    type="warning",
                ),
            )

        # 终稿完整性总检查
        paper_issues = validate_final_paper(self.work_dir, final_paper)
        if paper_issues:
            checkpoint["final_paper_issues"] = paper_issues
            self._save_checkpoint(checkpoint)
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content="终稿完整性检查发现问题：" + "；".join(paper_issues[:5]),
                    type="warning",
                ),
            )

        user_output.save_result(final_text=final_paper)
        file_issues = validate_saved_files(self.work_dir)
        if file_issues:
            checkpoint["final_file_issues"] = file_issues
            self._save_checkpoint(checkpoint)
        checkpoint["completed"] = True
        self._save_checkpoint(checkpoint)

        step_counter[0] += 1
        await self._publish_progress(step_counter[0], total_steps, "论文生成完成")
        await mark_task_terminal(
            self.task_id,
            "completed",
            "论文生成完成",
        )
