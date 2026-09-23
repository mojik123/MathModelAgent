# MathModelAgent deployment notes

## Current project configuration

- Backend config: `backend/.env.dev`
- Frontend config: `frontend/.env.development`
- Model provider: DeepSeek
- Model: `deepseek-chat`
- API base URL: `https://api.deepseek.com/v1`
- Docker Redis URL: `redis://redis:6379/0`

## Codex workflow workbench

The stage workbench (`00` to `08`) uses the locally authenticated Codex CLI.
The model and reasoning selector is saved per stage and is passed to the CLI
when that stage starts. The browser never receives a Codex API key.

Verify the local CLI before using the workbench:

```powershell
Get-Command codex
codex login
```

Use the stage model panel to select a model and reasoning strength, click
`保存本阶段设置`, then click `运行当前阶段`. The run log is written below the
task workspace under `logs/codex/` and the workbench can stop an active stage.
When a stage has no saved setting, the default is `gpt-6-luna` with `max`
reasoning; an explicitly saved stage setting takes precedence.

The existing DeepSeek configuration remains available to the legacy
multi-agent `/modeling/{task_id}/start` flow. It is separate from the Codex
stage workbench flow.

## Complete problem-package intake

The workbench upload entry calls `POST /workflow_intake`. It accepts inline
question text plus mixed PDF, DOCX, ZIP, image, spreadsheet, and text
attachments. ZIP entries are extracted below the task's `user_data/` folder
after path and size checks. Stage 00 input files are recorded in:

- `RUN_CONTEXT.json`
- `INPUT_INVENTORY.json`
- `CAPABILITY_REPORT.json`
- `TASK_CHECKLIST.md`
- `STAGE_STATE.json`

The `独立验收` button calls `GET /workflow_acceptance` and checks files and
JSON/PDF readability independently of the model's self-reported status. Run
metadata is stored atomically in `logs/codex/runs/`; a backend restart marks a
previously running entry as `interrupted` instead of leaving it falsely active.

For a local smoke check after installing dependencies:

```powershell
Set-Location .\backend
python -m pytest app/tests -q --ignore=app/tests/mock
Set-Location ..\frontend
pnpm exec vitest run
npm run type-check
npm run build
```

The DeepSeek API key is configured in `backend/.env.dev`.

## Required system dependency

Install Docker Desktop for Windows:

https://www.docker.com/products/docker-desktop/

Docker Desktop is required because this project runs three services together:

- Redis
- backend API
- frontend web UI

After installing Docker Desktop, restart the computer if Docker asks for it.

## Start the app

Open a normal Windows PowerShell as your Windows user, not inside Codex, in this folder:

```powershell
C:\Users\mojik\Desktop\mm-auto-3\MathModelAgent-main
```

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-docker.ps1
```

If Docker Desktop asks to finish setup or restart Windows, complete that first and run the same command again.

When startup finishes, open:

- Frontend: http://localhost:5173
- Backend: http://localhost:8000

## Check configuration

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\check-config.ps1
```

This checks whether the backend config, frontend config, DeepSeek keys, and Docker are available without printing the key value.
