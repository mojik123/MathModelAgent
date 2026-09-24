from app.routers.workflow_router import router
from app.services.codex_runner import CodexEventResult
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.config.setting import ApiType, settings


@pytest.fixture
def workflow_client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.routers.workflow_router.WORK_DIR_ROOT", tmp_path)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), tmp_path


def _configure_responses_model(monkeypatch, role="COORDINATOR", model="gpt-6-sol"):
    for name in ("COORDINATOR", "MODELER", "CODER", "WRITER"):
        monkeypatch.setattr(settings, f"{name}_API_TYPE", None)
        monkeypatch.setattr(settings, f"{name}_API_KEY", None)
        monkeypatch.setattr(settings, f"{name}_MODEL", None)
    monkeypatch.setattr(settings, f"{role}_API_TYPE", ApiType.OPENAI_RESPONSES)
    monkeypatch.setattr(settings, f"{role}_API_KEY", "test-secret-key")
    monkeypatch.setattr(settings, f"{role}_MODEL", model)


def test_empty_task_has_initial_stage_and_no_artifacts(workflow_client):
    client, work_root = workflow_client
    (work_root / "empty-task").mkdir()

    state = client.get("/workflow_state", params={"task_id": "empty-task"})
    artifacts = client.get("/artifacts", params={"task_id": "empty-task", "stage_id": "00-intake"})

    assert state.status_code == 200
    assert state.json()["stages"][0]["status"] == "READY"
    assert all(stage["status"] == "LOCKED" for stage in state.json()["stages"][1:])
    assert state.json()["checklist"] is None
    assert artifacts.status_code == 200
    assert artifacts.json() == []


def test_stage_state_and_checklist_drive_status_and_artifact_stage(workflow_client):
    client, work_root = workflow_client
    task_dir = work_root / "state-task"
    output_dir = task_dir / "05_figures"
    output_dir.mkdir(parents=True)
    (output_dir / "结果 图.png").write_bytes(b"png")
    (task_dir / "TASK_CHECKLIST.md").write_text("- [x] 输入已核对\n", encoding="utf-8")
    for name in ("RUN_CONTEXT.json", "INPUT_INVENTORY.json", "CAPABILITY_REPORT.json"):
        (task_dir / name).write_text("{}", encoding="utf-8")
    (task_dir / "STAGE_STATE.json").write_text(
        '{"current_stage":"01-analysis","status":"RUNNING","history":['
        '{"stage":"00-intake","status":"PASS","outputs":["RUN_CONTEXT.json","INPUT_INVENTORY.json","CAPABILITY_REPORT.json","TASK_CHECKLIST.md"]},'
        '{"stage":"01-analysis","status":"RUNNING"},'
        '{"stage":"05-figures","status":"PASS","outputs":[{"path":"05_figures/结果 图.png"}]}'
        ']}',
        encoding="utf-8",
    )

    state = client.get("/workflow_state", params={"task_id": "state-task"})
    figures = client.get("/artifacts", params={"task_id": "state-task", "stage_id": "05-figures"})

    assert state.status_code == 200
    statuses = {stage["id"]: stage["status"] for stage in state.json()["stages"]}
    assert statuses["00-intake"] == "PASS"
    assert statuses["01-analysis"] == "RUNNING"
    assert statuses["02-modeling"] == "LOCKED"
    assert state.json()["checklist"] == "- [x] 输入已核对\n"
    assert figures.status_code == 200
    assert figures.json()[0]["path"] == "05_figures/结果 图.png"


def test_legacy_files_are_discoverable_with_encoded_nested_paths(workflow_client):
    client, work_root = workflow_client
    task_dir = work_root / "legacy-task"
    files = {
        "figures/研究 图 1.png": b"image",
        "code/拟合 模型.py": b"print(1)",
        "res.md": b"# result",
        "res.pdf": b"pdf",
    }
    for relative_path, content in files.items():
        path = task_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    all_artifacts = client.get("/artifacts", params={"task_id": "legacy-task", "stage_id": "05-figures"})
    code = client.get("/artifacts", params={"task_id": "legacy-task", "stage_id": "03-code"})
    paper = client.get("/artifacts", params={"task_id": "legacy-task", "stage_id": "06-paper"})
    compiled = client.get("/artifacts", params={"task_id": "legacy-task", "stage_id": "07-compile"})

    assert all_artifacts.status_code == 200
    image = all_artifacts.json()[0]
    assert image["filename"] == "研究 图 1.png"
    assert image["kind"] == "image"
    assert image["preview_url"] == "/static/legacy-task/figures/%E7%A0%94%E7%A9%B6%20%E5%9B%BE%201.png"
    assert code.json()[0]["kind"] == "code"
    assert paper.json()[0]["path"] == "res.md"
    assert compiled.json()[0]["path"] == "res.pdf"


