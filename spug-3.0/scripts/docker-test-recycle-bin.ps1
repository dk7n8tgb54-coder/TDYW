# 回收站功能Docker测试脚本 (PowerShell版本)
# 使用方法: .\docker-test-recycle-bin.ps1

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "    回收站功能Docker测试脚本" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# 检查Docker是否运行
try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Docker未运行"
    }
    Write-Host "[✓] Docker运行正常" -ForegroundColor Green
} catch {
    Write-Host "[错误] Docker未运行，请先启动Docker" -ForegroundColor Red
    exit 1
}

Write-Host ""

# 获取容器名称
$API_CONTAINER = docker ps --filter "name=api" --format "{{.Names}}" | Select-Object -First 1

if (-not $API_CONTAINER) {
    Write-Host "[警告] 未找到api容器，尝试查找其他可能的容器名..." -ForegroundColor Yellow
    $API_CONTAINER = docker ps --format "{{.Names}}" | Where-Object { $_ -match "(api|backend|spug)" } | Select-Object -First 1
}

if (-not $API_CONTAINER) {
    Write-Host "[错误] 未找到API容器，请确保项目已启动" -ForegroundColor Red
    Write-Host "可用的容器列表:" -ForegroundColor Yellow
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    exit 1
}

Write-Host "[✓] 找到API容器: $API_CONTAINER" -ForegroundColor Green
Write-Host ""

# 检查Python语法
Write-Host "[1/5] 执行Python语法检查..." -ForegroundColor Cyan
try {
    docker exec $API_CONTAINER python -m py_compile apps/document/models.py
    docker exec $API_CONTAINER python -m py_compile apps/document/views/recycle_bin.py
    docker exec $API_CONTAINER python -m py_compile apps/document/urls.py
    docker exec $API_CONTAINER python -m py_compile apps/document/tasks/cleanup.py
    docker exec $API_CONTAINER python -m py_compile tests/test_recycle_bin.py
    Write-Host "[✓] 语法检查全部通过" -ForegroundColor Green
} catch {
    Write-Host "[✗] 语法检查失败: $_" -ForegroundColor Red
    exit 1
}
Write-Host ""

# 检查数据库迁移
Write-Host "[2/5] 检查数据库迁移状态..." -ForegroundColor Cyan
docker exec $API_CONTAINER python manage.py showmigrations document | Select-String -Pattern "(X|\[ \])"
Write-Host ""

# 执行单元测试
Write-Host "[3/5] 执行回收站单元测试..." -ForegroundColor Cyan
docker exec $API_CONTAINER python manage.py test tests.test_recycle_bin -v 2
if ($LASTEXITCODE -ne 0) {
    Write-Host "[✗] 单元测试失败" -ForegroundColor Red
    exit 1
}
Write-Host ""

# 检查Celery任务注册
Write-Host "[4/5] 检查Celery任务注册..." -ForegroundColor Cyan
docker exec $API_CONTAINER python -c "from celery import current_app; tasks = [t for t in current_app.tasks.keys() if 'recycle' in t or 'cleanup' in t]; print('注册的任务:', tasks)"
Write-Host ""

# 检查定时任务配置
Write-Host "[5/5] 检查定时任务配置..." -ForegroundColor Cyan
docker exec $API_CONTAINER python -c "
from apps.document.celery_beat_schedule import DOCUMENT_BEAT_SCHEDULE
print('定时任务配置:')
for name, config in DOCUMENT_BEAT_SCHEDULE.items():
    schedule = config.get('schedule', 'N/A')
    print(f'  - {name}: {schedule}')
"
Write-Host ""

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "    测试执行完成！" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan

# 提示手动测试命令
Write-Host ""
Write-Host "手动测试命令:" -ForegroundColor Yellow
Write-Host "  查看容器日志: docker logs -f $API_CONTAINER" -ForegroundColor Gray
Write-Host "  进入容器: docker exec -it $API_CONTAINER /bin/bash" -ForegroundColor Gray
Write-Host "  运行特定测试: docker exec $API_CONTAINER python manage.py test tests.test_recycle_bin.RecycleBinViewTest -v 2" -ForegroundColor Gray
