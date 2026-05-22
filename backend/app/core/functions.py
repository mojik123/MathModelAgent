"""工具函数定义模块，为各 Agent 提供可用的工具 schema。"""

# ---- OpenAI 格式（Chat Completions + Responses 共用） ----

coder_tools = [
    {
        "type": "function",
        "function": {
            "name": "execute_code",
            "description": "This function allows you to execute Python code and retrieve the terminal output. If the code "
            "generates image output, the function will return the text '[image]'. The code is sent to a "
            "Jupyter kernel for execution. The kernel will remain active after execution, retaining all "
            "variables in memory."
            "You cannot show rich outputs like plots or images, but you can store them in the working directory and point the user to them. ",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "The code text"}
                },
                "required": ["code"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": "Call this tool when the coding subtask is fully complete — all required code has been executed successfully, all plots/images have been generated, and no further code changes are needed.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Brief summary of what was accomplished"}
                },
                "required": ["summary"],
                "additionalProperties": False,
            },
        },
    },
]

writer_tools = [
    {
        "type": "function",
        "function": {
            "name": "search_papers",
            "description": "Search for papers using a query string.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The query string"}
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]

# ---- Anthropic 格式 ----

coder_tools_anthropic = [
    {
        "name": "execute_code",
        "description": "This function allows you to execute Python code and retrieve the terminal output. If the code "
        "generates image output, the function will return the text '[image]'. The code is sent to a "
        "Jupyter kernel for execution. The kernel will remain active after execution, retaining all "
        "variables in memory."
        "You cannot show rich outputs like plots or images, but you can store them in the working directory and point the user to them. ",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "The code text"}
            },
            "required": ["code"],
        },
    },
    {
        "name": "task_complete",
        "description": "Call this tool when the coding subtask is fully complete — all required code has been executed successfully, all plots/images have been generated, and no further code changes are needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Brief summary of what was accomplished"}
            },
            "required": ["summary"],
        },
    },
]

writer_tools_anthropic = [
    {
        "name": "search_papers",
        "description": "Search for papers using a query string.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The query string"}
            },
            "required": ["query"],
        },
    },
]
