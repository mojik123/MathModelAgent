[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$SkipBrowser,
    [switch]$SkipPull
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$restartScript = Join-Path $projectRoot "scripts\restart-dev.ps1"
$frontendDir = Join-Path $projectRoot "frontend"
$frontendVite = Join-Path $frontendDir "node_modules\vite\bin\vite.js"
$frontendUrl = "http://localhost:5174"
$backendHealthUrl = "http://localhost:8000/healthz"
$originalLocation = Get-Location
$exitCode = 0

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory)]
        [string]$Command,
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE"
    }
}

function Test-DockerEngine {
    $null = & docker info --format "{{.ServerVersion}}" 2>$null
    return $LASTEXITCODE -eq 0
}

function Invoke-GitPull {
    $maximumAttempts = 3
    for ($attempt = 1; $attempt -le $maximumAttempts; $attempt++) {
        & git pull --ff-only
        if ($LASTEXITCODE -eq 0) {
            return
        }

        if ($attempt -lt $maximumAttempts) {
            Write-Host "Git pull failed. Retrying ($attempt/$maximumAttempts)..." `
                -ForegroundColor Yellow
            Start-Sleep -Seconds 3
        }
    }

    throw "Git pull failed after $maximumAttempts attempts."
}

function Start-DockerEngine {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker is not installed or is not available in PATH."
    }
    if (Test-DockerEngine) {
        return
    }

    $dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path -LiteralPath $dockerDesktop)) {
        throw "Docker Desktop is not installed at the expected location."
    }

    Write-Host "Docker engine is stopped. Starting Docker Desktop..."
    Start-Process -FilePath $dockerDesktop -WindowStyle Hidden

    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        if (Test-DockerEngine) {
            Write-Host "Docker engine is ready."
            return
        }
    }

    throw "Docker Desktop did not become ready within 120 seconds."
}

function Wait-HttpEndpoint {
    param(
        [Parameter(Mandatory)]
        [string]$Url,
        [int]$TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest `
                -Uri $Url `
                -UseBasicParsing `
                -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                return
            }
        } catch {
        }
        Start-Sleep -Seconds 1
    }

    throw "Service did not become ready: $Url"
}

try {
    Set-Location -LiteralPath $projectRoot

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git is not installed or is not available in PATH."
    }
    if (-not (Test-Path -LiteralPath $restartScript)) {
        throw "Missing startup script: $restartScript"
    }

    $branch = (& git branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $branch) {
        throw "Unable to determine the current Git branch."
    }
    Write-Host "Current branch: $branch"

    $beforeCommit = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to read the current Git commit."
    }

    if (-not $SkipPull) {
        $pendingChanges = @(& git status --porcelain=v1)
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to inspect the Git working tree."
        }
        if ($pendingChanges.Count -gt 0) {
            Write-Host "Local changes were found:" -ForegroundColor Yellow
            $pendingChanges | ForEach-Object { Write-Host "  $_" }
            throw "Upload, commit, or stash local changes before synchronizing."
        }

        Write-Host "Pulling the latest changes from GitHub..."
        Invoke-GitPull
    } else {
        Write-Host "Skipping Git pull."
    }

    $afterCommit = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to read the updated Git commit."
    }
    Write-Host "Running commit: $afterCommit"

    $backendDependenciesChanged = $false
    $frontendDependenciesChanged = $false
    if ($beforeCommit -ne $afterCommit) {
        $changedFiles = @(& git diff --name-only "$beforeCommit..$afterCommit")
        if ($LASTEXITCODE -eq 0) {
            $backendDependenciesChanged = @(
                $changedFiles | Where-Object {
                    $_ -match "^(backend/(Dockerfile|pyproject\.toml|uv\.lock)|docker-compose(\.override)?\.yml)$"
                }
            ).Count -gt 0
            $frontendDependenciesChanged = @(
                $changedFiles | Where-Object {
                    $_ -match "^frontend/(package\.json|pnpm-lock\.yaml)$"
                }
            ).Count -gt 0
        }
    }

    if ($frontendDependenciesChanged -or -not (Test-Path -LiteralPath $frontendVite)) {
        if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
            throw "Frontend dependencies are missing and pnpm is unavailable."
        }
        Write-Host "Installing frontend dependencies..."
        Push-Location -LiteralPath $frontendDir
        try {
            Invoke-NativeCommand -Command "pnpm" -Arguments @("install", "--frozen-lockfile")
        } finally {
            Pop-Location
        }
    }

    $localPython = Join-Path $projectRoot "backend\.venv\Scripts\python.exe"
    $hasLocalBackend = (Test-Path -LiteralPath $localPython) -or
        [bool](Get-Command uv -ErrorAction SilentlyContinue)
    if (-not $hasLocalBackend) {
        Start-DockerEngine
    }

    $shouldBuild = $Build -or $backendDependenciesChanged
    if ($shouldBuild) {
        Write-Host "Dependency changes detected. Rebuilding the backend image..."
        & powershell `
            -NoProfile `
            -ExecutionPolicy Bypass `
            -File $restartScript `
            -Build
    } else {
        & powershell `
            -NoProfile `
            -ExecutionPolicy Bypass `
            -File $restartScript
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Project startup failed with exit code $LASTEXITCODE."
    }

    Write-Host "Checking backend and frontend..."
    Wait-HttpEndpoint -Url $backendHealthUrl -TimeoutSeconds 60
    Wait-HttpEndpoint -Url $frontendUrl -TimeoutSeconds 60

    if (-not $SkipBrowser) {
        Write-Host "Opening $frontendUrl"
        Start-Process -FilePath $frontendUrl
    }

    Write-Host "Synchronization and startup completed successfully." -ForegroundColor Green
} catch {
    $exitCode = 1
    Write-Host ""
    Write-Host "Synchronization or startup failed:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "No local files were overwritten." -ForegroundColor Yellow
} finally {
    Set-Location -LiteralPath $originalLocation
}

exit $exitCode
