# 本地开发启动方式

推荐使用快速重启脚本，让 Docker 只负责 Redis/后端，前端用本机 Vite 运行：

```powershell
cd C:\Users\mojik\Desktop\mm-auto-3\MathModelAgent-main
powershell -ExecutionPolicy Bypass -File .\scripts\restart-dev.ps1 -BackendMode docker
```

启动后访问：

- 前端：http://localhost:5174
- 后端轻量健康检查：http://localhost:8000/healthz
- 后端详细状态：http://localhost:8000/status

常用命令：

```powershell
# 查看当前端口和健康状态
powershell -ExecutionPolicy Bypass -File .\scripts\restart-dev.ps1 -Status

# 只重启前端，不打断后端正在跑的建模任务
powershell -ExecutionPolicy Bypass -File .\scripts\restart-dev.ps1 -FrontendOnly

# 只重启后端。注意：会打断正在运行的建模任务
powershell -ExecutionPolicy Bypass -File .\scripts\restart-dev.ps1 -BackendOnly -BackendMode docker

# 停止前后端开发服务
powershell -ExecutionPolicy Bypass -File .\scripts\restart-dev.ps1 -StopOnly
```

如果使用完整 Docker 启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-docker.ps1
```

完整 Docker 也统一使用前端端口 `5174`。
