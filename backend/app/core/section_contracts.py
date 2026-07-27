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
            "概括研究对象和建模目标的论文标题",
            "总体建模路线",
            "每一问的模型、求解方式、关键结果和验证",
            "带单位和合理有效数字的直接答案",
            "3-5个关键词",
        ],
        forbidden=[
            "不要写问题重述",
            "不要写模型假设",
            "不要写详细求解过程",
            "不要插入图片",
            "不要写参考文献",
            "不要编造正文没有证明的数值或结论",
            "不要只罗列算法名称",
        ],
    ),
    "toc": SectionContract(
        key="toc",
        title="目录",
        must_include=[
            "最终实际存在的一级标题",
            "覆盖全部问题的二级标题",
        ],
        forbidden=[
            "不要写正文段落",
            "不要写摘要",
            "不要写模型内容",
            "不要插入图片",
            "不要虚构页码",
            "不要列出正文不存在的章节",
        ],
    ),
    "RepeatQues": SectionContract(
        key="RepeatQues",
        title="问题重述",
        must_include=[
            "忠实压缩的题目背景",
            "题设数据、常量、边界和规则",
            "按问题一、问题二等拆解输入、目标和输出",
            "题目要求的文件、方案或评价指标",
        ],
        forbidden=[
            "不要大段复制原题",
            "不要写模型假设",
            "不要写求解代码",
            "不要写具体结果数值",
            "不要写模型评价",
            "不要插入图片",
            "不要虚构外部背景或文献",
        ],
    ),
    "analysisQues": SectionContract(
        key="analysisQues",
        title="问题分析",
        must_include=[
            "逐问说明任务类型和关键难点",
            "说明可用数据、变量、约束和目标",
            "说明模型选择理由和预期输出",
            "说明各问题之间的数据依赖",
            "说明逐问验证计划",
        ],
        forbidden=[
            "不要重复题目原文",
            "不要写完整模型公式推导",
            "不要写结果表格",
            "不要写模型评价",
            "不要插入图片",
            "不要只列算法名称",
        ],
    ),
    "modelAssumption": SectionContract(
        key="modelAssumption",
        title="模型假设",
        must_include=[
            "假设的具体对象和成立范围",
            "题设、量级或数据依据",
            "假设对模型的简化作用",
            "假设可能带来的偏差或适用边界",
        ],
        forbidden=[
            "不要写问题重述",
            "不要写数据预处理",
            "不要写代码结果",
            "不要插入图片",
            "不要写后文未使用的假设",
            "不要使用数据真实可靠或不考虑特殊情况等万能套话",
        ],
    ),
    "symbol": SectionContract(
        key="symbol",
        title="符号说明",
        must_include=[
            "符号表",
            "变量含义",
            "变量单位",
            "变量类型或取值域",
            "集合、下标和向量定义",
        ],
        forbidden=[
            "不要写模型求解过程",
            "不要写评价分析",
            "不要重复问题重述",
            "不要插入图片",
            "不要臆造正文未使用的符号",
        ],
    ),
    "judge": SectionContract(
        key="judge",
        title="模型评价、改进与推广",
        must_include=[
            "由精度、计算量、解释性或约束适应性证据支持的优点",
            "具体失效条件、偏差方向或数据限制",
            "与局限逐一对应的改进方向",
            "推广时需要重估的参数和最低数据条件",
        ],
        forbidden=[
            "不要重新写各问题的完整求解过程",
            "不要重复灵敏度分析章节",
            "不要重新插入所有结果图",
            "不要写参考文献",
            "不要使用精度高或适用范围广等无指标套话",
            "不要引入前文没有证据的新结果",
        ],
    ),
}
