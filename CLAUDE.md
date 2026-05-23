# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 自动推送规则

每次完成代码修改后，必须执行以下命令提交并推送到 GitHub：
```powershell
powershell -ExecutionPolicy Bypass -File .\push-to-github.ps1
```

## 项目概述

MathModelAgent 是数学建模竞赛自动化系统，通过多 Agent 协作完成建模、代码生成和论文撰写。核心工作流：CoordinatorAgent 分析问题 → ModelerAgent 建模 → CoderAgent 编码执行 → WriterAgent 撰写论文。

## Commands

### 后端

```bash
cd backend

# 安装依赖
uv sync

# 启动开发服务器（需要先启动 Redis）
ENV=DEV uvicorn app.main:app --host 0.0.0.0 --port 8000 --ws-ping-interval 60 --ws-ping-timeout 120 --reload

# Lint（使用虚拟环境中的 ruff）
.\.venv\Scripts\python.exe -m ruff check app/
.\.venv\Scripts\python.exe -m ruff format app/

# 类型检查
npx pyright app/

# 运行测试
.\.venv\Scripts\python.exe -m pytest app/tests/ -v

# 运行单个测试
.\.venv\Scripts\python.exe -m pytest app/tests/test_common_utils.py::TestCommonUtils::test_split_footnotes -v
```

### 前端

```bash
cd frontend

# 安装依赖
pnpm i

# 启动开发服务器
pnpm run dev

# 构建
pnpm run build

# Lint
npx biome check src/
npx biome check --write src/  # 自动修复
```

### Docker

```bash
docker-compose up -d      # 后台启动所有服务
docker-compose down        # 停止
```

`docker-compose.yml` 启动 3 个服务：

| 服务 | 端口 | 说明 |
|------|------|------|
| redis | 6379 | Redis 消息队列 |
| backend | 8000 | FastAPI 后端（含 WebSocket） |
| frontend | 5174 | Vite 开发服务器（--strictPort） |

## 架构设计

### Agent 体系

每个 Agent 继承 `core/agents/agent.py` 基类（对话历史管理、轮次控制、记忆压缩），并各自选用不同的 LLM 模型：

| Agent | 文件 | 职责 |
|-------|------|------|
| CoordinatorAgent | `coordinator_agent.py` | 分析问题、拆分子任务 |
| ModelerAgent | `modeler_agent.py` | 数学建模、方法选择 |
| CoderAgent | `coder_agent.py` | 代码生成与执行 |
| WriterAgent | `writer_agent.py` | 论文撰写 |

### LLM 调用层 (`core/llm/`)

LLM 调用基于 LiteLLM 封装，支持多 Provider 架构：

- `llm_factory.py` — LLMFactory 根据 `ApiType` 枚举（`openai-chat` / `openai-responses` / `anthropic`）创建对应的 Provider 实例
- `providers/` 下每个 Provider 实现统一的抽象基类（`base.py`），封装了对话、重试、fallback 逻辑
- 每个 Agent 可独立配置 API 类型、模型、Base URL、最大 Token 数（见 `config/setting.py` 中 `COORDINATOR_*`、`MODELER_*`、`CODER_*`、`WRITER_*` 前缀的环境变量）

### 工作流编排

- `core/workflow.py` — `MathModelWorkFlow` 是主工作流类，编排多 Agent 协作完成完整建模任务，包含 checkpoint 断点续传、cancel 取消机制
- `core/flows.py` — `Flows` 类定义任务的求解阶段序列（firstPage → toc → RepeatQues → analysisQues → modelAssumption → symbol → eda → ques{N} → sensitivity_analysis → judge），根据问题数量动态生成流程节点

### FastAPI 路由

| 文件 | 说明 |
|------|------|
| `routers/modeling_router.py` | 主任务管理（创建、取消、状态查询、结果下载） |
| `routers/ws_router.py` | WebSocket `/task/{task_id}` 实时推送 |
| `routers/files_router.py` | 文件上传/下载，支持 `.txt`/`.csv`/`.xlsx` |
| `routers/common_router.py` | 公共接口（检索诊断、临时文件管理） |

### WebSocket 实时推送

- 路由 `routers/ws_router.py` 提供 `/task/{task_id}` WebSocket 端点
- 后端订阅 Redis 频道 `task:{task_id}:messages`，通过 `ws_manager.send_personal_message_json` 将消息以 JSON 推向前端
- 消息结构体定义在 `schemas/response.py`（`AgentMessage`, `AgentType`, `SystemMessage`）
- 若 `task_id` 不存在于 Redis，连接以 code=1008 关闭

