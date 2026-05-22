"""写作手 Agent 模块，负责基于建模结果撰写学术论文。"""

import asyncio
import json
import os
import re
from app.core.agents.agent import Agent
from app.core.llm.llm import LLM
from app.core.prompts import get_writer_prompt
from app.schemas.enums import CompTemplate, FormatOutPut
from app.tools.openalex_scholar import OpenAlexScholar
from app.utils.log_util import logger
from app.services.redis_manager import redis_manager
from app.schemas.response import SystemMessage, WriterMessage
from app.core.functions import writer_tools
from app.schemas.A2A import WriterResponse
from app.utils.common_utils import get_work_dir
from app.utils.image_code_index import get_image_code_entry, normalize_image_name


# TODO: 并行 parallel
# TODO: 获取当前文件下的文件
# TODO: 引用cites tool


class WriterAgent(Agent):
    """写作手 Agent，基于建模和代码执行结果撰写竞赛论文。"""
    def __init__(
        self,
        task_id: str,
        model: LLM,
        comp_template: CompTemplate = CompTemplate.CHINA,
        format_output: FormatOutPut = FormatOutPut.Markdown,
        scholar: OpenAlexScholar | None = None,
        context_window: int = 128000,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        super().__init__(task_id, model, context_window, cancel_event=cancel_event)
        self.format_out_put = format_output
        self.comp_template = comp_template
        self.scholar = scholar
        self.is_first_run = True
        self.system_prompt = get_writer_prompt(format_output)
        self.available_images: list[str] = []

    @staticmethod
    def _describe_image(filename: str) -> str:
        """从文件名推演人类可读的图片描述。

        示例：
          '5.1_预测结果对比.png' -> '预测结果对比 (5.1)'
          '20260420-xxx/1_distribution.png' -> 'Distribution (1)'
        """
        name = os.path.splitext(os.path.basename(filename))[0]
        parts = re.split(r"[_\-\s]+|(?<=[a-z])(?=[A-Z])|(?<=\d)(?=[A-Za-z])|(?<=[A-Za-z])(?=\d)", name)
        label = " ".join(p.strip().capitalize() for p in parts if p.strip())
        return label or name

    def _image_description_for_prompt(self, filename: str) -> str:
        try:
            entry = get_image_code_entry(
                get_work_dir(self.task_id),
                normalize_image_name(filename),
            )
            if entry:
                for key in ("caption", "description", "alt_text"):
                    value = str(entry.get(key) or "").strip()
                    if value:
                        return value
        except Exception as e:
            logger.debug(f"读取图片说明失败 {filename}: {e}")
        return self._describe_image(filename)

    @staticmethod
    def _strip_markdown_wrapper(text: str) -> str:
        cleaned = (text or "").strip()
        fence_match = re.match(
            r"^```(?:markdown|md)?\s*\n([\s\S]*?)\n```$",
            cleaned,
            re.IGNORECASE,
        )
        if fence_match:
            cleaned = fence_match.group(1).strip()
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    @staticmethod
    def _looks_like_complete_paper(original: str, reviewed: str) -> bool:
        if len(reviewed.strip()) < max(1000, int(len(original.strip()) * 0.45)):
            return False
        required_markers = [
            "摘要",
            "关键词",
            "问题重述",
            "问题分析",
            "模型假设",
            "符号",
            "模型",
            "参考文献",
        ]
        return sum(marker in reviewed for marker in required_markers) >= 5

    async def review_full_paper(
        self,
        paper_markdown: str,
        section_order: list[str] | None = None,
    ) -> WriterResponse:
        """Run a final whole-paper review pass and return cleaned Markdown."""
        section_order_text = "\n".join(
            f"{idx + 1}. {title}"
            for idx, title in enumerate(section_order or [])
        )
        system_prompt = (
            "你是数学建模竞赛论文终稿审阅 Agent。你的任务是对完整 Markdown 论文做最后的结构检查、"
            "章节重排、重复内容去除和语言一致性修订。你必须保持论文中已有的实验结果、数值、公式、"
            "图片引用和参考文献事实，不得编造新的结果。"
        )
        prompt = f"""
请对下面完整论文 Markdown 做终稿整体检查，并输出整理后的完整 Markdown 论文。

必须完成：
1. 按标准数学建模论文顺序重排：标题、摘要、关键词、问题重述、问题分析、模型假设、符号说明和数据预处理、模型建立与求解、模型检验/灵敏度分析、模型评价/改进/推广、参考文献。
2. 删除重复出现的标题、摘要、关键词、问题重述、问题分析、模型假设、符号说明、模型评价和参考文献。
3. 如果某个章节里误混入了另一份完整论文或重复草稿，只保留信息更完整、和上下文更一致的一份内容，并放到正确章节。
4. 合并同义小节，修正明显错乱的章节编号，但不要改变已给出的模型结果、预测数值、评价指标和图表引用。
5. 参考文献只保留一次，统一放在全文末尾；Markdown 图片引用必须全部保留在最相关段落附近。

期望章节来源顺序如下，供你判断哪些内容来自哪个写作片段：
{section_order_text or "未提供"}

输出要求：
- 只输出最终完整 Markdown 论文正文。
- 不要输出解释、检查报告、代码块围栏或额外说明。
- 不要写“以下是整理后的论文”等引导语。

原始完整论文 Markdown：
```markdown
{paper_markdown}
```
"""
        response = await self._chat(
            stream=False,
            history=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            tools=None,
            tool_choice=None,
            agent_name=self.__class__.__name__,
            sub_title="final_review",
        )
        reviewed = self._strip_markdown_wrapper(response.content or "")
        if not self._looks_like_complete_paper(paper_markdown, reviewed):
            raise RuntimeError("WriterAgent final review returned incomplete paper")
        return WriterResponse(response_content=reviewed, footnotes=[])

    async def review_paper_section(
        self,
        section_key: str,
        section_label: str,
        section_markdown: str,
        section_order: list[str] | None = None,
    ) -> WriterResponse:
        """Clean one paper section during the final review pass."""
        section_order_text = "\n".join(
            f"{idx + 1}. {title}"
            for idx, title in enumerate(section_order or [])
        )
        system_prompt = (
            "你是数学建模竞赛论文终稿审阅 Agent。你正在逐节清理论文，目标是让各章节内容各归其位，"
            "删除重复草稿和误混入的其他章节。必须保留已有实验结果、数值、公式、图片引用和事实，"
            "不得编造新结果。"
        )
        prompt = f"""
请清理当前论文片段，使其只包含“{section_label}”这一章节应有的内容。

全文章节顺序：
{section_order_text or "未提供"}

当前片段标识：{section_key}
当前片段应写内容：{section_label}

处理规则：
1. 如果当前片段混入了标题、摘要、关键词、其他问题章节、模型评价或参考文献，而这些内容不属于“{section_label}”，请删除。
2. 如果当前片段误包含另一份完整论文草稿，请只抽取其中属于“{section_label}”的内容。
3. 如果当前片段内部有重复段落或重复小节，请合并保留更完整、更具体的一份。
4. 修正明显错乱的小节编号和标题层级，但不要改变模型结果、预测数值、指标、公式和图片引用。
5. 只输出清理后的本章节 Markdown，不要输出解释、检查报告或代码块围栏。

待清理片段：
```markdown
{section_markdown}
```
"""
        response = await self._chat(
            stream=False,
            history=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            tools=None,
            tool_choice=None,
            agent_name=self.__class__.__name__,
            sub_title=f"final_review:{section_key}",
        )
        reviewed = self._strip_markdown_wrapper(response.content or "")
        if not reviewed.strip():
            raise RuntimeError(f"WriterAgent final review returned empty {section_key}")
        return WriterResponse(response_content=reviewed, footnotes=[])

    async def extract_section_from_draft(
        self,
        section_key: str,
        section_label: str,
        full_draft: str,
        section_order: list[str] | None = None,
    ) -> WriterResponse:
        """从完整草稿中抽取指定章节的内容，用于修复章节串位问题。

        当某些章节内容被错误写入其他章节时，直接清理各自原片段无效。
        此方法以完整草稿为来源，逐个目标章节抽取并归位。

        Args:
            section_key: 章节标识（如 ques1、sensitivity_analysis）。
            section_label: 章节的中文名称（如 "问题1的模型建立与求解"）。
            full_draft: 所有章节拼接而成的完整草稿 Markdown。
            section_order: 章节顺序列表，用于辅助定位。

        Returns:
            包含该章节清理后内容的 WriterResponse。
        """
        section_order_text = "\n".join(
            f"{idx + 1}. {title}"
            for idx, title in enumerate(section_order or [])
        )
        system_prompt = (
            "你是数学建模竞赛论文终稿审阅 Agent。你的任务是从一篇可能存在章节串位的完整草稿中，"
            "准确抽取属于指定章节的所有内容，并整理成该章节应有的格式。"
            "只输出该章节本身的 Markdown，不输出其他章节内容、解释或代码块围栏。"
            "必须保留草稿中已有的数值结果、公式、图片引用，不得编造新内容。"
        )
        prompt = f"""
请从下面的完整论文草稿中，抽取属于"{section_label}"（章节标识：{section_key}）的所有内容。

全文期望章节顺序：
{section_order_text or "未提供"}

抽取规则：
1. 在草稿中定位所有实际上应属于"{section_label}"的段落、小节、公式、图表和分析，无论它们当前出现在哪个位置。
2. 如果草稿中该章节的内容被写在了其他章节（如灵敏度分析中混有问题1-4的建模求解内容），请将其全部抽取出来。
3. 排除不属于"{section_label}"的内容（其他章节的标题、摘要、其他问题的求解过程等）。
4. 保持抽取内容的内部顺序和逻辑，修正章节编号使其符合该章节的独立结构。
5. 如果草稿中确实不存在属于"{section_label}"的有效内容，输出该章节的标题行即可，不要编造内容。

输出要求：
- 只输出"{section_label}"这一章节的完整 Markdown 内容
- 不要输出解释、检查报告或代码块围栏
- 不要输出其他任何章节的内容

完整论文草稿：
```markdown
{full_draft}
```
"""
        response = await self._chat(
            stream=False,
            history=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            tools=None,
            tool_choice=None,
            agent_name=self.__class__.__name__,
            sub_title=f"extract_section:{section_key}",
        )
        extracted = self._strip_markdown_wrapper(response.content or "")
        if not extracted.strip():
            raise RuntimeError(
                f"WriterAgent extract_section_from_draft returned empty for {section_key}"
            )
        return WriterResponse(response_content=extracted, footnotes=[])

    async def run(  # type: ignore[reportIncompatibleMethodOverride]
        self,
        prompt: str,
        available_images: list[str] | None = None,
        sub_title: str | None = None,
    ) -> WriterResponse:
        """
        执行写作任务
        Args:
            prompt: 写作提示
            available_images: 可用的图片相对路径列表（如 20250420-173744-9f87792c/编号_分布.png）
            sub_title: 子任务标题
        """
        logger.info(f"subtitle是:{sub_title}")

        # 统一使用 OpenAI 格式，由 AnthropicProvider._convert_tools 负责转换
        tools = writer_tools

        if self.is_first_run:
            self.is_first_run = False
            await self.append_chat_history(
                {"role": "system", "content": self.system_prompt}
            )

        if available_images:
            self.available_images = available_images
            described_images = []
            for img in available_images:
                desc = self._image_description_for_prompt(img)
                described_images.append(f"- **{desc}** (`{img}`)")
            image_lines = "\n".join(described_images)
            image_prompt = (
                f"\n\n【必须插入的图片列表】\n"
                f"以下图片是代码手生成的，你必须在论文相关段落后用 Markdown 格式逐一插入。\n"
                f"每张图片附带了内容描述（粗体文字），请根据描述选择合适的章节插入，\n"
                f"并用该描述作为 Markdown 图片的 alt-text。\n"
                f"{image_lines}\n"
                f"插入格式为独占一行的 ![描述](文件名)，每张图片后需配3行以上的分析解读。\n"
            )
            logger.info(f"image_prompt是:{image_prompt}")
            prompt = prompt + image_prompt

        logger.info(f"{self.__class__.__name__}:开始:执行对话")

        await self.append_chat_history({"role": "user", "content": prompt})

        # 获取历史消息用于本次对话
        response = await self._chat(
            stream=True,
            history=self.chat_history,
            tools=tools,
            tool_choice="auto",
            agent_name=self.__class__.__name__,
            sub_title=sub_title,
        )

        footnotes = []
        response_content: str = response.content or ""
        final_response = response

        if response.tool_calls:
            logger.info("检测到工具调用")
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
                    logger.warning(f"写作手忽略未知工具调用: {tool_call.name}")
                    continue

                logger.info("调用工具: search_papers")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content=f"写作手调用{tool_call.name}工具"),
                )

                try:
                    query = json.loads(tool_call.arguments)["query"]
                except Exception:
                    query = str(tool_call.arguments or "").strip() or "mathematical modeling"

                await redis_manager.publish_message(
                    self.task_id,
                    WriterMessage(content=query),
                )

                try:
                    assert self.scholar is not None, "scholar 未初始化"
                    papers = await self.scholar.search_papers(query)
                    papers_str = self.scholar.papers_to_str(papers)
                    logger.info(f"搜索文献结果\n{papers_str}")
                except Exception as e:
                    error_msg = f"搜索文献失败: {str(e)}"
                    logger.warning(error_msg)
                    papers_str = f"文献搜索失败: {str(e)}。请继续完成写作任务，无需引用外部文献。"

                await self.append_chat_history(
                    {
                        "role": "tool",
                        "content": papers_str,
                        "tool_call_id": tool_call.id,
                        "name": "search_papers",
                    }
                )

            await self.append_chat_history(
                {
                    "role": "user",
                    "content": "文献检索结果已经返回。请不要再调用工具，直接输出本章节完整 Markdown 正文。",
                }
            )
            final_response = await self._chat(
                stream=True,
                history=self.chat_history,
                tools=None,
                tool_choice=None,
                agent_name=self.__class__.__name__,
                sub_title=sub_title,
            )
            response_content = final_response.content or ""

        if not response_content.strip():
            logger.warning(
                f"{self.__class__.__name__}: {sub_title or 'unknown'} 首次正文为空，禁用工具重试"
            )
            await self.append_chat_history(
                {
                    "role": "user",
                    "content": "上一轮没有输出正文。请不要调用任何工具，直接输出本章节完整 Markdown 内容。",
                }
            )
            final_response = await self._chat(
                stream=True,
                history=self.chat_history,
                tools=None,
                tool_choice=None,
                agent_name=self.__class__.__name__,
                sub_title=sub_title,
            )
            response_content = final_response.content or ""

        if not response_content.strip():
            raise RuntimeError(f"WriterAgent 未生成 {sub_title or '当前章节'} 的正文内容")

        self.chat_history.append(
            {"role": "assistant", "content": response_content, "reasoning_content": final_response.reasoning_content}
            if final_response.reasoning_content
            else {"role": "assistant", "content": response_content}
        )
        logger.info(f"{self.__class__.__name__}:完成:执行对话")
        return WriterResponse(response_content=response_content, footnotes=footnotes)

    async def summarize(self) -> str:
        """总结对话内容，生成任务执行摘要。"""
        try:
            await self.append_chat_history(
                {"role": "user", "content": "请简单总结以上完成什么任务取得什么结果:"}
            )
            # 获取历史消息用于本次对话
            response = await self._chat(
                stream=True,
                history=self.chat_history, agent_name=self.__class__.__name__
            )
            response_content = response.content or ""
            summary_msg: dict = {"role": "assistant", "content": response_content}
            if response.reasoning_content:
                summary_msg["reasoning_content"] = response.reasoning_content
            await self.append_chat_history(summary_msg)
            return response_content
        except Exception as e:
            logger.error(f"总结生成失败: {str(e)}")
            # 返回一个基础总结，避免完全失败
            return "由于网络原因无法生成详细总结，但已完成主要任务处理。"
