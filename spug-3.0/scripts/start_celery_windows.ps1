# ========================================
# Windows 环境 Celery 启动脚本
# ========================================
# 注意：Windows下Celery必须使用solo池（无fork机制）

# 设置环境变量
$env:DJANGO_SETTINGS_MODULE = "spug.settings"
$env:PYTHONPATH = "e:\TDYW\spug-3.0\spug_api"

# 日志目录
$logDir = "e:\TDYW\spug-3.0\spug_api\logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force
}

Write-Host "Starting Celery Worker (Windows mode)..." -ForegroundColor Green

# 启动 Celery Worker（使用solo池）
Start-Process -FilePath "python" -ArgumentList @(
    "-m", "celery",
    "-A", "spug",
    "worker",
    "-l", "info",
    "-Q", "document.merge,document.batch,document.cleanup",
    "-P", "solo",
    "-n", "windows-worker@%computername%"
) -WindowStyle Normal -RedirectStandardOutput "$logDir\celery_worker.log" -RedirectStandardError "$logDir\celery_worker_error.log"

Write-Host "Starting Celery Beat..." -ForegroundColor Green

# 启动 Celery Beat
Start-Process -FilePath "python" -ArgumentList @(
    "-m", "celery",
    "-A", "spug",
    "beat",
    "-l", "info",
    "--scheduler", "django_celery_beat.schedulers:DatabaseScheduler"
) -WindowStyle Normal -RedirectStandardOutput "$logDir\celery_beat.log" -RedirectStandardError "$logDir\celery_beat_error.log"

Write-Host "Celery services started!" -ForegroundColor Green
Write-Host "Logs: $logDir" -ForegroundColor Yellow
