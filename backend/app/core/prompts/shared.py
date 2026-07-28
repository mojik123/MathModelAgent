"""共享的提示词工具函数。"""


def get_reflection_prompt(
    error_message: str,
    code: str,
    recovery_advice: str = "",
) -> str:
    """生成代码错误反思提示词。

    Args:
        error_message: 错误信息。
        code: 出错的代码。
        recovery_advice: 系统根据错误族生成的定向修复建议。

    Returns:
        反思提示词字符串。
    """
    advice_block = (
        f"\nSystem-diagnosed recovery path (must follow):\n{recovery_advice}\n"
        if recovery_advice
        else ""
    )
    return f"""The code execution encountered an error:
{error_message}
{advice_block}

Please analyze the error, identify the cause, and execute a corrected version of the code.
Consider:
1. Syntax errors
2. Missing imports
3. Incorrect variable names or types
4. File path issues
5. Any other potential issues
6. Do not execute the unchanged failing code again. Validate the failed assumption
   with one small inspection, then apply one concrete fix.
7. If a task repeatedly fails, change the approach or simplify the model.
8. Do not ask the user what to do next; use the available files and traceback.

Previous code:
{code}

Briefly explain the root cause, then call the appropriate tool to execute the fix.
"""


def get_completion_check_prompt(prompt, text_to_gpt) -> str:
    """生成任务完成检查提示词。

    Args:
        prompt: 原始任务描述。
        text_to_gpt: 最新执行结果。

    Returns:
        完成检查提示词字符串。
    """
    return f"""
Please analyze the current state and determine if the task is fully completed:

Original task: {prompt}

Latest execution results:
{text_to_gpt}  # 修改：使用合并后的结果

Consider:
1. Have all required data processing steps been completed?
2. Have all necessary files been saved?
3. Are there any remaining steps needed?
4. Is the output satisfactory and complete?
5. 如果一个任务反复无法完成，尝试切换路径、简化路径或直接跳过，千万别陷入反复重试，导致死循环。
6. 尽量在较少的对话轮次内完成任务
7. If the task is complete, please provide a short summary of what was accomplished and don't call function tool.
8. If the task is not complete, please rethink how to do and call function tool
9. Don't ask user any thing about how to do and next to do,just do it by yourself
10. have a good visualization?
"""
