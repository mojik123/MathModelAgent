param(
    [ValidateSet("auto", "local", "docker")]
    [string]$BackendMode = "auto",
    [int]$BackendPort = 8000,
    [string]$FrontendHost = "localhost",
    [int]$FrontendPort = 5174,
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$StopOnly,
    [switch]$Status,
    [switch]$Build
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$logDir = Join-Path $root ".codex-run\dev-logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Get-ListenProcessIds([int]$Port) {
    @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
}

function Get-ProcessInfoForPort([int]$Port) {
    $ids = Get-ListenProcessIds $Port
    foreach ($id in $ids) {
        $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
        $cmd = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
        [pscustomobject]@{
            Port = $Port
            Id = $id
            Name = $proc.ProcessName
            Path = $proc.Path
            CommandLine = $cmd.CommandLine
        }
    }
}

function Stop-Port([int]$Port) {
    $ids = Get-ListenProcessIds $Port
    foreach ($id in $ids) {
        $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
        if (-not $proc) { continue }
        Write-Host "Stopping port $Port process $id ($($proc.ProcessName))"
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
}

function Get-BrowserHost([string]$HostName) {
    if ($HostName -eq "0.0.0.0" -or $HostName -eq "::") { return "localhost" }
    return $HostName
}

function Wait-Port([int]$Port, [int]$TimeoutSeconds = 20, [string]$HostName = "localhost") {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $client = $null
        try {
            $client = [System.Net.Sockets.TcpClient]::new()
            $task = $client.ConnectAsync($HostName, $Port)
            if ($task.Wait(300) -and $client.Connected) {
                $client.Dispose()
                return $true
            }
        } catch {
        } finally {
            if ($client) { $client.Dispose() }
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Test-HttpEndpoint([string]$Url, [int]$TimeoutSeconds = 2) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSeconds
        return [pscustomobject]@{
            Ok = $true
            StatusCode = [int]$response.StatusCode
            Error = $null
        }
    } catch {
        return [pscustomobject]@{
            Ok = $false
            StatusCode = $null
            Error = $_.Exception.Message
        }
    }
}

function Format-HttpStatusCode($StatusCode) {
    if ($null -eq $StatusCode) { return "no response" }
    return "$StatusCode"
}

function Wait-HttpEndpoint([string]$Url, [int]$TimeoutSeconds = 30) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $result = Test-HttpEndpoint $Url 2
        if ($result.Ok) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Resolve-NodeExe {
    if ($env:NODE_EXE -and (Test-Path $env:NODE_EXE)) { return $env:NODE_EXE }
    $cmd = Get-Command node -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $known = "E:\Program Files\nodejs\node.exe"
    if (Test-Path $known) { return $known }
    throw "node.exe not found"
}

function Resolve-BackendMode {
    if ($BackendMode -ne "auto") { return $BackendMode }
    $py = Join-Path $backendDir ".venv\Scripts\python.exe"
    if (Test-Path $py) { return "local" }
    if (Get-Command uv -ErrorAction SilentlyContinue) { return "local" }
    return "docker"
}

function Start-Frontend {
    $vite = Join-Path $frontendDir "node_modules\vite\bin\vite.js"
    if (-not (Test-Path $vite)) {
        throw "Vite is missing. Run dependency install in frontend first."
    }

    $node = Resolve-NodeExe
    $out = Join-Path $logDir "frontend.out.log"
    $err = Join-Path $logDir "frontend.err.log"
    Remove-Item -LiteralPath $out, $err -ErrorAction SilentlyContinue

    $frontendUrlHost = Get-BrowserHost $FrontendHost
    Write-Host "Starting frontend on http://${frontendUrlHost}:$FrontendPort"
    Start-Process `
        -FilePath $node `
        -ArgumentList @($vite, "--host", "$FrontendHost", "--port", "$FrontendPort", "--strictPort") `
        -WorkingDirectory $frontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $out `
        -RedirectStandardError $err | Out-Null
}

function Start-BackendLocal {
    $env:ENV = "DEV"
    if (-not $env:REDIS_URL) {
        $env:REDIS_URL = "redis://localhost:6379/0"
    }

    $python = Join-Path $backendDir ".venv\Scripts\python.exe"
    $out = Join-Path $logDir "backend.out.log"
    $err = Join-Path $logDir "backend.err.log"
    Remove-Item -LiteralPath $out, $err -ErrorAction SilentlyContinue

    if (Test-Path $python) {
        Write-Host "Starting local backend on http://localhost:$BackendPort"
        Start-Process `
            -FilePath $python `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$BackendPort", "--reload", "--reload-dir", "app", "--ws-ping-interval", "60", "--ws-ping-timeout", "120") `
            -WorkingDirectory $backendDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput $out `
            -RedirectStandardError $err | Out-Null
        return
    }

    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        Write-Host "Starting local backend via uv on http://localhost:$BackendPort"
        Start-Process `
            -FilePath $uv.Source `
            -ArgumentList @("run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$BackendPort", "--reload", "--reload-dir", "app", "--ws-ping-interval", "60", "--ws-ping-timeout", "120") `
            -WorkingDirectory $backendDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput $out `
            -RedirectStandardError $err | Out-Null
        return
    }

    throw "No local backend runtime found. Use -BackendMode docker or install uv / backend .venv."
}

function Start-BackendDocker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker is not available"
    }
    $env:DOCKER_CONFIG = Join-Path $root ".docker-config"
    Push-Location $root
    try {
        Write-Host "Starting Docker redis + backend on http://localhost:$BackendPort"
        $oldErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        if ($Build) {
            docker compose up -d --build redis backend
        } else {
            docker compose up -d redis backend
        }
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose up failed with exit code $LASTEXITCODE"
        }
        $ErrorActionPreference = $oldErrorActionPreference
    } finally {
        if ($oldErrorActionPreference) {
            $ErrorActionPreference = $oldErrorActionPreference
        }
        Pop-Location
    }
}

function Show-Status {
    Write-Host "Dev status"
    foreach ($port in @($BackendPort, $FrontendPort)) {
        $items = @(Get-ProcessInfoForPort $port)
        if ($items.Count -eq 0) {
            Write-Host "Port ${port}: not listening"
        } else {
            foreach ($item in $items) {
                Write-Host "Port ${port}: PID $($item.Id) $($item.Name)"
            }
        }
    }
    $frontendUrlHost = Get-BrowserHost $FrontendHost
    $frontendUrl = "http://${frontendUrlHost}:$FrontendPort"
    $backendHealthUrl = "http://localhost:$BackendPort/healthz"
    $backendStatusUrl = "http://localhost:$BackendPort/status"
    $frontendStatus = Test-HttpEndpoint $frontendUrl 2
    $backendHealth = Test-HttpEndpoint $backendHealthUrl 2
    $backendStatus = Test-HttpEndpoint $backendStatusUrl 2
    Write-Host "Frontend URL: $frontendUrl [$(Format-HttpStatusCode $frontendStatus.StatusCode)]"
    Write-Host "Backend health: $backendHealthUrl [$(Format-HttpStatusCode $backendHealth.StatusCode)]"
    Write-Host "Backend status: $backendStatusUrl [$(Format-HttpStatusCode $backendStatus.StatusCode)]"
    Write-Host "Logs: $logDir"
}

if ($Status) {
    Show-Status
    exit 0
}

$mode = Resolve-BackendMode

if (-not $FrontendOnly) {
    if ($mode -eq "docker") {
        Push-Location $root
        try {
            $oldErrorActionPreference = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            docker compose stop backend *> $null
            $ErrorActionPreference = $oldErrorActionPreference
        } finally {
            if ($oldErrorActionPreference) {
                $ErrorActionPreference = $oldErrorActionPreference
            }
            Pop-Location
        }
    } else {
        Stop-Port $BackendPort
    }
}

if (-not $BackendOnly) {
    Stop-Port $FrontendPort
}

if ($StopOnly) {
    Show-Status
    exit 0
}

if (-not $FrontendOnly) {
    if ($mode -eq "docker") {
        Start-BackendDocker
    } else {
        Start-BackendLocal
    }
}

if (-not $BackendOnly) {
    Start-Frontend
}

$backendReady = $true
$frontendReady = $true
$frontendUrlHost = Get-BrowserHost $FrontendHost
if (-not $FrontendOnly) {
    $backendReady = Wait-HttpEndpoint "http://localhost:$BackendPort/healthz" 30
    if (-not $backendReady) {
        $backendReady = Wait-Port $BackendPort 5 "127.0.0.1"
    }
}
if (-not $BackendOnly) {
    $frontendReady = Wait-HttpEndpoint "http://${frontendUrlHost}:$FrontendPort" 30
    if (-not $frontendReady) {
        $frontendReady = Wait-Port $FrontendPort 5 $frontendUrlHost
    }
}

Show-Status
if (-not $backendReady) {
    Write-Host "Backend did not become ready within timeout. Check backend.err.log."
}
if (-not $frontendReady) {
    Write-Host "Frontend did not become ready within timeout. Check frontend.err.log."
}
