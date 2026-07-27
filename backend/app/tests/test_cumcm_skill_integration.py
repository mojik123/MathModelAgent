"""新版 CUMCM 论文 skill 的运行时接入测试。"""

from app.core.prompts.writer import get_writer_prompt
from app.core.section_contracts import SECTION_CONTRACTS
from app.schemas.enums import CompTemplate, FormatOutPut
from app.utils.common_utils import get_config_template


def test_writer_system_prompt_loads_distilled_skill_rules() -> None:
    """WriterAgent 的最终系统提示词应包含新版蒸馏规则。"""
    prompt = get_writer_prompt(FormatOutPut.Markdown)

    assert "# 新版 CUMCM 论文 skill（最高优先级）" in prompt
    assert "任务目标 → 输入证据 → 变量与假设" in prompt
    assert "不得猜测数值、样本量、参数" in prompt
    assert "按模型类型追加要求" in prompt
    assert "质量和证据优先，不为凑固定字数" in prompt


def test_runtime_section_templates_use_question_closure() -> None:
    """运行时分章节模板应使用逐问闭环且不再注入旧示例。"""
    template = get_config_template(CompTemplate.CHINA)
    required_keys = {
        "firstPage",
        "toc",
        "RepeatQues",
        "analysisQues",
        "modelAssumption",
        "symbol",
        "eda",
        "ques1",
        "ques2",
        "ques3",
        "ques4",
        "ques5",
        "ques6",
        "sensitivity_analysis",
        "judge",
    }

    assert required_keys.issubset(template)
    assert "模型—求解—关键结果—验证" in template["firstPage"]
    assert "模型选择理由" in template["analysisQues"]
    assert "本问结论" in template["ques1"]
    assert "验证、敏感性和不确定性不得混为一谈" in template["sensitivity_analysis"]

    combined = "\n".join(str(template[key]) for key in sorted(required_keys))
    assert "哈里斯鹰" not in combined
    assert "页码数字根据实际论文长度估算" not in combined
    assert "应在 1000-5000 字之间" not in combined


def test_section_contracts_match_distilled_skill() -> None:
    """框架章节合同应约束真实性、直接答案和题目特异假设。"""
    abstract_contract = SECTION_CONTRACTS["firstPage"]
    assumption_contract = SECTION_CONTRACTS["modelAssumption"]
    judge_contract = SECTION_CONTRACTS["judge"]

    assert "带单位和合理有效数字的直接答案" in abstract_contract.must_include
    assert "不要编造正文没有证明的数值或结论" in abstract_contract.forbidden
    assert "假设可能带来的偏差或适用边界" in assumption_contract.must_include
    assert any("万能套话" in item for item in assumption_contract.forbidden)
    assert any("证据" in item for item in judge_contract.must_include)
