$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:DOCKER_CONFIG = Join-Path $root ".docker-config"
$backendEnv = Join-Path $root "backend\.env.dev"
$frontendEnv = Join-Path $root "frontend\.env.development"

Write-Host "MathModelAgent configuration check"
Write-Host "Project: $root"
Write-Host ""

if (Test-Path $backendEnv) {
    Write-Host "Backend env: OK"
    $requiredKeys = @(
        "COORDINATOR_API_KEY",
        "MODELER_API_KEY",
        "CODER_API_KEY",
        "WRITER_API_KEY"
    )
    $envText = Get-Content $backendEnv
    foreach ($key in $requiredKeys) {
        $line = $envText | Where-Object { $_ -match "^$key=" } | Select-Object -First 1
        if ($line -and (($line -split "=", 2)[1]).Trim()) {
            Write-Host "${key}: SET"
        } else {
            Write-Host "${key}: EMPTY"
        }
    }
} else {
    Write-Host "Backend env: MISSING"
}

if (Test-Path $frontendEnv) {
    Write-Host "Frontend env: OK"
} else {
    Write-Host "Frontend env: MISSING"
}

if (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-Host "Docker: FOUND"
    docker --version
} else {
    Write-Host "Docker: MISSING"
}

if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
    Write-Host "docker-compose: FOUND"
} elseif (Get-Command docker -ErrorAction SilentlyContinue) {
    docker compose version
} else {
    Write-Host "Docker Compose: MISSING"
}
