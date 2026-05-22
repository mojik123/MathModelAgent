param(
    [switch]$Build
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$env:DOCKER_CONFIG = Join-Path $root ".docker-config"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker is not installed or not available in PATH."
    Write-Host "Install Docker Desktop first, then run this script again."
    Write-Host "Project folder: $root"
    exit 1
}

docker compose version | Out-Null

Write-Host "Starting MathModelAgent..."
Write-Host "Frontend: http://localhost:5174"
Write-Host "Backend health: http://localhost:8000/healthz"
if ($Build) {
    docker compose up --build
} else {
    docker compose up
}