### Code Interpreter

`tools/interpreter_factory.py` — `create_interpreter()` 工厂函数根据配置创建代码解释器实例，支持三种后端：
- **Local Jupyter** — 基于 ipykernel + jupyter-client，代码保存为 `.ipynb`
- **E2B** — 云端沙箱解释器
- **Daytona** — 云端解释器（备用）

### Prompt 模板与 Inject

`core/prompts/` 下每个 Agent 有独立的 prompt 模板文件（`coordinator.py`, `modeler.py`, `coder.py`, `writer.py`），`shared.py` 存放共享模板，`image_revision.py` 和 `text_revision.py` 存放图片/文本修订模板。

`config/md_template.toml` 是用户可自定义的论文模板（Prompt Inject），定义每个求解阶段（firstPage、toc、analysisQues 等）的输出格式要求。用户可按需修改模板来控制论文风格，不需要改代码。

### Agent 工具函数 (`core/functions.py`)

定义各 Agent 可调用的工具 schema（含 OpenAI 和 Anthropic 两种格式）：

| Agent | 工具 | 说明 |
|-------|------|------|
| Coder | `execute_code` | 在 Jupyter kernel 中执行 Python 代码并返回输出，生成的图片返回 `[image]` 标记 |
| Coder | `task_complete` | Coder 完成所有代码执行和图表生成后调用，标记子任务结束 |
| Writer | `search_papers` | 通过 OpenAlex API 搜索学术论文用于参考文献 |

### 论文章节契约 (`core/section_contracts.py`)

`SectionContract` dataclass 定义每个论文章节的强制性规则：`must_include`（必须包含的内容）和 `forbidden`（禁止出现的内容）。Writer Agent 在生成各章节时遵循对应契约，确保论文结构合规。覆盖章节：firstPage、toc、RepeatQues、analysisQues、modelAssumption、symbol、judge。

### Agent 间通信 (A2A) (`schemas/A2A.py`)

Agent 之间通过 Pydantic 模型传递结构化数据：

| 数据流 | 模型 | 内容 |
|--------|------|------|
| Coordinator → Modeler | `CoordinatorToModeler` | 问题列表和数量 |
| Modeler → Coder | `ModelerToCoder` | 每问的建模方案 |
| Coder → Writer | `CoderToWriter` | 代码响应、执行输出、生成的图片列表 |
| Writer → 工作流 | `WriterResponse` | 论文内容和脚注 |

### 结果聚合 (`models/user_output.py`)

`UserOutput` 类聚合所有问题求解结果（代码、输出、图片、建模描述），供 Writer Agent 生成论文时使用。

### 核心功能特性

**HIL 人机协作**（`HIL_ENABLED`）：关键节点（问题拆分、模型选择、论文审查）暂停等待用户审批，支持 6 种决策动作：confirm / edit / regenerate / ask / skip / abort。

**四层容错**：有限重试 → Fallback Hand Off（主模型故障自动切换备用模型）→ Evaluator Shadow Mode（输出质量评估）→ Feedback Rerun（评估反馈注入重跑）。

**Coder 执行模式**：默认每问单 Coder（主力失败自动启动备用），竞速模式（多 Coder 同时抢跑）通过 `CODER_RACING_ENABLED` 手动开启。
- `CODER_RACING_ENABLED`（默认 `False`）— 是否开启竞速模式
- `CODER_FALLBACK_WORKERS`（默认 `1`）— 主力失败后备用 Coder 数量
- `ARTIFACT_CHECK_ENABLED`（默认 `True`）— 是否在 Coder 完成后检查产物（图片、代码、目录）

**RAG 知识库**（`RAG_ENABLED`）：基于 ChromaDB + sentence-transformers 嵌入 + BGE Reranker 重排序，从本地知识库检索建模方法、代码模板、论文写作参考。

**Web Search**（`SEARCH_ENABLED` + `TAVILY_API_KEY`）：Agent 通过 Tavily API 自主搜索互联网获取真实数据，搜索结果带缓存（默认 86400 秒 TTL）。

## 日志

后端使用 loguru 进行日志记录，初始化逻辑位于 `app/utils/log_util.py`。日志输出到控制台和 `logs/` 目录（按天轮转，自动压缩）。

## 配置系统

