from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_local_launcher_keeps_only_redis_in_docker():
    launcher = (ROOT / "start-local.ps1").read_text(encoding="utf-8")
    restart = (ROOT / "scripts" / "restart-dev.ps1").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert '"-BackendMode", "local"' in launcher
    assert "docker compose up -d redis" in restart
    assert '[string]$FrontendHost = "0.0.0.0"' in restart
    assert "function Stop-ProcessTree" in restart
    assert "function Stop-LocalBackendProcesses" in restart
    assert "function Get-ProbeHost" in restart
    assert "6379:6379" in compose
    assert "docker compose up -d --build redis backend" in restart
