# 回收站功能Docker测试脚本 (PowerShell)
# 适用于容器名: tdyw

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "    回收站功能Docker测试脚本" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$CONTAINER_NAME = "tdyw"

# 检查容器是否运行
$container = docker ps --format "{{.Names}}" | Where-Object { $_ -eq $CONTAINER_NAME }
if (-not $container) {
    Write-Host "[错误] 容器 $CONTAINER_NAME 未运行" -ForegroundColor Red
    Write-Host "可用的容器:" -ForegroundColor Yellow
    docker ps --format "table {{.Names}}\t{{.Status}}"
    exit 1
}

Write-Host "[✓] 容器 $CONTAINER_NAME 运行正常" -ForegroundColor Green
Write-Host ""

function Docker-Exec {
    param([string]$Command)
    docker exec $CONTAINER_NAME $Command
}

# 检查Python语法
Write-Host "[1/4] 执行Python语法检查..." -ForegroundColor Cyan
try {
    Docker-Exec "python -m py_compile /data/spug/spug_api/apps/document/models.py"
    Docker-Exec "python -m py_compile /data/spug/spug_api/apps/document/views/recycle_bin.py"
    Docker-Exec "python -m py_compile /data/spug/spug_api/apps/document/urls.py"
    Docker-Exec "python -m py_compile /data/spug/spug_api/apps/document/tasks/cleanup.py"
    
    if (Test-Path "tests/test_recycle_bin.py") {
        docker cp tests/test_recycle_bin.py ${CONTAINER_NAME}:/data/spug/tests/
        Docker-Exec "python -m py_compile /data/spug/tests/test_recycle_bin.py"
    }
    Write-Host "[✓] 语法检查全部通过" -ForegroundColor Green
} catch {
    Write-Host "[✗] 语法检查失败: $_" -ForegroundColor Red
}
Write-Host ""

# 检查数据库表结构
Write-Host "[2/4] 检查数据库表结构..." -ForegroundColor Cyan
docker exec $CONTAINER_NAME python /data/spug/spug_api/manage.py showmigrations document 2>$null | Select-Object -Last 20
Write-Host ""

# 检查回收站相关配置
Write-Host "[3/4] 检查回收站配置..." -ForegroundColor Cyan
docker exec $CONTAINER_NAME python -c "
import sys
sys.path.insert(0, '/data/spug/spug_api')
import os
os.chdir('/data/spug/spug_api')

import django
django.setup()

from django.conf import settings

print('回收站配置:')
retention = getattr(settings, 'RECYCLE_BIN_RETENTION_DAYS', '未设置')
batch_limit = getattr(settings, 'RECYCLE_BIN_BATCH_LIMIT', '未设置')
cache_ttl = getattr(settings, 'RECYCLE_BIN_CACHE_TTL', '未设置')
print(f'  RECYCLE_BIN_RETENTION_DAYS: {retention}')
print(f'  RECYCLE_BIN_BATCH_LIMIT: {batch_limit}')
print(f'  RECYCLE_BIN_CACHE_TTL: {cache_ttl}')

from apps.document.models import DocumentFilePrivate
print('')
print('模型方法检查:')
has_delete = '✓' if hasattr(DocumentFilePrivate, 'delete') else '✗'
has_restore = '✓' if hasattr(DocumentFilePrivate, 'restore') else '✗'
print(f'  delete方法: {has_delete}')
print(f'  restore方法: {has_restore}')
"
Write-Host ""

# 检查Celery任务
Write-Host "[4/4] 检查Celery任务..." -ForegroundColor Cyan
docker exec $CONTAINER_NAME python -c "
import sys
sys.path.insert(0, '/data/spug/spug_api')
import os
os.chdir('/data/spug/spug_api')

from apps.document.celery_beat_schedule import DOCUMENT_BEAT_SCHEDULE

print('定时任务配置:')
for name, config in DOCUMENT_BEAT_SCHEDULE.items():
    if 'cleanup' in name or 'recycle' in name:
        schedule = config.get('schedule', 'N/A')
        print(f'  - {name}: {schedule}')
"
Write-Host ""

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "    环境检查完成！" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "手动执行单元测试命令:" -ForegroundColor Yellow
Write-Host "  docker exec $CONTAINER_NAME python /data/spug/spug_api/manage.py test tests.test_recycle_bin -v 2" -ForegroundColor Gray
Write-Host ""
Write-Host "API手动测试:" -ForegroundColor Yellow
Write-Host "  1. 先获取Token:" -ForegroundColor Gray
Write-Host "     Invoke-RestMethod -Uri 'http://localhost/api/account/login/' -Method POST -ContentType 'application/json' -Body '{`"username`":`"admin`",`"password`":`"your_password`"}'" -ForegroundColor Gray
Write-Host ""
Write-Host "  2. 测试回收站列表:" -ForegroundColor Gray
Write-Host "     Invoke-RestMethod -Uri 'http://localhost/api/document/recycle-bin/' -Headers @{Authorization='Bearer YOUR_TOKEN'}" -ForegroundColor Gray
