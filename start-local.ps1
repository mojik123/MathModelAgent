param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$StopOnly,
    [switch]$Status
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$restartScript = Join-Path $root "scripts\restart-dev.ps1"

$arguments = @("-BackendMode", "local")
if ($BackendOnly) { $arguments += "-BackendOnly" }
if ($FrontendOnly) { $arguments += "-FrontendOnly" }
if ($StopOnly) { $arguments += "-StopOnly" }
if ($Status) { $arguments += "-Status" }

& powershell.exe -ExecutionPolicy Bypass -File $restartScript @arguments
exit $LASTEXITCODE