`config/setting.py` 使用 pydantic-settings，根据 `ENV` 环境变量加载 `.env.{env}` 配置文件（如 `ENV=DEV` → `.env.dev`）。从 `.env.example` 复制并重命名来创建配置，每个 Agent 有独立的 API 配置（类型、Key、模型、Base URL、Max Tokens、Context Window）。

可选功能通过环境变量开关控制，未配置外部依赖时自动降级跳过。主要开关：`SEARCH_ENABLED`、`RAG_ENABLED`、`HIL_ENABLED`、`CODER_RACING_ENABLED`、`ARTIFACT_CHECK_ENABLED`、`FALLBACK_*` 系列、`EVALUATOR_*` 系列。

其他配置文件：
- `config/model_config.toml` — 模型参数配置
- `config/cumcm_latex_rules.md` — CUMCM 竞赛 LaTeX 排版规范
- `config/nature_figure_rules.md` — Nature 风格图片规范
- `config/cumcm_pandoc_template.tex` — Pandoc LaTeX 模板
- `config/template.md` — 论文 Markdown 模板

## 用户交互流程

前端页面路由：`/login` (登录) → `/chat` (主页面：文件上传、题目输入、参数选择、提交任务) → `/task/{task_id}` (任务详情：实时进度、代码 Tab、论文 Tab、下载)。

支持上传的数据文件格式：`.txt`、`.csv`、`.xlsx`。

## 输出目录

每次建模任务的结果保存在 `backend/project/work_dir/{task_id}/` 下：
- `notebook.ipynb` — 运行过程中产生的代码
- `res.md` — 最终结果为 markdown 格式
- 生成的图片文件（`fig{N}_{描述}.png` 等）

## 工具与自动修复

- `utils/artifact_checker.py` — Coder 完成后检查产物（图片、代码、目录）是否齐全，触发自动修复
- `utils/final_output_validator.py` — 验证最终输出的完整性和格式合规性
- `utils/paper_validator.py` — 论文结构/内容验证
- `utils/data_recorder.py` — 记录任务执行过程中的数据，用于调试和审计
- `utils/image_describer.py` — 为生成的图片生成描述文本
- `utils/image_code_index.py` — 建立图片与代码块的交叉索引
- `tools/openalex_scholar.py` — OpenAlex 学术论文搜索（参考文献检索）

## 项目结构

`.cursor/rules/` 目录下有额外的架构说明文件（`structure.mdc`、`backend-rules.mdc`、`frontend-rules.mdc`、`ws-frontend-backend-interaction.mdc`），可作为补充参考。

```
backend/
  app/
    core/
      agents/          # Agent 实现（继承 Agent 基类）
        agent.py       # Agent 基类：对话历史、轮次控制、记忆压缩
        coordinator_agent.py  # 任务分解
        modeler_agent.py      # 数学建模
        coder_agent.py        # 代码生成与执行
        writer_agent.py       # 论文撰写
      llm/             # LLM 调用层
        llm_factory.py  # 工厂，根据 ApiType 创建 Provider
        providers/      # Anthropic / OpenAI Chat / OpenAI Responses 实现
      prompts/         # 各 Agent 的 prompt 模板
      flows.py         # 任务流程节点定义（求解阶段序列）
      workflow.py      # 工作流主入口（多 Agent 编排、checkpoint）
    routers/           # FastAPI 路由（REST + WebSocket）
    schemas/           # Pydantic 模型（请求/响应/枚举/A2A 消息协议）
    services/          # Redis 管理、WebSocket 管理、任务状态
    tools/             # 代码解释器（本地 Jupyter / E2B）、论文搜索工具
    utils/             # 工具函数（image_constants.py 为图片常量权威来源）
    config/            # 配置（pydantic-settings，多 Agent 独立配置）
    tests/             # 测试文件

frontend/
  src/
    apis/              # 后端 API 调用封装（按业务模块拆分）
    components/        # 通用组件 + shadcn-vue UI 库（components/ui/ 不要修改）
    pages/             # 页面组件（chat/、task/、login/）
    stores/            # Pinia 状态管理（apiKeys.ts、task.ts）
    router/            # vue-router 路由配置
    utils/             # 工具函数、类型定义、WebSocket 客户端、axios 封装、图片常量
```

## Code Style

### 后端（Python）

- 模块级、类级、公共方法均使用 Google 风格 docstring（Args/Returns/Raises）
- 类型注解：使用 `str | None` 而非 `Optional[str]`
- 异步：全程 async/await，FastAPI 路由均为 async def
- 注释：中文，解释 WHY 而非 WHAT
- Ruff 配置：行宽 88，缩进 4 空格，双引号，规则集 E4/E7/E9/F

