"""建模手 Agent 模块，负责分析问题并制定建模方案。"""

import asyncio
from app.core.agents.agent import Agent
from app.core.llm.llm import LLM
from app.core.prompts import MODELER_PROMPT
from app.core.functions import modeler_tools
from app.schemas.A2A import CoordinatorToModeler, ModelerToCoder
from app.tools.openalex_scholar import OpenAlexScholar
from app.utils.log_util import logger
from app.services.redis_manager import redis_manager
from app.schemas.response import SystemMessage
import json
import re
from icecream import ic  # type: ignore[import-unresolved]


def repair_json(json_str: str) -> dict | None:
    """尝试修复 LLM 输出的格式错误的 JSON。

    Args:
        json_str: 可能包含格式错误的 JSON 字符串。

    Returns:
        修复后的字典，无法修复时返回 None。
    """
    json_str = json_str.replace("```json", "").replace("```", "").strip()

    # Try direct parse first
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # Fix unescaped newlines and quotes inside string values
    try:
        fixed = re.sub(
            r'(?<=: ")(.*?)(?=",\s*\n\s*"|"\s*\n\s*})',
            lambda m: m.group(0).replace('"', '\\"'),
            json_str,
            flags=re.DOTALL,
        )
        return json.loads(fixed)
    except (json.JSONDecodeError, re.error):
        pass

    # Extract key-value pairs with regex as last resort
    try:
        pattern = r'"(\w+)"\s*:\s*"((?:[^"\\]|\\.|"(?!,\s*\n)|"(?!\s*\n\s*}))*)"'
        matches = re.findall(pattern, json_str, re.DOTALL)
        if matches:
            return {k: v.replace('\\"', '"') for k, v in matches}
    except re.error:
        pass

    return None


