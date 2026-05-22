"""工作流模块，编排多 Agent 协作完成数学建模任务。

并行架构：每个子问题绑定独立的 (SubCoordinator + Modeler + Coder + Writer) 组，
多组并行运行。每个子问题 Coder 使用独立 Jupyter kernel，信号量只限制并发上限。
EDA 和 sensitivity_analysis 作为独立阶段顺序执行。
"""

import asyncio
import json
import os
from app.core.agents import WriterAgent, CoderAgent, CoordinatorAgent, ModelerAgent
from app.schemas.request import Problem
from app.schemas.response import SystemMessage, ProgressMessage, SubCoordinatorMessage
from app.tools.openalex_scholar import OpenAlexScholar
from app.utils.log_util import logger
from app.utils.common_utils import create_work_dir, get_config_template
from app.models.user_output import UserOutput, clean_final_paper_markdown
from app.schemas.A2A import CoordinatorToModeler, ModelerToCoder
from app.config.setting import settings
from app.tools.interpreter_factory import create_interpreter
from app.services.redis_manager import redis_manager
from app.services.task_state import mark_task_running
from app.tools.notebook_serializer import NotebookSerializer
from app.core.flows import Flows
from app.core.llm.llm import LLM
from app.core.llm.llm_factory import LLMFactory
from app.utils.image_code_index import update_image_metadata
from app.utils.image_describer import generate_image_description
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
    task_id: str
    work_dir: str
    ques_count: int = 0
    questions: dict[str, str | int] = {}
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
            max_retries=settings.MAX_RETRIES,
            code_interpreter=code_interpreter,
            context_window=settings.CODER_CONTEXT_WINDOW,
            cancel_event=self.cancel_event,
        )

    async def _create_code_interpreter(self, key: str, worker_suffix: str = ""):
        """创建代码解释器。

        Args:
            key: 章节标识（如 "ques1"、"eda"）。
            worker_suffix: 竞速 worker 后缀（如 "_w0"、"_w1"），
                           确保每个竞速 worker 写入不同的 notebook 文件，避免并发覆盖。
        """
        if key == "eda":
            notebook_name = "notebook.ipynb"
        else:
            notebook_name = f"{key}{worker_suffix}.ipynb"
        notebook_serializer = NotebookSerializer(
            work_dir=self.work_dir,
            notebook_name=notebook_name,
        )
        return await create_interpreter(
            kind="local",
            task_id=self.task_id,
            work_dir=self.work_dir,
            notebook_serializer=notebook_serializer,
            timeout=3000,
        )

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
    ) -> str:
        prefix = self._section_image_prefix(key)
        examples = f"{prefix}_prediction_result.png, {prefix}_model_diagnostics.png"
        return f"""{coder_prompt}

[Parallel image naming rule — MANDATORY]
- For the current subtask `{key}`, every saved image filename MUST start with the paper-section prefix `{prefix}_`.
- Filename format: `{prefix}_short_english_name.png`
  The descriptive part MUST use ONLY ASCII letters, digits, underscores and hyphens.
  NO Chinese characters, NO spaces, NO special chars.
- Examples: {examples}
- Do NOT use global figure names such as `fig1_...png`, `fig_q...png`, or `fig_sens...png`.
- WARNING: Images violating this naming rule will be rejected by the validation layer.

REMINDER: Before EVERY execute_code call, you MUST still output the ## 代码介绍 block
(所属阶段 / 功能说明 / 预期产出) as required by the system prompt. This is NOT optional.
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
        await redis_manager.publish_message(
            self.task_id,
            SubCoordinatorMessage(
                content=content,
                agent_index=group_index,
            ),
        )

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

        # 图片描述（在 coder_semaphore 外执行，不阻塞下一个 coder）
        if coder_response.created_images:
            await self._describe_images(
                image_filenames=coder_response.created_images,
                section_label=label,
                writer_llm=writer_llm,
            )

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

        async with write_lock:
            user_output.set_res(key, writer_response)
            self._save_writer_checkpoint(checkpoint, key, writer_response)

    async def execute(self, problem: Problem):  # type: ignore[reportIncompatibleMethodOverride]
        """执行数学建模工作流（并行多组架构）。

        Args:
            problem: 包含题目信息、模板配置等的 Problem 对象。
        """
        self.task_id = problem.task_id
        self.work_dir = create_work_dir(self.task_id)
        checkpoint = self._load_checkpoint()

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
        write_flow_count = 6  # firstPage, RepeatQues, analysisQues, modelAssumption, symbol, judge
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
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
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
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
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
        modeler_agent = ModelerAgent(
            self.task_id, modeler_llm,
            context_window=settings.MODELER_CONTEXT_WINDOW,
            cancel_event=self.cancel_event,
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

        # 并发控制：每个子问题完全并行（每组独立 kernel，无共享状态）
        # coder_semaphore 容量 = 问题数，确保每问最多同时跑一个胜者 Coder；
        # 竞速输家被 cancel 后会释放额度，空闲额度自动流向其他问题的等待 Coder（跨问协作）
        question_parallelism = max(1, self.ques_count or 1)
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
            racing_workers_count = max(1, int(getattr(settings, "CODER_RACING_WORKERS", 2)))
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=(
                        f"全局协调者：启动 {len(question_keys)} 个子问题并行组，"
                        f"每问竞速 {racing_workers_count} 个 Coder（先完成者胜出）"
                    )
                ),
            )

        async def run_question_group(group_idx: int, key: str) -> None:
            """运行单个子问题组，使用双竞速 Coder 架构。

            为每个子问题同时启动 RACING_WORKERS 个独立 Coder，
            哪个先完成就用哪个结果，其余取消。信号量的释放会自动把空闲额度
            让给其他尚未完成问题的等待 Coder，实现跨问协作。
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

            coder_prompt = self._with_image_position_hint(
                solution_flows[key]["coder_prompt"], key, group_idx
            )

            # ── 双竞速 Coder：为本问创建 N 个独立 interpreter+coder 同时跑 ──
            racing_workers = max(1, int(getattr(settings, "CODER_RACING_WORKERS", 2)))
            racing_interpreters: list = []
            racing_coders: list[CoderAgent] = []
            for w in range(racing_workers):
                # 每个竞速 worker 使用独立 notebook 文件，避免并发写入时互相覆盖
                interp = await self._create_code_interpreter(key, worker_suffix=f"_w{w}")
                coder = self._create_coder_agent(
                    problem, interp, agent_index=group_idx
                )
                racing_interpreters.append(interp)
                racing_coders.append(coder)

            async def _run_one_racing_coder(interp, coder, worker_num: int):
                """单个竞速 Coder：在信号量内执行，完成后返回 (interpreter, CoderToWriter)。"""
                async with coder_semaphore:
                    await self._check_cancelled()
                    await redis_manager.publish_message(
                        self.task_id,
                        SystemMessage(
                            content=(
                                f"[组#{group_idx}·竞速{worker_num + 1}/{racing_workers}]"
                                f" 代码手开始求解 {key}"
                            )
                        ),
                    )
                    result = await coder.run(prompt=coder_prompt, subtask_title=key)
                return interp, result

            coder_tasks = [
                asyncio.create_task(_run_one_racing_coder(interp, coder, w))
                for w, (interp, coder) in enumerate(
                    zip(racing_interpreters, racing_coders)
                )
            ]

            winner_interp = None
            winner_coder_response = None
            try:
                # 等第一个完成的竞速 Coder；若失败则继续等其余
                remaining = set(coder_tasks)
                while remaining and winner_coder_response is None:
                    done, remaining = await asyncio.wait(
                        remaining, return_when=asyncio.FIRST_COMPLETED
                    )
                    for t in done:
                        try:
                            winner_interp, winner_coder_response = t.result()
                            break
                        except Exception as exc:
                            logger.warning(f"[组#{group_idx}] 竞速 Coder 失败: {exc}")

                if winner_coder_response is None:
                    raise RuntimeError(
                        f"[组#{group_idx}] 所有 {racing_workers} 个竞速 Coder 均失败"
                    )

                # 取消并等待输家退出（释放信号量额度，供其他问题使用）
                for t in remaining:
                    t.cancel()
                await asyncio.gather(*remaining, return_exceptions=True)

            except Exception:
                # 异常时取消所有任务并清理所有 interpreter
                for t in coder_tasks:
                    t.cancel()
                await asyncio.gather(*coder_tasks, return_exceptions=True)
                for interp in racing_interpreters:
                    try:
                        await interp.cleanup()
                    except Exception:
                        pass
                raise
            else:
                # 仅清理输家的 interpreter；胜者留给 Writer 使用
                for interp in racing_interpreters:
                    if interp is not winner_interp:
                        try:
                            await interp.cleanup()
                        except Exception:
                            pass

            step_counter[0] += 1
            await self._publish_progress(
                step_counter[0], total_steps,
                f"[组#{group_idx}] 求解完成: {key}，正在撰写",
            )
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content=f"[组#{group_idx}] 代码手求解成功 {key}", type="success"),
            )

            # 图片描述（在 coder_semaphore 外执行，不阻塞其他 Coder）
            if winner_coder_response.created_images:
                await self._describe_images(
                    image_filenames=winner_coder_response.created_images,
                    section_label=label,
                    writer_llm=writer_llm,
                )

            # Writer 阶段：立即执行
            writer_prompt = flows.get_writer_prompt(
                key,
                winner_coder_response.code_response or "",
                winner_interp,
                config_template,
            )
            group_writer = self._create_writer_agent(problem, agent_index=group_idx)

            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content=f"[组#{group_idx}] 论文手开始写 {key} 部分"),
            )
            writer_response = await group_writer.run(
                writer_prompt,
                available_images=winner_coder_response.created_images,
                sub_title=key,
            )
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content=f"[组#{group_idx}] 论文手完成 {key} 部分"),
            )

            async with write_lock:
                user_output.set_res(key, writer_response)
                self._save_writer_checkpoint(checkpoint, key, writer_response)

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
                await run_question_group(group_idx, key)

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
        pending_write_flows: list[tuple[str, str]] = []
        for key, value in write_flows.items():
            await self._check_cancelled()
            if key in user_output.res:
                step_counter[0] += 1
                await self._publish_progress(
                    step_counter[0], total_steps, f"从断点恢复：已完成 {key}"
                )
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

        # 写作手编号：从 n+1 开始（避免与子问题组编号冲突）
        write_agent_offset = self.ques_count + 1

        async def run_write_flow(key: str, value: str, write_idx: int) -> None:
            nonlocal step_counter
            async with write_semaphore:
                await self._check_cancelled()
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content=f"论文手开始写{key}部分"),
                )

                section_writer = self._create_writer_agent(problem, agent_index=write_agent_offset + write_idx)
                writer_response = await section_writer.run(prompt=value, sub_title=key)
                await self._check_cancelled()

                async with write_lock:
                    user_output.set_res(key, writer_response)
                    self._save_writer_checkpoint(checkpoint, key, writer_response)
                    step_counter[0] += 1
                    completed = step_counter[0]

                await self._publish_progress(completed, total_steps, f"完成撰写: {key}")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content=f"论文手完成{key}部分"),
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

        # ── 阶段 7：集成协调者 + 终稿审查 ────────────────────────────────────
        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="集成协调者：开始整合各组写作结果，启动终稿整体检查"),
        )

        final_paper = checkpoint.get("final_paper_review")
        section_label_map = {
            "firstPage": "标题、摘要、关键词",
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
                step_counter[0], total_steps, "从断点恢复：已完成论文终稿整体检查"
            )
        else:
            step_counter[0] += 1
            await self._publish_progress(
                step_counter[0], total_steps, "论文手正在进行终稿整体检查"
            )
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content="论文手开始终稿整体检查：单次全文 review，重排章节、去重、统一参考文献"
                ),
            )
            try:
                # 拼接所有章节草稿，整体发给 WriterAgent 做一次性全文 review
                # （替代原来逐节 extract_section_from_draft 的 N+8 次调用）
                raw_draft = "\n\n".join(
                    str(user_output.res.get(key, {}).get("response_content") or "")
                    for key in user_output.seq
                    if key in user_output.res
                )

                final_review_writer = self._create_writer_agent(problem, agent_index=None)
                review_response = await final_review_writer.review_full_paper(
                    paper_markdown=raw_draft,
                    section_order=section_order,
                )
                final_paper = clean_final_paper_markdown(review_response.response_content)
                checkpoint["final_paper_review"] = final_paper
                self._save_checkpoint(checkpoint)
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content="论文手完成终稿整体检查"),
                )
            except Exception as e:
                logger.warning(f"论文终稿整体检查失败，使用原始拼接稿: {e}")
                final_paper = user_output.get_result_to_save()
                checkpoint["final_paper_review_failed"] = str(e)
                self._save_checkpoint(checkpoint)

        user_output.save_result(final_text=final_paper)
        checkpoint["completed"] = True
        self._save_checkpoint(checkpoint)

        step_counter[0] += 1
        await self._publish_progress(step_counter[0], total_steps, "论文生成完成")
