"""工作流程定义模块，管理建模任务的求解和写作流程。"""

from app.models.user_output import UserOutput
from app.tools.base_interpreter import BaseCodeInterpreter
from app.core.agents.modeler_agent import ModelerToCoder
from app.core.section_contracts import SECTION_CONTRACTS


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
1. 读取每个 Excel sheet 后，必须先统一清洗列名和字符串字段：
   - df.columns = [str(c).strip() for c in df.columns]
   - 所有 object/string 列都要 astype(str).str.strip()，并把 "nan" 还原为空值。
2. 不得直接假定某个 DataFrame 一定包含“作物类型”。
   - 若当前经济参数表缺少“作物类型”，必须从“附件1.xlsx / 乡村种植的农作物”按“作物编号”合并补齐。
   - 合并前必须把“作物编号”转为数值型并删除非数据行。
   - 若按“作物编号”合并后仍有缺失，可再按“作物名称”映射补齐。
3. 对固定类别排序或绘图时，禁止使用 set_index(...).loc[固定列表] 直接强索引。
   - 必须使用 reindex(固定列表) 后再 dropna/reset_index，避免 KeyError。
4. 所有可能缺列的统计都必须先检查列是否存在：
   - if "作物类型" in df.columns: ...
   - 缺列时先补列或跳过该图，并输出明确说明。
5. EDA 阶段只做数据清洗、结构核验和轻量可视化，不做 MILP、动态规划、穷举搜索等复杂模型。
6. 保存清洗后的中间数据，输出必要的列名检查结果和缺失值统计，便于后续 Coder 复用。
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
            return tpl.replace("{问题}", model_build_solve).replace("{模型的建立与求解}", model_build_solve).replace("{题目}", bg_ques_all)

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
结合模型变量和求解摘要{model_build_solve}，按照模板撰写符号说明：{fill_template('symbol')}

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
                f"问题背景{bg_ques_all}，结合各问题模型求解摘要{model_build_solve}，按照模板撰写问题分析：{fill_template('analysisQues')}",
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
        questions_quesx_keys = self.get_questions_quesx_keys()
        bgc = str(self.questions.get("background") or "")

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

        quesx_writer_prompt = {
            key: f"""
                    问题背景{bgc},不需要编写代码,代码手得到的结果{coder_response},{code_output},按照如下模板撰写：{config_template[key]}{_SUBQUES_SCOPE_CONSTRAINT}
                """
            for key in questions_quesx_keys
        }

        writer_prompt = {
            "eda": f"""
                    问题背景{bgc},不需要编写代码,代码手得到的结果{coder_response},{code_output},按照如下模板撰写：{config_template["eda"]}
                """,
            **quesx_writer_prompt,
            "sensitivity_analysis": f"""
                    问题背景{bgc},不需要编写代码,代码手得到的结果{coder_response},{code_output},按照如下模板撰写：{config_template["sensitivity_analysis"]}
                """,
        }

        if key in writer_prompt:
            return writer_prompt[key]
        raise ValueError(f"未知的任务类型: {key}")

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
