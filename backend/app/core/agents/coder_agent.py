"""代码手 Agent 模块，负责生成和执行 Python 代码完成建模任务。"""

import asyncio
import json
from app.core.agents.agent import Agent
from app.config.setting import settings
from app.utils.log_util import logger
from app.services.redis_manager import redis_manager
from app.schemas.response import SystemMessage, InterpreterMessage
from app.tools.base_interpreter import BaseCodeInterpreter
from app.core.llm.llm import LLM
from app.schemas.A2A import CoderToWriter
from app.core.prompts import CODER_PROMPT
from app.utils.common_utils import get_current_files
from app.core.prompts import get_reflection_prompt
from app.core.functions import coder_tools
from app.utils.repeat_error_judge import judge_repeated_error, error_signature


class CoderAgent(Agent):
    """代码手 Agent，通过 LLM 生成代码并在解释器中执行，支持错误反思。"""

    def __init__(
        self,
        task_id: str,
        model: LLM,
        work_dir: str,
        max_retries: int | None = None,
        code_interpreter: BaseCodeInterpreter | None = None,
        context_window: int = 128000,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        super().__init__(task_id, model, context_window, cancel_event=cancel_event)
        self.work_dir = work_dir
        configured_retries = (
            max_retries
            if max_retries is not None
            else (
                settings.MAX_RETRIES
                if getattr(settings, "MAX_RETRIES", None) not in (None, 0)
                else settings.CODER_MAX_RETRIES
            )
        )
        self.max_retries = int(configured_retries) if configured_retries not in (None, 0) else None
        self.is_first_run = True
        self.system_prompt = CODER_PROMPT
        self.code_interpreter = code_interpreter

    async def run(self, prompt: str, subtask_title: str) -> CoderToWriter:  # type: ignore[reportIncompatibleMethodOverride]
        logger.info(f"{self.__class__.__name__}:开始:执行子任务: {subtask_title}")
        assert self.code_interpreter is not None, "code_interpreter 未初始化"
        self.code_interpreter.add_section(subtask_title)

        from app.utils.image_constants import get_section_num

        section_num = get_section_num(subtask_title)
        if section_num:
            naming_reminder = (
                f"【系统提示】你当前正在处理章节：{subtask_title}（论文编号 {section_num}）。"
                "章节编号由系统目录管理，图片文件名只写英文语义名，"
                "例如 prediction_result.png、model_diagnostics.png、sensitivity_curve.png。"
                "不要使用中文、空格、fig1、figure1、图1，也不要在图片名前重复添加章节号前缀。"
                "系统会自动把图片和对应 Python 文件归入当前章节目录。"
            )
            prompt = f"{naming_reminder}\n\n{prompt}"

        tools = coder_tools

        if self.is_first_run:
            logger.info("首次运行，添加系统提示和数据集文件信息")
            self.is_first_run = False
            await self.append_chat_history({"role": "system", "content": self.system_prompt})
            await self.append_chat_history(
                {
                    "role": "user",
                    "content": f"当前文件夹下的数据集文件{get_current_files(self.work_dir, 'data')}",
                }
            )

        logger.info(f"添加子任务提示: {prompt}")
        await self.append_chat_history({"role": "user", "content": prompt})

        retry_count = 0
        last_error_message = ""
        consecutive_same_error_count = 0
        total_execute_count = 0
        max_total_steps = int(getattr(settings, "CODER_MAX_TOTAL_STEPS", 0) or 0)
        last_error_type = ""
        has_executed_code = False

        # 协调者错误判别：旁路异步，不阻塞当前 Coder。
        judge_min_errors = int(getattr(settings, "CODER_REPEAT_ERROR_JUDGE_MIN_ERRORS", 3) or 3)
        judge_interval = max(1, int(getattr(settings, "CODER_REPEAT_ERROR_JUDGE_INTERVAL", 2) or 2))
        pending_judge_task: asyncio.Task | None = None
        restart_requested = False
        restart_reason = ""

        async def _consume_judge_if_ready() -> None:
            nonlocal pending_judge_task, restart_requested, restart_reason
            if pending_judge_task is None or not pending_judge_task.done():
                return
            try:
                judge = pending_judge_task.result()
            except asyncio.CancelledError:
                pending_judge_task = None
                return
            except Exception as exc:
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content=f"协调者重复错误判别失败，当前 Coder 继续试错：{exc}", type="warning"),
                )
                pending_judge_task = None
                return

            pending_judge_task = None
            same_error = bool(judge.get("same_error"))
            should_restart = bool(judge.get("should_restart"))
            root_cause = str(judge.get("root_cause") or last_error_type or "unknown")[:160]
            advice = str(judge.get("advice") or "")
            reason = str(judge.get("reason") or "")

            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=(
                        f"协调者后台错误判别完成：same_error={same_error}, should_restart={should_restart}\n"
                        f"根因：{root_cause}\n"
                        f"建议：{advice}\n"
                        f"依据：{reason}"
                    ),
                    type="warning" if should_restart or same_error else "info",
                ),
            )

            if should_restart:
                restart_requested = True
                restart_reason = (
                    f"协调者建议切换新 Coder；根因：{root_cause}；依据：{reason}；建议：{advice}"
                )
                return

            if same_error and advice:
                await self.append_chat_history(
                    {
                        "role": "user",
                        "content": (
                            "【协调者后台建议】你可能正在重复处理同类错误。"
                            "当前任务继续由你处理，但下一步必须改变修复策略。\n"
                            f"错误根因：{root_cause}\n"
                            f"建议：{advice}\n"
                        ),
                    }
                )

        def _should_start_judge() -> bool:
            if not getattr(settings, "CODER_REPEAT_ERROR_JUDGE_ENABLED", True):
                return False
            if pending_judge_task is not None and not pending_judge_task.done():
                return False
            if retry_count < judge_min_errors:
                return False
            return (retry_count - judge_min_errors) % judge_interval == 0

        while True:
            total_execute_count += 1
            await _consume_judge_if_ready()

            if restart_requested:
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=(
                            f"代码手已停止：协调者后台判定需要切换新 Coder\n"
                            f"子任务：{subtask_title}\n"
                            f"停止详情：{restart_reason}\n"
                            f"最后错误：{last_error_message[:1000]}"
                        ),
                        type="error",
                    ),
                )
                raise RuntimeError(
                    f"代码手求解失败：协调者后台判定需要切换新 Coder，子任务：{subtask_title}，{restart_reason}"
                )

            if max_total_steps > 0 and total_execute_count > max_total_steps:
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=(
                            f"代码手已停止：总执行步数超过上限({max_total_steps})\n"
                            f"子任务：{subtask_title}\n"
                            f"停止原因：显式启用的总步数保护触发\n"
                            f"最后错误：{last_error_message[:1000]}"
                        ),
                        type="error",
                    ),
                )
                raise RuntimeError(
                    f"代码手求解失败：总执行步数超过上限 {max_total_steps}，"
                    f"子任务：{subtask_title}，最后错误：{last_error_message}"
                )

            if self.max_retries is not None and retry_count >= self.max_retries:
                logger.error(f"超过最大重试次数: {self.max_retries}")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=(
                            f"代码手已停止：超过最大重试次数({self.max_retries})\n"
                            f"子任务：{subtask_title}\n"
                            f"停止原因：显式启用的总重试保护触发\n"
                            f"最后错误：{last_error_message[:1000]}"
                        ),
                        type="error",
                    ),
                )
                raise RuntimeError(
                    f"代码手求解失败：达到最大重试次数 {self.max_retries}，子任务：{subtask_title}，"
                    f"最后错误：{last_error_message}"
                )

            try:
                response = await self._chat(
                    stream=True,
                    history=self.chat_history,
                    tools=tools,
                    tool_choice="auto",
                    agent_name=self.__class__.__name__,
                )

                if response.tool_calls:
                    logger.info("检测到工具调用")
                    tool_call = response.tool_calls[0]
                    tool_id = tool_call.id

                    if tool_call.name == "task_complete":
                        if not has_executed_code:
                            logger.info("代码手未执行代码却调用 task_complete，已拒绝完成")
                            retry_count += 1
                            last_error_message = "代码手未调用 execute_code 工具，不能直接 task_complete"
                            error_type = "no_execute_before_complete"
                            if error_type == last_error_type:
                                consecutive_same_error_count += 1
                            else:
                                consecutive_same_error_count = 1
                                last_error_type = error_type

                            await self.append_chat_history(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "name": "task_complete",
                                    "content": "拒绝完成：本任务必须至少调用一次 execute_code 工具。",
                                }
                            )
                            await self.append_chat_history(
                                {
                                    "role": "user",
                                    "content": (
                                        "你还没有调用 execute_code 工具。"
                                        "请先执行 Python 代码完成数据读取、建模、计算或结果生成，"
                                        "确认结果后再调用 task_complete。"
                                    ),
                                }
                            )
                            continue

                        if pending_judge_task is not None and not pending_judge_task.done():
                            pending_judge_task.cancel()
                        logger.info("任务完成信号")
                        await redis_manager.publish_message(
                            self.task_id,
                            SystemMessage(content="代码手完成任务", type="success"),
                        )
                        return CoderToWriter(
                            code_response=response.content,
                            created_images=await self.code_interpreter.get_created_images(subtask_title),
                        )

                    if tool_call.name == "execute_code":
                        logger.info(f"调用工具: {tool_call.name}")
                        await redis_manager.publish_message(
                            self.task_id,
                            SystemMessage(content=f"代码手调用{tool_call.name}工具"),
                        )

                        code = json.loads(tool_call.arguments)["code"]
                        code_description = response.content.strip() if response.content else None

                        await redis_manager.publish_message(
                            self.task_id,
                            InterpreterMessage(input={"code": code}, description=code_description),
                        )

                        assistant_msg: dict = {"role": "assistant", "content": response.content}
                        if response.reasoning_content:
                            assistant_msg["reasoning_content"] = response.reasoning_content
                        if response.tool_calls:
                            assistant_msg["tool_calls"] = [
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {"name": tc.name, "arguments": tc.arguments},
                                }
                                for tc in response.tool_calls
                            ]
                        await self.append_chat_history(assistant_msg)

                        logger.info("执行工具调用")
                        text_to_gpt, error_occurred, error_message = await self.code_interpreter.execute_code(code)

                        if error_occurred:
                            await self.append_chat_history(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "name": "execute_code",
                                    "content": error_message,
                                }
                            )

                            logger.warning(f"代码执行错误: {error_message}")
                            retry_count += 1
                            previous_error_message = last_error_message
                            last_error_message = error_message

                            current_signature = error_signature(error_message)
                            previous_signature = error_signature(previous_error_message) if previous_error_message else ""
                            if previous_signature and current_signature == previous_signature:
                                consecutive_same_error_count += 1
                            else:
                                consecutive_same_error_count = 1
                            last_error_type = current_signature

                            if _should_start_judge():
                                await redis_manager.publish_message(
                                    self.task_id,
                                    SystemMessage(
                                        content=(
                                            f"协调者后台错误判别已启动：累计错误 {retry_count} 次，"
                                            f"当前 Coder 不等待判别结果，继续自行反思修复。"
                                        ),
                                        type="info",
                                    ),
                                )
                                pending_judge_task = asyncio.create_task(
                                    judge_repeated_error(
                                        task_id=self.task_id,
                                        subtask_title=subtask_title,
                                        previous_error=previous_error_message,
                                        current_error=error_message,
                                        current_code=code,
                                        same_count=consecutive_same_error_count,
                                        retry_count=retry_count,
                                    )
                                )

                            reflection_prompt = get_reflection_prompt(error_message, code)
                            if pending_judge_task is not None and not pending_judge_task.done():
                                reflection_prompt = (
                                    "【系统提示】协调者正在后台判断错误是否重复；你不要等待协调者结果，"
                                    "继续基于当前报错自行修复。\n\n"
                                    + reflection_prompt
                                )

                            await redis_manager.publish_message(
                                self.task_id,
                                SystemMessage(content="代码手自行反思纠错，协调者后台判别不阻塞当前尝试", type="info"),
                            )
                            await self.append_chat_history({"role": "user", "content": reflection_prompt})
                            continue

                        await self.append_chat_history(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "name": "execute_code",
                                "content": text_to_gpt,
                            }
                        )
                        if pending_judge_task is not None and not pending_judge_task.done():
                            pending_judge_task.cancel()
                            pending_judge_task = None
                        retry_count = 0
                        consecutive_same_error_count = 0
                        last_error_type = ""
                        last_error_message = ""
                        has_executed_code = True
                        continue

                    logger.warning(f"未知工具调用: {tool_call.name}")
                    await self.append_chat_history(
                        {
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "name": tool_call.name,
                            "content": f"未知工具: {tool_call.name}",
                        }
                    )
                    continue

                if not has_executed_code:
                    logger.info("代码手未调用 execute_code，强制要求至少执行一次")
                    retry_count += 1
                    last_error_message = "代码手未调用 execute_code 工具"
                    error_type = "no_tool_call"
                    if error_type == last_error_type:
                        consecutive_same_error_count += 1
                    else:
                        consecutive_same_error_count = 1
                        last_error_type = error_type
                    await self.append_chat_history({"role": "assistant", "content": response.content or ""})
                    await self.append_chat_history(
                        {
                            "role": "user",
                            "content": (
                                "你还没有调用 execute_code 工具。"
                                "本任务必须至少执行一次 Python 代码，读取数据、建模或生成结果后，"
                                "再调用 task_complete。请继续。"
                            ),
                        }
                    )
                    continue

                if pending_judge_task is not None and not pending_judge_task.done():
                    pending_judge_task.cancel()
                logger.info("没有工具调用，任务完成")
                return CoderToWriter(
                    code_response=response.content,
                    created_images=await self.code_interpreter.get_created_images(subtask_title),
                )

            except asyncio.CancelledError:
                if pending_judge_task is not None and not pending_judge_task.done():
                    pending_judge_task.cancel()
                raise
            except Exception as e:
                logger.error(f"执行过程中发生异常: {str(e)}")
                retry_count += 1
                last_error_message = str(e)
                error_type = str(e)[:100]
                if error_type == last_error_type:
                    consecutive_same_error_count += 1
                else:
                    consecutive_same_error_count = 1
                    last_error_type = error_type
                continue