class ModelerAgent(Agent):
    """建模手 Agent，分析问题类型并制定建模方案、求解方法和可视化策略。"""
    def __init__(
        self,
        task_id: str,
        model: LLM,
        context_window: int = 128000,
        cancel_event: asyncio.Event | None = None,
        scholar: OpenAlexScholar | None = None,
    ) -> None:
        super().__init__(task_id, model, context_window, cancel_event=cancel_event)
        self.system_prompt = MODELER_PROMPT
        self.scholar = scholar

    async def _handle_tool_calls(self, response) -> None:
        """处理建模手的工具调用（search_papers）。

        搜索文献后将结果注入对话历史，让建模手在后续输出中引用。
        """
        if not response.tool_calls:
            return

        assistant_msg: dict = {"role": "assistant", "content": response.content or ""}
        if response.reasoning_content:
            assistant_msg["reasoning_content"] = response.reasoning_content
        assistant_msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in response.tool_calls
            if tc.name == "search_papers"
        ]
        if assistant_msg["tool_calls"]:
            await self.append_chat_history(assistant_msg)

        for tool_call in response.tool_calls:
            if tool_call.name != "search_papers":
                logger.warning(f"建模手忽略未知工具调用: {tool_call.name}")
                continue

            logger.info("建模手调用工具: search_papers")
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="建模手正在系统性检索学术文献（深度调研模式）..."),
            )

            try:
                query = json.loads(tool_call.arguments)["query"]
            except Exception:
                query = str(tool_call.arguments or "").strip() or "mathematical modeling"

            try:
                assert self.scholar is not None, "scholar 未初始化"
                papers = await self.scholar.search_papers(query)
                papers_str = self.scholar.papers_to_str(papers)
                logger.info(f"建模手文献搜索结果\n{papers_str}")
            except Exception as e:
                error_msg = f"文献搜索失败: {str(e)}"
                logger.warning(error_msg)
                papers_str = f"文献搜索失败: {str(e)}。请继续制定建模方案，可基于领域知识引用经典文献。"

            await self.append_chat_history(
                {
                    "role": "tool",
                    "content": papers_str,
                    "tool_call_id": tool_call.id,
                    "name": "search_papers",
                }
            )

    async def run(
        self,
        coordinator_to_modeler: CoordinatorToModeler,
        modeling_selections: list[dict] | dict | None = None,
    ) -> ModelerToCoder:  # type: ignore[reportIncompatibleMethodOverride]
        """根据协调者拆解的问题生成建模方案。

        Args:
            coordinator_to_modeler: 协调者传递的结构化问题信息。

        Returns:
            ModelerToCoder 对象，包含各问题的建模解决方案。
        """
        await self.append_chat_history(
            {"role": "system", "content": self.system_prompt}
        )
        user_prompt = json.dumps(coordinator_to_modeler.questions, ensure_ascii=False)
        if modeling_selections:
            user_prompt = (
                f"{user_prompt}\n\n"
                "【用户已确认的逐问建模方案】\n"
                f"{json.dumps(modeling_selections, ensure_ascii=False, indent=2)}\n\n"
                "请严格以用户确认的模型选择、自定义方案和讨论记录为最高优先级来制定正式建模方案。"
                "若某个选择与题目约束冲突，可以在该问方案中说明必要修正，但不要忽略用户选择。"
            )
        await self.append_chat_history({"role": "user", "content": user_prompt})

        attempt = 0
        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="建模手正在进行深度调研：问题分析 → 文献检索 → 头脑风暴 → 方案制定..."),
        )

        # 第一轮：允许工具调用（搜索文献）
        tools = modeler_tools if self.scholar else None
        max_tool_rounds = 6  # 最多允许 6 轮工具调用，支持深度系统性文献调研

        while True:
            response = await self._chat(
                stream=True,
                history=self.chat_history,
                tools=tools,
                tool_choice="auto" if tools else None,
                agent_name=self.__class__.__name__,
            )

            # 处理工具调用（文献检索）
            if response.tool_calls and tools and max_tool_rounds > 0:
                max_tool_rounds -= 1
                await self._handle_tool_calls(response)
                # 工具调用后要求继续输出最终 JSON 方案
                if max_tool_rounds <= 0:
                    # 最后一轮后禁用工具，强制输出 JSON
                    tools = None
                    await self.append_chat_history(
                        {
                            "role": "user",
                            "content": (
                                "系统性文献调研已完成。请基于所有检索到的文献，进行头脑风暴和方案综合，"
                                "直接输出最终的 JSON 格式建模方案。\n"
                                "要求：\n"
                                "1. 每个问题的方案中必须引用检索到的相关文献\n"
                                "2. 基于文献说明模型选择的理论依据\n"
                                "3. 详细描述数学原理和公式，供下游写作手直接引用\n"
                                "4. 每个问题末尾汇总该问题的参考文献列表"
                            ),
                        }
                    )
                else:
                    await self.append_chat_history(
                        {
                            "role": "user",
                            "content": (
                                "文献检索结果已返回。请继续深度调研：\n"
                                "- 还有哪些问题没有搜索相关文献？请继续搜索\n"
                                "- 是否需要搜索方法的改进变体或前沿应用？\n"
                                "- 是否需要搜索方法组合的创新案例？\n"
                                "如果所有问题都已充分调研，可以直接输出最终 JSON 格式建模方案。"
                            ),
                        }
                    )
                continue

            # 尝试解析 JSON 方案
            json_str = response.content or ""
            questions_solution = repair_json(json_str)
            if questions_solution:
                ic(questions_solution)
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content="建模手深度调研完成，前沿建模方案已生成（含文献支撑）"),
                )
                return ModelerToCoder(questions_solution=questions_solution)

            # JSON 解析失败，禁用工具重试
            tools = None
            attempt += 1
            logger.warning(f"JSON 解析失败 (第{attempt}次)，请求模型重新生成")
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content=f"建模方案格式校验中，第{attempt}次修正..."),
            )
            retry_msg: dict = {"role": "assistant", "content": json_str}
            if response.reasoning_content:
                retry_msg["reasoning_content"] = response.reasoning_content
            await self.append_chat_history(retry_msg)
            await self.append_chat_history(
                {
                    "role": "user",
                    "content": "你返回的JSON格式有误，请严格按照JSON格式重新输出，注意字符串值内的双引号必须转义为\\\"，不要包含未转义的特殊字符。不要再调用任何工具。",
                }
            )