```python
"""模块级 docstring：描述模块用途。"""

class ExampleAgent:
    """类级 docstring：简述职责。"""

    async def run(self, prompt: str, system_prompt: str) -> str:
        """执行任务并返回结果。

        Args:
            prompt: 用户输入。
            system_prompt: 系统提示词。

        Returns:
            处理结果文本。
        """
```

### 前端（Vue 3 + TypeScript）

- SFC 使用 `<script setup lang="ts">`
- 代码按逻辑分组，用注释分隔：`// ---- Props ----`、`// ---- State ----`、`// ---- Computed ----`、`// ---- Methods ----`
- TypeScript 接口和 API 函数使用 JSDoc `/** */` 注释
- UI 库组件（`components/ui/`）为 shadcn-vue 生成代码，不要修改
- 格式：tab 缩进，双引号，Biome 管理 lint 和格式化
- 路径别名 `@` 指向 `src/`

```vue
<script setup lang="ts">
import { ref, computed } from "vue";

// ---- Props ----

/** 组件属性 */
interface Props {
	/** 消息类型 */
	type: "agent" | "user";
	/** 消息内容 */
	content: string;
}
const props = withDefaults(defineProps<Props>(), { type: "user" });

// ---- Computed ----

const rendered = computed(() => marked.parse(props.content));
</script>
```

## 根目录辅助脚本

- `check-config.ps1` — 启动前检查 API Key 等配置是否完整
- `start-docker.ps1` — 一键启动 Docker 所有服务
- `push-to-github.ps1` — 提交并推送到 GitHub（每次修改后执行）
- `scripts/` — 环境修复和补丁脚本（Python + PowerShell）
- `skills/` — 自定义技能定义（`cumcm-latex`、`nature-figure`）
- `third_party/CUMCMThesis/` — CUMCM LaTeX 论文模板

## Git Workflow

提交信息格式：`<type>: <描述>`，type 包括：

- `feat`: 新功能
- `fix`: 修复
- `refactor`: 重构
- `chore`: 杂项变更
- `enhance`: 增强
- `docs`: 文档

示例：`feat: 添加 OpenAlex API Key 支持并更新相关配置`

## Boundaries

### 自动化 Lint Hook

每次 Edit/Write 文件后，PostToolUse hook 自动触发：
- `backend/**/*.py` → `ruff check app/`
- `frontend/src/**/*.{vue,ts}` → `biome check <file>`

hook 脚本位于 `.claude/hook_lint.sh`，配置位于 `.claude/settings.json`。

### 不要修改的内容

- `frontend/src/components/ui/` — shadcn-vue 第三方 UI 库组件
- 已有的 `# type: ignore` 注释 — 这些是经过验证的类型抑制，非遗留问题
- `.env` 相关文件中的实际配置值
- **图片扩展名常量** — `backend/app/utils/image_constants.py` 和 `frontend/src/utils/imageConstants.ts` 是全项目图片格式的唯一权威来源，不要在别处硬编码扩展名列表

### 运行环境

- Python 3.12+，包管理用 uv（非 pip）
- Node.js，包管理用 pnpm（`pnpm@10.6.3`）
- Redis 必须运行（任务队列和 WebSocket 广播）
- 后端虚拟环境路径：`backend/.venv/`

### 图片命名规范

**图片扩展名统一常量**（全项目唯一权威来源）：

| 位置 | 文件 |
|------|------|
| 后端 | `backend/app/utils/image_constants.py` |
| 前端 | `frontend/src/utils/imageConstants.ts` |

支持的图片格式：`.png` `.jpg` `.jpeg` `.gif` `.bmp` `.webp` `.svg`

**命名规范**：CoderAgent 生成的图片必须遵循 `fig{N}_{英文功能描述}.ext`（如 `fig1_data_distribution.png`），由 prompt 约定 + 运行时校验（解释器执行后自动检查并 warning 不合规命名）。

**关键函数**：
- `is_image_file(filename)` — 判断是否为支持的图片格式
- `validate_image_filename(filename)` — 校验命名是否合规，返回 `(bool, reason)`
- `normalize_image_filename(filename)` — 去除路径仅保留基本名
- `IMAGE_EXTENSION_RE_FRAGMENT` — 可嵌入其他正则的扩展名片段
- `SAVEFIG_RE` / `MARKDOWN_IMAGE_RE` — 预编译正则

新增或修改图片相关代码时，**必须引用上述常量模块**，禁止硬编码扩展名列表。
