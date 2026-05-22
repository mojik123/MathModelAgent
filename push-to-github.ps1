# MathModelAgent - 一键推送到 GitHub
# 双击运行即可提交所有修改并推送

Set-Location $PSScriptRoot

$message = if ($args.Count -gt 0) { $args[0] } else { "update: $(Get-Date -Format 'yyyy-MM-dd HH:mm')" }

Write-Host ">>> 提交中: $message" -ForegroundColor Cyan

git add -A
git commit -m $message 2>$null

if ($LASTEXITCODE -eq 0) {
    Write-Host ">>> 推送中..." -ForegroundColor Cyan
    git push
    Write-Host ">>> 完成!" -ForegroundColor Green
} else {
    Write-Host ">>> 无变更可提交，直接推送..." -ForegroundColor Yellow
    git push
    Write-Host ">>> 完成!" -ForegroundColor Green
}

Read-Host "按回车关闭"
