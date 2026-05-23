from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SectionContract:
    key: str
    title: str
    must_include: list[str]
    forbidden: list[str]
    image_policy: str = "不主动插入图片，除非 prompt 显式提供 available_images"
    output_rule: str = "只输出本章节 Markdown，不输出其他章节"


SECTION_CONTRACTS: dict[str, SectionContract] = {
    "firstPage": SectionContract(
        key="firstPage",
        title="标题、摘要、关键词",
        must_include=[
            "论文标题",
            "300字左右摘要",
            "3-5个关键词",
            "摘要中简要概括模型、算法和主要结果",
        ],
        forbidden=[
            "不要写问题重述",
            "不要写模型假设",
            "不要写详细求解过程",
            "不要插入图片",
            "不要写参考文献",
        ],
    ),
    "toc": SectionContract(
        key="toc",
        title="目录",
        must_include=[
            "一级标题",
            "二级标题",
            "页码占位符",
        ],
        forbidden=[
            "不要写正文段落",
            "不要写摘要",
            "不要写模型内容",
            "不要插入图片",
        ],
    ),
    "RepeatQues": SectionContract(
        key="RepeatQues",
        title="问题重述",
        must_include=[
            "题目背景简述",
            "按问题1、问题2、问题3拆解任务",
            "说明每问要求输出什么",
        ],
        forbidden=[
            "不要写模型假设",
            "不要写求解代码",
            "不要写具体结果数值",
            "不要写模型评价",
            "不要插入图片",
        ],
    ),
    "analysisQues": SectionContract(
        key="analysisQues",
        title="问题分析",
        must_include=[
            "分析每个问题的建模类型",
            "说明数据、变量、约束和目标",
            "说明各问题之间的逻辑关系",
        ],
        forbidden=[
            "不要重复题目原文",
            "不要写完整模型公式推导",
            "不要写结果表格",
            "不要写模型评价",
            "不要插入图片",
        ],
    ),
    "modelAssumption": SectionContract(
        key="modelAssumption",
        title="模型假设",
        must_include=[
            "列出必要假设",
            "说明假设合理性",
            "假设应服务于后续模型",
        ],
        forbidden=[
            "不要写问题重述",
            "不要写数据预处理",
            "不要写代码结果",
            "不要插入图片",
        ],
    ),
    "symbol": SectionContract(
        key="symbol",
        title="符号说明",
        must_include=[
            "符号表",
            "变量含义",
            "单位或取值说明",
        ],
        forbidden=[
            "不要写模型求解过程",
            "不要写评价分析",
            "不要重复问题重述",
            "不要插入图片",
        ],
    ),
    "judge": SectionContract(
        key="judge",
        title="模型评价、改进与推广",
        must_include=[
            "模型优点",
            "模型不足",
            "改进方向",
            "推广应用场景",
        ],
        forbidden=[
            "不要重新写各问题的完整求解过程",
            "不要重复灵敏度分析章节",
            "不要重新插入所有结果图",
            "不要写参考文献",
        ],
    ),
}
