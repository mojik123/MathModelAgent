$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = Split-Path -Parent $PSScriptRoot
$targetDir = Join-Path $root "third_party\CUMCMThesis"
$zipPath = Join-Path $root "third_party\CUMCMThesis.zip"
$url = "https://github.com/latexstudio/CUMCMThesis/archive/refs/heads/master.zip"

New-Item -ItemType Directory -Force (Join-Path $root "third_party") | Out-Null

if (Test-Path $targetDir) {
    Write-Host "CUMCMThesis already exists: $targetDir"
    exit 0
}

Write-Host "Downloading CUMCMThesis from GitHub..."
Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing

Write-Host "Extracting..."
Expand-Archive -Path $zipPath -DestinationPath (Join-Path $root "third_party") -Force

$extracted = Join-Path $root "third_party\CUMCMThesis-master"
if (Test-Path $extracted) {
    Move-Item -Path $extracted -Destination $targetDir
}

Write-Host "Installed: $targetDir"

