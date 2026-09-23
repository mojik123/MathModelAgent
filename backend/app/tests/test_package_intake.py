from __future__ import annotations

import json
import zipfile
from io import BytesIO

from app.services.package_intake import IntakeUpload, ingest_package


def _zip_bytes(*entries: tuple[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return buffer.getvalue()


def test_ingest_package_writes_contract_and_extracts_mixed_inputs(tmp_path):
    result = ingest_package(
        tmp_path / "task",
        task_id="workflow-test",
        question="请建立一个可验证的模型。",
        uploads=[
            IntakeUpload("data.csv", "x,y\n1,2\n".encode()),
            IntakeUpload(
                "附件.zip",
                _zip_bytes(
                    ("题目说明.md", "# 子问题\n".encode()),
                    ("data/values.csv", "a,b\n3,4\n".encode()),
                ),
            ),
        ],
    )

    workspace = tmp_path / "task"
    assert result["status"] == "created"
    assert (workspace / "QUESTION.md").is_file()
    assert (workspace / "INPUT_INVENTORY.json").is_file()
    assert (workspace / "CAPABILITY_REPORT.json").is_file()
    assert (workspace / "STAGE_STATE.json").is_file()
    assert (workspace / "TASK_CHECKLIST.md").is_file()
    assert (workspace / "user_data" / "附件.zip").is_file()
    assert (workspace / "user_data" / "附件__extracted" / "题目说明.md").is_file()
    inventory = json.loads((workspace / "INPUT_INVENTORY.json").read_text(encoding="utf-8"))
    assert inventory["counts"]["stored"] >= 3
    assert any(entry["text_extraction"] == "extracted" for entry in inventory["entries"])


def test_ingest_package_rejects_archive_traversal_without_writing_outside(tmp_path):
    workspace = tmp_path / "task"
    outside = tmp_path / "escape.txt"
    result = ingest_package(
        workspace,
        task_id="workflow-test",
        question="题目",
        uploads=[IntakeUpload("unsafe.zip", _zip_bytes(("../../escape.txt", b"bad")))],
    )

    assert result["rejected"]
    assert not outside.exists()
    assert not list(tmp_path.glob("escape.txt"))