def test_model_registry_exposes_codex_cli_models_without_secrets(workflow_client, monkeypatch):
    client, _ = workflow_client
    monkeypatch.setattr("app.routers.workflow_router.shutil.which", lambda name: "codex.exe")

    response = client.get("/model_registry")

    assert response.status_code == 200
    models = response.json()
    assert any(model["id"] == "gpt-6-sol" and model["provider"] == "codex-cli" for model in models)
    assert all("API_KEY" not in model for model in models)


def test_task_model_config_persists_and_invalid_update_preserves_saved_value(workflow_client, monkeypatch):
    client, work_root = workflow_client
    monkeypatch.setattr("app.routers.workflow_router.shutil.which", lambda name: "codex.exe")
    task_id = "model-task"
    (work_root / task_id).mkdir()
    params = {"task_id": task_id, "task_key": "task-key"}

    missing = client.get("/task_model_config", params=params)
    assert missing.status_code == 404

    payload = {**params, "model": "gpt-6-sol", "reasoning": "medium"}
    saved = client.put("/task_model_config", json=payload)
    assert saved.status_code == 200
    assert saved.json() == payload
    assert client.get("/task_model_config", params=params).json() == payload

    invalid = client.put("/task_model_config", json={**payload, "model": "unconfigured-model"})
    assert invalid.status_code == 422
    assert client.get("/task_model_config", params=params).json() == payload


def test_task_model_config_rejects_path_traversal_without_touching_outside(workflow_client):
    client, work_root = workflow_client
    outside = work_root.parent / "outside"
    outside.mkdir()

    response = client.get("/workflow_state", params={"task_id": "../outside"})

    assert response.status_code == 422
    assert list(outside.iterdir()) == []


def test_workflow_run_uses_saved_codex_model_and_reasoning(workflow_client, monkeypatch):
    client, work_root = workflow_client
    monkeypatch.setattr("app.routers.workflow_router.shutil.which", lambda name: "codex.exe")
    task_id = "codex-run-task"
    (work_root / task_id).mkdir()
    payload = {
        "task_id": task_id,
        "task_key": "00-intake",
        "model": "gpt-6-sol",
        "reasoning": "high",
    }
    assert client.put("/task_model_config", json=payload).status_code == 200

    class FakeRunner:
        executable = "codex.exe"

        async def run(self, *, workspace, model, reasoning, prompt, log_path):
            assert workspace == work_root / task_id
            assert model == "gpt-6-sol"
            assert reasoning == "high"
            assert "题目与附件盘点" in prompt
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("fake log", encoding="utf-8")
            return CodexEventResult(output="stage done", thread_id="thread-1", usage={"total_tokens": 12}), 0, ""

    monkeypatch.setattr("app.routers.workflow_router._get_codex_runner", lambda: FakeRunner())
    response = client.post("/workflow_run", json={"task_id": task_id, "stage_id": "00-intake"})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["model"] == "gpt-6-sol"
    assert response.json()["reasoning"] == "high"
    assert response.json()["output"] == "stage done"
    assert (work_root / task_id / "logs" / "codex").exists()


def test_workflow_run_defaults_to_luna_max_without_saved_config(workflow_client, monkeypatch):
    client, work_root = workflow_client
    monkeypatch.setattr("app.routers.workflow_router.shutil.which", lambda name: "codex.exe")
    task_id = "codex-default-task"
    (work_root / task_id).mkdir()

    class FakeRunner:
        executable = "codex.exe"

        async def run(self, *, workspace, model, reasoning, prompt, log_path):
            assert workspace == work_root / task_id
            assert model == "gpt-6-luna"
            assert reasoning == "max"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("fake default log", encoding="utf-8")
            return CodexEventResult(output="default done", thread_id="thread-default"), 0, ""

    monkeypatch.setattr("app.routers.workflow_router._get_codex_runner", lambda: FakeRunner())
    response = client.post("/workflow_run", json={"task_id": task_id, "stage_id": "00-intake"})

    assert response.status_code == 200
    assert response.json()["model"] == "gpt-6-luna"
    assert response.json()["reasoning"] == "max"


