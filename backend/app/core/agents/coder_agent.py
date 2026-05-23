"""代码手 Agent 模块，负责生成和执行 Python 代码完成建模任务。"""

import asyncio
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
import json
from app.core.prompts import get_reflection_prompt
from app.core.functions import coder_tools

# TODO: 时间等待过久，stop 进程
# TODO: 支持 cuda
# TODO: 引入创新方案：


class CoderAgent(Agent):
    """代码手 Agent，通过 LLM 生成代码并在解释器中执行，支持错误反思和重试。"""
    def __init__(
        self,
        task_id: str,
        model: LLM,
        work_dir: str,  # 工作目录
        max_retries: int | None = None,  # None 时自动从 settings 读取
        code_interpreter: BaseCodeInterpreter | None = None,
        context_window: int = 128000,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        super().__init__(task_id, model, context_window, cancel_event=cancel_event)
        self.work_dir = work_dir
        self.max_retries = (
            max_retries
            if max_retries is not None
            else int(
                settings.MAX_RETRIES
                if getattr(settings, "MAX_RETRIES", None) is not None
                else settings.CODER_MAX_RETRIES
            )
        )
        self.is_first_run = True
        self.system_prompt = CODER_PROMPT
        self.code_interpreter = code_interpreter

    async def run(self, prompt: str, subtask_title: str) -> CoderToWriter:  # type: ignore[reportIncompatibleMethodOverride]
        """执行代码手子任务，生成并运行代码。

        Args:
            prompt: 子任务描述。
            subtask_title: 子任务标题，用于分段输出。

        Returns:
            CoderToWriter 对象，包含代码执行结果和生成的图片列表。
        """
        logger.info(f"{self.__class__.__name__}:开始:执行子任务: {subtask_title}")
        assert self.code_interpreter is not None, "code_interpreter 未初始化"
        self.code_interpreter.add_section(subtask_title)

        # 注入当前章节的命名前缀，确保 LLM 生成代码时使用正确的图片/代码文件命名
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

        # 统一使用 OpenAI 格式，由各 Provider 的 _convert_tools 负责转换
        # 注意：不应传入 coder_tools_anthropic，因为 AnthropicProvider._convert_tools
        # 只识别 OpenAI 格式（type=="function"），传入已转换格式会导致 tools 被过滤为空列表，
        # 模型收不到工具定义，从而完全跳过代码执行直接返回文本。
        tools = coder_tools

        # 如果是第一次运行，则添加系统提示
        if self.is_first_run:
            logger.info("首次运行，添加系统提示和数据集文件信息")
            self.is_first_run = False
            await self.append_chat_history(
                {"role": "system", "content": self.system_prompt}
            )
            # 当前数据集文件
            await self.append_chat_history(
                {
                    "role": "user",
                    "content": f"当前文件夹下的数据集文件{get_current_files(self.work_dir, 'data')}",
                }
            )

        # 添加 sub_task
        logger.info(f"添加子任务提示: {prompt}")
        await self.append_chat_history({"role": "user", "content": prompt})

        retry_count = 0
        last_error_message = ""
        consecutive_same_error_count = 0
        last_error_type = ""
        max_same_error = int(getattr(settings, "CODER_MAX_SAME_ERROR", 4))
        has_executed_code = False

        while True:
            if consecutive_same_error_count >= max_same_error:
                logger.error(f"连续相同错误达到上限: {max_same_error}")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=f"代码手求解失败：连续 {max_same_error} 次相同错误，"
                        f"错误类型：{last_error_type}，"
                        f"请检查任务或数据",
                        type="error",
                    ),
                )
                raise RuntimeError(
                    f"代码手求解失败：连续 {max_same_error} 次相同错误 "
                    f"（{last_error_type}），"
                    f"最后错误：{last_error_message}"
                )
            if retry_count >= self.max_retries:
                logger.error(f"超过最大重试次数: {self.max_retries}")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=f"代码手求解失败：超过最大重试次数({self.max_retries})",
                        type="error",
                    ),
                )
                raise RuntimeError(
                    f"代码手求解失败：达到最大重试次数 {self.max_retries}，"
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

                # 如果有工具调用
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
                            SystemMessage(
                                content=f"代码手调用{tool_call.name}工具"
                            ),
                        )

                        code = json.loads(tool_call.arguments)["code"]

                        # 提取 LLM 在工具调用前生成的代码介绍文本
                        code_description = response.content.strip() if response.content else None

                        await redis_manager.publish_message(
                            self.task_id,
                            InterpreterMessage(
                                input={"code": code},
                                description=code_description,
                            ),
                        )

                        # 更新对话历史 - 添加助手的响应
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

                        # 执行工具调用
                        logger.info("执行工具调用")
                        (
                            text_to_gpt,
                            error_occurred,
                            error_message,
                        ) = await self.code_interpreter.execute_code(code)

                        # 添加工具执行结果
                        if error_occurred:
                            # 即使发生错误也要添加tool响应
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
                            logger.info(f"当前重试次数: {retry_count} / {self.max_retries}")
                            last_error_message = error_message
                            error_type = error_message[:100]
                            if error_type == last_error_type:
                                consecutive_same_error_count += 1
                            else:
                                consecutive_same_error_count = 1
                                last_error_type = error_type
                            reflection_prompt = get_reflection_prompt(error_message, code)

                            await redis_manager.publish_message(
                                self.task_id,
                                SystemMessage(content="代码手反思纠正错误", type="info"),
                            )

                            await self.append_chat_history(
                                {"role": "user", "content": reflection_prompt}
                            )
                            continue
                        else:
                            # 成功执行的tool响应
                            await self.append_chat_history(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "name": "execute_code",
                                    "content": text_to_gpt,
                                }
                            )
                            retry_count = 0  # 成功后重置重试计数
                            has_executed_code = True
                            # 成功执行后继续循环，等待下一步指令或 task_complete
                            continue
                    else:
                        # 未知工具调用，添加占位响应后继续
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
                else:
                    # 没有工具调用 —— 必须先执行过代码才允许完成
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
                        await self.append_chat_history(
                            {"role": "assistant", "content": response.content or ""}
                        )
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

                    logger.info("没有工具调用，任务完成")
                    return CoderToWriter(
                        code_response=response.content,
                        created_images=await self.code_interpreter.get_created_images(
                            subtask_title
                        ),
                    )

            except asyncio.CancelledError:
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