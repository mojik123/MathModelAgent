"""Run one math-modeling stage through the locally authenticated Codex CLI."""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CodexEventResult:
    output: str = ""
    thread_id: str | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None


def parse_codex_events(raw: str) -> CodexEventResult:
    """Extract the final agent message from Codex JSONL output."""

    output = ""
    thread_id: str | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if event.get("type") == "thread.started":
            thread_id = event.get("thread_id") or thread_id
        elif event.get("type") == "turn.completed":
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
        elif event.get("type") == "item.completed":
            item = event.get("item") or {}
            item_type = item.get("type")
            if item_type == "agent_message" and isinstance(item.get("text"), str):
                output = item["text"]
            elif item_type == "error" and isinstance(item.get("message"), str):
                error = item["message"]

    return CodexEventResult(output=output, thread_id=thread_id, usage=usage, error=error)


class CodexRunner:
    """Small subprocess adapter for the user's locally authenticated Codex CLI."""

    def __init__(self, executable: str | None = None, timeout_seconds: int = 1800) -> None:
        self.executable = executable or shutil.which("codex.exe") or shutil.which("codex")
        self.timeout_seconds = timeout_seconds
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}
        self._stop_requested: set[str] = set()

    def build_command(
        self,
        *,
        workspace: Path,
        model: str,
        reasoning: str,
        prompt: str,
    ) -> list[str]:
        if not self.executable:
            raise RuntimeError("未找到 Codex CLI，请先安装并登录 Codex。")

        return [
            self.executable,
            "exec",
            "--ephemeral",
            "--json",
            "--color",
            "never",
            "--skip-git-repo-check",
            "--cd",
            str(workspace),
            "--model",
            model,
            "--config",
            f'model_reasoning_effort="{reasoning}"',
            "--approve-for-me",
            prompt,
        ]

    async def run(
        self,
        *,
        workspace: Path,
        model: str,
        reasoning: str,
        prompt: str,
        log_path: Path,
        run_id: str | None = None,
    ) -> tuple[CodexEventResult, int, str]:
        command = self.build_command(
            workspace=workspace,
            model=model,
            reasoning=reasoning,
            prompt=prompt,
        )
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(workspace),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if run_id:
            self._active_processes[run_id] = process
            if run_id in self._stop_requested:
                process.kill()

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise TimeoutError(f"Codex 阶段执行超过 {self.timeout_seconds} 秒") from None
        finally:
            if run_id:
                self._active_processes.pop(run_id, None)
                self._stop_requested.discard(run_id)

        raw_stdout = stdout.decode("utf-8", errors="replace")
        raw_stderr = stderr.decode("utf-8", errors="replace")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            json.dumps(
                {
                    "command": command[:-1] + ["<prompt>"],
                    "stdout": raw_stdout,
                    "stderr": raw_stderr,
                    "returncode": process.returncode,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        result = parse_codex_events(raw_stdout)
        if process.returncode != 0 and not result.error:
            result = CodexEventResult(
                output=result.output,
                thread_id=result.thread_id,
                usage=result.usage,
                error=raw_stderr.strip() or f"Codex CLI 退出码 {process.returncode}",
            )
        return result, process.returncode or 0, raw_stderr

    async def stop(self, run_id: str) -> bool:
        """Terminate a currently running Codex process, if one exists."""

        self._stop_requested.add(run_id)
        process = self._active_processes.pop(run_id, None)
        if process is None:
            return False
        if process.returncode is None:
            process.kill()
        return True