def test_workflow_run_prefers_task_default_model_config_over_stage_config(workflow_client, monkeypatch):
    client, work_root = workflow_client
    monkeypatch.setattr("app.routers.workflow_router.shutil.which", lambda name: "codex.exe")
    task_id = "codex-task-default-task"
    (work_root / task_id).mkdir()
    assert client.put("/task_model_config", json={
        "task_id": task_id,
        "task_key": "task-default",
        "model": "gpt-6-sol",
        "reasoning": "high",
    }).status_code == 200
    assert client.put("/task_model_config", json={
        "task_id": task_id,
        "task_key": "00-intake",
        "model": "gpt-6-luna",
        "reasoning": "max",
    }).status_code == 200

    class FakeRunner:
        executable = "codex.exe"

        async def run(self, *, workspace, model, reasoning, prompt, log_path):
            assert model == "gpt-6-sol"
            assert reasoning == "high"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("fake task default log", encoding="utf-8")
            return CodexEventResult(output="task default done", thread_id="thread-task-default"), 0, ""

    monkeypatch.setattr("app.routers.workflow_router._get_codex_runner", lambda: FakeRunner())
    response = client.post("/workflow_run", json={"task_id": task_id, "stage_id": "00-intake"})

    assert response.status_code == 200
    assert response.json()["model"] == "gpt-6-sol"
    assert response.json()["reasoning"] == "high"


def test_workflow_start_returns_run_id_and_persists_terminal_status(workflow_client, monkeypatch):
    client, work_root = workflow_client
    monkeypatch.setattr("app.routers.workflow_router.shutil.which", lambda name: "codex.exe")
    task_id = "codex-start-task"
    (work_root / task_id).mkdir()

    class FakeRunner:
        executable = "codex.exe"

        async def run(self, *, workspace, model, reasoning, prompt, log_path, run_id):
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("fake log", encoding="utf-8")
            return CodexEventResult(output="background done", thread_id="thread-2"), 0, ""

        async def stop(self, run_id):
            return False

    monkeypatch.setattr("app.routers.workflow_router._get_codex_runner", lambda: FakeRunner())
    started = client.post("/workflow_start", json={"task_id": task_id, "stage_id": "00-intake"})

    assert started.status_code == 200
    run_id = started.json()["run_id"]
    assert started.json()["status"] == "running"

    status = client.get(f"/workflow_run/{run_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "completed"
    assert status.json()["output"] == "background done"


def test_workflow_intake_creates_inventory_for_mixed_uploads(workflow_client):
    client, work_root = workflow_client
    response = client.post(
        "/workflow_intake",
        data={"question": "一个带附件的题目", "template": "国赛", "output_format": "Markdown"},
        files=[
            ("files", ("data.csv", b"x,y\n1,2\n", "text/csv")),
            ("files", ("notes.txt", "说明".encode("utf-8"), "text/plain")),
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    task_id = payload["task_id"]
    assert (work_root / task_id / "INPUT_INVENTORY.json").is_file()
    inventory = client.get("/workflow_input_inventory", params={"task_id": task_id})
    assert inventory.status_code == 200
    assert inventory.json()["counts"]["stored"] == 3
    acceptance = client.get(
        "/workflow_acceptance",
        params={"task_id": task_id, "stage_id": "00-intake"},
    )
    assert acceptance.status_code == 200
    assert acceptance.json()["verdict"] == "BLOCKED"


def test_workflow_state_locks_following_stages_when_acceptance_fails(workflow_client):
    client, work_root = workflow_client
    task_dir = work_root / "acceptance-gate-task"
    task_dir.mkdir()
    (task_dir / "STAGE_STATE.json").write_text(
        '{"history":[{"stage":"00-intake","status":"PASS","outputs":[]},'
        '{"stage":"01-analysis","status":"PASS","outputs":[]}]}',
        encoding="utf-8",
    )

    response = client.get("/workflow_state", params={"task_id": "acceptance-gate-task"})

    assert response.status_code == 200
    statuses = {stage["id"]: stage["status"] for stage in response.json()["stages"]}
    assert statuses["00-intake"] == "FAIL"
    assert statuses["01-analysis"] == "LOCKED"
