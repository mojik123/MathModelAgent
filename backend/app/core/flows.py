"""工作流程定义模块，管理建模任务的求解和写作流程。"""

from app.models.user_output import UserOutput
from app.tools.base_interpreter import BaseCodeInterpreter
from app.core.agents.modeler_agent import ModelerToCoder
from app.core.section_contracts import SECTION_CONTRACTS
from app.utils.paper_evidence_validator import build_writer_evidence_context


class Flows:
    """管理数学建模任务的求解流程和写作流程。"""

    def __init__(self, questions: dict[str, str | int]):
        self.flows: dict[str, dict] = {}
        self.questions: dict[str, str | int] = questions

    def set_flows(self, ques_count: int):
        ques_str = [f"ques{i}" for i in range(1, ques_count + 1)]
        seq = [
            "firstPage",
            "toc",
            "RepeatQues",
            "analysisQues",
            "modelAssumption",
            "symbol",
            "eda",
            *ques_str,
            "sensitivity_analysis",
            "judge",
        ]
        self.flows = {key: {} for key in seq}

    def get_solution_flows(
        self, questions: dict[str, str | int], modeler_response: ModelerToCoder
    ):
        questions_quesx = {
            key: value
            for key, value in questions.items()
            if key.startswith("ques") and key != "ques_count"
        }
        solutions = modeler_response.questions_solution
        # 保存建模方案供后续 Writer 使用
        self._modeler_solutions = solutions
        ques_flow = {
            key: {
                "coder_prompt": f"""
                        参考建模手给出的解决方案{solutions.get(key, "")}
                        完成如下问题{value}
                    """,
            }
            for key, value in questions_quesx.items()
        }

        eda_data_safety_prompt = """
【EDA 数据读取与防错规则 — 必须严格执行】
1. 先枚举当前目录中的数据文件、Excel sheet、列名、数据类型和数据规模，再决定读取与合并方式，不得猜测文件名或字段名。
2. 读取表格后统一清洗列名和字符串字段；保留原始文件，清洗结果另存为可复用的中间文件。
3. 多表合并前必须从实际列名中寻找公共键，并检查键的类型、重复值、匹配率和合并后的缺失值。
4. 所有统计、排序和绘图都必须先确认字段存在；缺少必要字段时跳过对应分析并明确说明，不能自行虚构字段。
5. 类别重排使用 reindex 后再清理缺失项，避免固定列表强索引引发 KeyError。
6. EDA 只做数据清洗、结构核验和轻量可视化，不执行复杂优化模型。
7. 输出列名检查、缺失值、重复值和异常值摘要，供后续 Coder 复用。
"""

        flows = {
            "eda": {
                "coder_prompt": f"""
                        参考建模手给出的解决方案{solutions.get("eda", "对数据进行探索性分析")}
                        对当前目录下数据进行EDA分析(数据清洗,可视化),清洗后的数据保存当前目录下,**不需要复杂的模型**
                        {eda_data_safety_prompt}
                    """,
            },
            **ques_flow,
            "sensitivity_analysis": {
                "coder_prompt": f"""
                        参考建模手给出的解决方案{solutions.get("sensitivity_analysis", "对模型进行灵敏度分析")}
                        完成敏感性分析
                    """,
            },
        }
        return flows

    def get_write_flows(
        self, user_output: UserOutput, config_template: dict, bg_ques_all: str
    ):
        """生成写作阶段的流程配置。"""
        model_build_solve = user_output.get_model_build_solve()

        def fill_template(key: str) -> str:
            tpl = config_template.get(key, "")
            return (
                tpl.replace("{问题}", model_build_solve)
                .replace("{模型的建立与求解}", model_build_solve)
                .replace("{题目}", bg_ques_all)
            )

        def contract_prompt(key: str, base_prompt: str) -> str:
            contract = SECTION_CONTRACTS.get(key)
            if not contract:
                return base_prompt

            must = "\n".join(f"- {item}" for item in contract.must_include)
            forbidden = "\n".join(f"- {item}" for item in contract.forbidden)

            return f"""
【章节写作合同】
当前章节：{contract.title}
章节标识：{key}

必须包含：
{must}

禁止写入：
{forbidden}

图片规则：
{contract.image_policy}

输出规则：
{contract.output_rule}

【原始写作任务】
{base_prompt}

【强制要求】
你只能写"{contract.title}"这一节。
不要输出其他章节标题。
不要复述其他章节内容。
不要写"以下是"等解释性文字。
"""

        symbol_specific_prompt = f"""
结合模型变量和求解摘要{model_build_solve}，按照模板撰写符号说明：{fill_template("symbol")}

【符号说明强制要求】
1. 只生成最重要的 10 个符号，不能超过 10 行。
2. 优先选择贯穿多个模型或决定约束/目标函数的核心符号；临时变量、中间绘图变量、程序变量和只出现一次的辅助量不要写入符号表。
3. 符号表标题使用普通文字“表X 符号说明”，不要加粗，不要使用 **表X**。
4. 表格标题在预览和导出中应居中显示，字体与正文一致，不额外加粗。
5. 表格列建议为“符号、含义、单位/取值说明”。
"""

        flows = {
            "firstPage": contract_prompt(
                "firstPage",
                f"问题背景{bg_ques_all}，根据模型求解摘要{model_build_solve}，按照模板撰写：{fill_template('firstPage')}",
            ),
            "toc": contract_prompt(
                "toc",
                f"根据论文标题和章节结构，按照模板撰写目录：{fill_template('toc')}",
            ),
            "RepeatQues": contract_prompt(
                "RepeatQues",
                f"问题背景{bg_ques_all}，按照模板撰写问题重述：{fill_template('RepeatQues')}",
            ),
            "analysisQues": contract_prompt(
                "analysisQues",
                self._build_analysis_ques_prompt(
                    bg_ques_all, model_build_solve, fill_template("analysisQues")
                ),
            ),
            "modelAssumption": contract_prompt(
                "modelAssumption",
                f"结合建模方案和求解摘要{model_build_solve}，按照模板撰写模型假设：{fill_template('modelAssumption')}",
            ),
            "symbol": contract_prompt("symbol", symbol_specific_prompt),
            "judge": contract_prompt(
                "judge",
                f"结合模型求解摘要{model_build_solve}，按照模板撰写模型评价、改进与推广：{fill_template('judge')}",
            ),
        }
        return flows

    def get_writer_prompt(
        self,
        key: str,
        coder_response: str,
        code_interpreter: BaseCodeInterpreter,
        config_template: dict,
    ) -> str:
        code_output = code_interpreter.get_code_output(key)
        evidence_context = build_writer_evidence_context(
            code_interpreter.work_dir,
            key,
        )
        questions_quesx_keys = self.get_questions_quesx_keys()
        bgc = str(self.questions.get("background") or "")

        # 获取建模手的方案（在 get_solution_flows 时已保存）
        modeler_solutions = getattr(self, "_modeler_solutions", {})

        _SUBQUES_SCOPE_CONSTRAINT = """

【并行写作作用域约束 — 必须严格遵守】
你是并行写作架构中负责本子问题的专职写作手。论文的以下章节已由其他专职写作手独立完成，
你**绝对不能**在本节中重复撰写这些内容：
- 标题、摘要、关键词（firstPage）
- 目录（toc）
- 一、问题重述（RepeatQues）
- 二、问题分析（analysisQues）
- 三、模型假设（modelAssumption）
- 四、符号说明（symbol）
- 数据预处理 EDA（eda）
- 六、灵敏度分析（sensitivity_analysis）
- 七、模型评价（judge）
- 参考文献（独立统一整理）

你只需严格按照上方模板，直接从分配的标题开始写本子问题的"模型的建立与求解"内容。
不要在节首写问题重述、不要写本节以外的模型假设、不要写本节以外的问题分析。
"""

        _WRITING_DEPTH_INSTRUCTION = """

【写作深度与篇幅要求 — 必须严格遵守】

## 一、证据优先的篇幅控制
- 不设置机械最低字数，以完整说明"目标→变量→模型→求解→结果→验证→结论"为结束条件。
- 复杂问题可以充分展开，简单问题保持简洁；不得通过重复题意、算法背景或中间日志凑字数。
- 内容过长时按以下顺序精简：冗余背景描述 > 重复解释 > 次要中间过程 > 与结论无关的图表。

**内容优化建议**：
- ✅ 保留：模型核心思想、关键公式推导逻辑、求解方法的主要步骤、关键数值结果、结论分析
- ❌ 删除：问题重述（那是分析章节的任务）、教科书级别的背景知识、所有中间计算细节、重复解释

- EDA 只保留会影响模型选择的数据审计和发现；灵敏度分析只扰动会影响最终结论的关键参数。
- 自动精简时保留模型关系、关键参数、真实结果、验证证据和本问直接答案。

## 二、图片全覆盖强制规则
- **代码手产出的每一张图片都必须插入到论文中，0 遗漏。**
- 图片插入位置：放在最相关的段落之后，图片标签独占一行。
- **每张图片配套简洁但实质的解读段落（2-3 行）**，内容包括：
  a) 图中关键信息（不用重复图题，描述要点）
  b) 关键趋势或数值特征（分析）
  c) 对模型或决策的支撑意义（结论）
- 禁止"如图X所示"或"见图X"的一笔带过，但也不必冗长

## 三、建模逻辑完整性（精炼表达）
1. **清晰的建模逻辑链**：让读者理解"为什么选这个方法→方法怎么解决问题→结果说明什么"，不能只给结论不给推理
2. **与其他问题的逻辑衔接**：若建模手指出各问关系，在正文中体现但不重复论述
3. **充分利用代码结果**：数值结果、表格、优化指标都必须体现，不遗漏关键数据
4. **模型与结果对应**：每个模型的求解结果与建立部分对应，但无需列举每个计算步骤
5. **数据驱动结论**：所有结论有数据支撑，引用具体数值而非空泛描述
6. **建模手方案的充分利用**：建模思路、逻辑分析、文献引用在正文展开论述

**核心原则：高效传递信息，避免篇幅浪费。质量 > 字数。**
"""

        # 获取建模手的全局逻辑概述
        overall_logic = modeler_solutions.get("overall_logic", "")
        overall_logic_section = ""
        if overall_logic:
            overall_logic_section = (
                f"\n\n【整体建模逻辑（各问之间的关系）】\n{overall_logic}\n"
                "上述是建模手对整道题的全局分析，说明了各小问之间的逻辑关系和数据依赖。"
                "请在撰写本问时注意与其他问题的逻辑衔接。\n"
            )

        quesx_writer_prompt = {}
        for qkey in questions_quesx_keys:
            q_solution = modeler_solutions.get(qkey, "")
            q_question = str(self.questions.get(qkey, ""))
            modeler_section = ""
            if q_solution:
                modeler_section = (
                    f"\n\n【建模手的调研成果与建模方案】\n{q_solution}\n"
                    "上述方案包含：\n"
                    "- 本问与其他问题的逻辑关系\n"
                    "- 建模思路的完整逻辑链（为什么选这个方法、方法如何解决问题）\n"
                    "- 关键公式及其用途\n"
                    "- 文献调研和参考文献列表\n"
                    "请在论文中体现建模思路的逻辑性，将文献引用转化为正式脚注格式。\n"
                )

            quesx_writer_prompt[qkey] = f"""
问题背景：{bgc}

原始问题：{q_question}
{overall_logic_section}{modeler_section}
不需要编写代码。代码手得到的结果如下：
{coder_response}

代码手的执行输出：
{code_output}
{evidence_context}

按照如下模板撰写：{config_template[qkey]}
{_SUBQUES_SCOPE_CONSTRAINT}
{_WRITING_DEPTH_INSTRUCTION}
"""

        modeler_eda_solution = modeler_solutions.get("eda", "")
        eda_modeler_section = ""
        if modeler_eda_solution:
            eda_modeler_section = (
                f"\n\n【建模手的 EDA 调研方案】\n{modeler_eda_solution}\n"
            )

        modeler_sa_solution = modeler_solutions.get("sensitivity_analysis", "")
        sa_modeler_section = ""
        if modeler_sa_solution:
            sa_modeler_section = (
                f"\n\n【建模手的灵敏度分析调研方案】\n{modeler_sa_solution}\n"
                "请在论文中体现分析方法的选择理由、数学原理，并引用建模手提供的相关文献。\n"
            )

        writer_prompt = {
            "eda": f"""
问题背景：{bgc}
{eda_modeler_section}
不需要编写代码。代码手得到的结果如下：
{coder_response}

代码手的执行输出：
{code_output}
{evidence_context}

按照如下模板撰写：{config_template["eda"]}
{_WRITING_DEPTH_INSTRUCTION}
""",
            **quesx_writer_prompt,
            "sensitivity_analysis": f"""
问题背景：{bgc}
{sa_modeler_section}
不需要编写代码。代码手得到的结果如下：
{coder_response}

代码手的执行输出：
{code_output}
{evidence_context}

按照如下模板撰写：{config_template["sensitivity_analysis"]}
{_WRITING_DEPTH_INSTRUCTION}
""",
        }

        if key in writer_prompt:
            return writer_prompt[key]
        raise ValueError(f"未知的任务类型: {key}")

    def _build_analysis_ques_prompt(
        self, bg_ques_all: str, model_build_solve: str, template: str
    ) -> str:
        """构建问题分析章节的写作 prompt，注入建模手的全局逻辑。"""
        modeler_solutions = getattr(self, "_modeler_solutions", {})
        overall_logic = modeler_solutions.get("overall_logic", "")
        logic_section = ""
        if overall_logic:
            logic_section = (
                f"\n\n【建模手的整体建模逻辑分析】\n{overall_logic}\n"
                "请在问题分析中体现各小问之间的逻辑关系（递进/并列/对比）和数据依赖，"
                "让读者清楚理解整道题的解题框架。\n"
            )
        return (
            f"问题背景{bg_ques_all}，结合各问题模型求解摘要{model_build_solve}，"
            f"按照模板撰写问题分析：{template}"
            f"{logic_section}"
        )

    def get_questions_quesx_keys(self) -> list[str]:
        return list(self.get_questions_quesx().keys())

    def get_questions_quesx(self) -> dict[str, str | int]:
        return {
            key: value
            for key, value in self.questions.items()
            if key.startswith("ques") and key != "ques_count"
        }

    def get_seq(self, ques_count: int) -> dict[str, str]:
        ques_str = [f"ques{i}" for i in range(1, ques_count + 1)]
        seq = [
            "firstPage",
            "toc",
            "RepeatQues",
            "analysisQues",
            "modelAssumption",
            "symbol",
            "eda",
            *ques_str,
            "sensitivity_analysis",
            "judge",
        ]
        return {key: "" for key in seq}
