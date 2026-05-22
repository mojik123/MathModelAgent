"""建模手 Agent 模块，负责分析问题并制定建模方案。"""

import asyncio
from app.core.agents.agent import Agent
from app.core.llm.llm import LLM
from app.core.prompts import MODELER_PROMPT
from app.schemas.A2A import CoordinatorToModeler, ModelerToCoder
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
    ) -> None:
        super().__init__(task_id, model, context_window, cancel_event=cancel_event)
        self.system_prompt = MODELER_PROMPT

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
            SystemMessage(content="建模手正在分析问题、选择模型和制定方案..."),
        )
        while True:
            response = await self._chat(
                stream=True,
                history=self.chat_history,
                agent_name=self.__class__.__name__,
            )

            json_str = response.content or ""
            questions_solution = repair_json(json_str)
            if questions_solution:
                ic(questions_solution)
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content="建模手分析完成，方案已生成"),
                )
                return ModelerToCoder(questions_solution=questions_solution)

            # JSON 解析失败，不设上限——直到输出合法方案为止（靠 cancel_event 停止）
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
                    "content": "你返回的JSON格式有误，请严格按照JSON格式重新输出，注意字符串值内的双引号必须转义为\\\"，不要包含未转义的特殊字符。",
                }
            )
