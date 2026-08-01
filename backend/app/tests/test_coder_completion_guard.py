from types import SimpleNamespace

from app.core.agents.coder_completion_guard import _response_calls_task_complete


def test_plain_text_response_does_not_complete_coder() -> None:
    response = SimpleNamespace(tool_calls=[])

    assert _response_calls_task_complete(response) is False


def test_execute_code_response_does_not_complete_coder() -> None:
    response = SimpleNamespace(
        tool_calls=[SimpleNamespace(name="execute_code")],
    )

    assert _response_calls_task_complete(response) is False


def test_explicit_task_complete_response_completes_coder() -> None:
    response = SimpleNamespace(
        tool_calls=[SimpleNamespace(name="task_complete")],
    )

    assert _response_calls_task_complete(response) is True
