"""主工作流关键回归测试。"""

import asyncio
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config.setting import Settings
from app.core.flows import Flows
from app.core.workflow import recover_unconfirmed_modeling_checkpoint
from app.routers import files_router, modeling_router
from app.routers.common_router import _parse_task_status
from app.schemas.A2A import ModelerToCoder
from app.schemas.enums import CompTemplate, FormatOutPut
from app.schemas.request import Problem


def test_hil_confirmation_is_enabled_by_default() -> None:
    """默认流程必须展示问题划分和建模方案确认。"""
    assert Settings.model_fields["HIL_ENABLED"].default is True


def test_empty_modeling_selection_resets_downstream_checkpoint() -> None:
    """旧任务的空建模选择不能继续跳过建模确认。"""
    checkpoint = {
        "coordinator": {"ques_count": 2},
        "question_selections": [{"questionIndex": 1}],
        "modeling_selections": {},
        "modeler": {"questions_solution": {}},
        "user_output_res": {"eda": {"response_content": "stale"}},
        "completed": True,
    }

    assert recover_unconfirmed_modeling_checkpoint(checkpoint) is True
    assert checkpoint == {
        "coordinator": {"ques_count": 2},
        "question_selections": [{"questionIndex": 1}],
    }


def test_recoverable_error_is_not_terminal() -> None:
    """Coder 回退过程中的 error 消息不能把历史任务标成失败。"""
    messages = [
        {
            "msg_type": "system",
            "type": "error",
            "content": "Coder 主力运行超时，准备切换备用",
        },
        {
            "msg_type": "system",
            "type": "success",
            "content": "代码手求解成功",
        },
    ]

    assert _parse_task_status(messages) == "interrupted"
    messages.append(
        {
            "msg_type": "system",
            "type": "error",
            "content": "任务执行失败: 所有 Coder 尝试均失败",
        }
    )
    assert _parse_task_status(messages) == "failed"


def test_eda_prompt_contains_no_fixed_crop_dataset() -> None:
    """通用 EDA 提示不能携带固定农业赛题字段。"""
    flows = Flows({"ques_count": 1, "ques1": "分析桥梁监测数据"})
    result = flows.get_solution_flows(
        flows.questions,
        ModelerToCoder(
            questions_solution={
                "eda": "检查监测数据",
                "ques1": "建立损伤识别模型",
            }
        ),
    )
    prompt = result["eda"]["coder_prompt"]

    assert "作物类型" not in prompt
    assert "作物编号" not in prompt
    assert "附件1.xlsx" not in prompt
    assert "先枚举当前目录中的数据文件" in prompt


def test_start_task_registers_runner_before_return() -> None:
    """启动接口返回时任务必须已经进入活动表。"""

    async def scenario() -> None:
        release = asyncio.Event()

        async def fake_runner(*_args, **_kwargs) -> None:
            await release.wait()

        problem = Problem(
            task_id="task-1",
            ques_all="test",
            comp_template=CompTemplate.CHINA,
            format_output=FormatOutPut.Markdown,
        )
        modeling_router._active_tasks.clear()
        with (
            patch.object(
                modeling_router,
                "_load_task_problem",
                return_value=problem,
            ),
            patch.object(
                modeling_router,
                "get_task_state",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                modeling_router,
                "mark_task_running",
                new=AsyncMock(return_value={}),
            ),
            patch.object(
                modeling_router.redis_manager,
                "set",
                new=AsyncMock(),
            ),
            patch.object(
                modeling_router,
                "run_modeling_task_async",
                side_effect=fake_runner,
            ),
        ):
            response = await modeling_router.start_task("task-1")
            active = modeling_router._active_tasks["task-1"]
            assert response["status"] == "processing"
            assert active["task"] is not None
            assert not active["task"].done()
            release.set()
            await active["task"]

        modeling_router._active_tasks.clear()

    asyncio.run(scenario())


def test_download_all_builds_real_archive(tmp_path: Path) -> None:
    """导出全部文件应生成可打开的 zip，并跳过符号链接。"""

    async def scenario() -> None:
        (tmp_path / "res.md").write_text("# paper", encoding="utf-8")
        section = tmp_path / "5.1_question"
        section.mkdir()
        (section / "code.py").write_text("print('ok')", encoding="utf-8")

        with patch.object(files_router, "get_work_dir", return_value=str(tmp_path)):
            result = await files_router.get_download_all_url("task-1")

        archive_path = tmp_path / "all.zip"
        assert archive_path.exists()
        assert result["download_url"].endswith("/static/task-1/all.zip")
        with zipfile.ZipFile(archive_path) as archive:
            assert set(archive.namelist()) == {
                "res.md",
                "5.1_question/code.py",
            }

    asyncio.run(scenario())
