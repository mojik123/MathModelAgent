import json
import asyncio

from app.services.codex_runner import CodexRunner, parse_codex_events


def test_build_command_passes_codex_model_reasoning_and_workspace(tmp_path):
    runner = CodexRunner(executable="codex.exe")

    command = runner.build_command(
        workspace=tmp_path,
        model="gpt-6-sol",
        reasoning="high",
        prompt="Run the current stage.",
    )

    assert command[:3] == ["codex.exe", "exec", "--ephemeral"]
    assert "--model" in command
    assert command[command.index("--model") + 1] == "gpt-6-sol"
    assert command[command.index("--config") + 1] == 'model_reasoning_effort="high"'
    assert command[command.index("--cd") + 1] == str(tmp_path)
    assert "--approve-for-me" in command
    assert "--ask-for-approval" not in command
    assert "--sandbox" not in command
    assert command[-1] == "Run the current stage."


def test_parse_codex_events_returns_final_agent_message_and_usage():
    events = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "stage output"}}),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 3}}),
        ]
    )

    result = parse_codex_events(events)

    assert result.output == "stage output"
    assert result.thread_id == "thread-1"
    assert result.usage == {"input_tokens": 10, "output_tokens": 3}


def test_parse_codex_events_keeps_error_text_when_no_agent_message():
    events = json.dumps({"type": "item.completed", "item": {"type": "error", "message": "model failed"}})

    result = parse_codex_events(events)

    assert result.output == ""
    assert result.error == "model failed"


def test_runner_stop_terminates_active_process(monkeypatch, tmp_path):
    class FakeProcess:
        returncode = None

        def __init__(self):
            self.done = asyncio.Event()

        async def communicate(self):
            await self.done.wait()
            return b"", b""

        def kill(self):
            self.returncode = -9
            self.done.set()

    async def fake_create_process(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_process)

    async def scenario():
        runner = CodexRunner(executable="codex.exe", timeout_seconds=30)
        task = asyncio.create_task(
            runner.run(
                workspace=tmp_path,
                model="gpt-6-sol",
                reasoning="medium",
                prompt="run",
                log_path=tmp_path / "run.json",
                run_id="run-1",
            )
        )
        await asyncio.sleep(0)
        assert await runner.stop("run-1") is True
        assert await runner.stop("run-1") is False
        await task

    asyncio.run(scenario())
