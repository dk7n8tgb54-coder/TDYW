# 回收站P0问题修复 - Docker环境部署脚本 (PowerShell)
# 执行数据库迁移、Celery配置和回归验证

param(
    [switch]$SkipMigration,
    [switch]$SkipRestart,
    [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"
$ContainerName = "tdyw"
$ComposeFile = "docker-compose.custom.yml"

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "回收站P0问题修复 - Docker部署脚本" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan

# 检查Docker环境
Write-Host "`n[1/6] 检查Docker环境..." -ForegroundColor Yellow
try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Docker未运行"
    }
    Write-Host "  [OK] Docker运行正常" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] Docker检查失败: $_" -ForegroundColor Red
    exit 1
}

# 检查容器状态
Write-Host "`n[2/6] 检查容器状态..." -ForegroundColor Yellow
$container = docker ps --format "{{.Names}}" | Select-String $ContainerName
if (-not $container) {
    Write-Host "  [WARNING] 容器 $ContainerName 未运行，尝试启动..." -ForegroundColor Yellow
    docker-compose -f $ComposeFile up -d
} else {
    Write-Host "  [OK] 容器 $ContainerName 运行中" -ForegroundColor Green
}

# 数据库迁移
if (-not $SkipMigration -and -not $VerifyOnly) {
    Write-Host "`n[3/6] 执行数据库迁移..." -ForegroundColor Yellow
    
    # 进入容器执行迁移
    docker exec -it $ContainerName /bin/sh -c @"
cd /data/spug/spug_api
echo "创建迁移文件..."
python manage.py makemigrations document --name add_pending_clean_fields 2>&1
echo "应用迁移..."
python manage.py migrate 2>&1
"@
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] 数据库迁移完成" -ForegroundColor Green
    } else {
        Write-Host "  [WARNING] 迁移可能有问题，请检查日志" -ForegroundColor Yellow
    }
} else {
    Write-Host "`n[3/6] 跳过数据库迁移" -ForegroundColor Gray
}

# 重启Celery服务
if (-not $SkipRestart -and -not $VerifyOnly) {
    Write-Host "`n[4/6] 重启Celery服务..." -ForegroundColor Yellow
    
    # 使用supervisor重启
    docker exec $ContainerName supervisorctl restart spug-beat spug-worker 2>&1
    
    Start-Sleep -Seconds 3
    
    # 检查状态
    $status = docker exec $ContainerName supervisorctl status spug-beat spug-worker 2>&1
    Write-Host "  服务状态:" -ForegroundColor Cyan
    $status | ForEach-Object { Write-Host "    $_" }
    
    if ($status -match "RUNNING") {
        Write-Host "  [OK] Celery服务重启成功" -ForegroundColor Green
    } else {
        Write-Host "  [WARNING] 服务状态异常" -ForegroundColor Yellow
    }
} else {
    Write-Host "`n[4/6] 跳过服务重启" -ForegroundColor Gray
}

# 验证配置
Write-Host "`n[5/6] 验证配置..." -ForegroundColor Yellow

# 检查模型字段
Write-Host "  检查模型字段..." -ForegroundColor Cyan
$fieldCheck = docker exec $ContainerName python -c @"
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()
from apps.document.models import DocumentFilePrivate, DocumentFilePublic
required = ['is_pending_clean', 'clean_retry_count', 'last_clean_attempt']
private_fields = [f.name for f in DocumentFilePrivate._meta.get_fields()]
public_fields = [f.name for f in DocumentFilePublic._meta.get_fields()]
all_ok = True
for f in required:
    if f in private_fields:
        print(f'  [OK] DocumentFilePrivate.{f}')
    else:
        print(f'  [MISSING] DocumentFilePrivate.{f}')
        all_ok = False
    if f in public_fields:
        print(f'  [OK] DocumentFilePublic.{f}')
    else:
        print(f'  [MISSING] DocumentFilePublic.{f}')
        all_ok = False
exit(0 if all_ok else 1)
"@ 2>&1

$fieldCheck | ForEach-Object { Write-Host "    $_" }

# 检查Celery任务
Write-Host "  检查Celery任务..." -ForegroundColor Cyan
$taskCheck = docker exec $ContainerName python -c @"
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()
from spug.celery import app
tasks = [t for t in app.tasks.keys() if 'cleanup' in t]
print(f'找到 {len(tasks)} 个清理任务:')
for t in tasks:
    print(f'  - {t}')
required = [
    'apps.document.tasks.cleanup.retry_clean_pending_files',
    'apps.document.tasks.cleanup.cleanup_soft_deleted_files',
    'apps.document.tasks.cleanup.async_batch_permanent_delete'
]
all_ok = True
for t in required:
    if t in tasks:
        print(f'  [OK] {t}')
    else:
        print(f'  [MISSING] {t}')
        all_ok = False
exit(0 if all_ok else 1)
"@ 2>&1

$taskCheck | ForEach-Object { Write-Host "    $_" }

# 检查定时任务配置
Write-Host "  检查定时任务配置..." -ForegroundColor Cyan
$beatCheck = docker exec $ContainerName python -c @"
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()
from django.conf import settings
schedule = settings.CELERY_BEAT_SCHEDULE
if 'retry-clean-pending-files' in schedule:
    print(f'  [OK] 定时任务已配置')
    print(f'       任务: {schedule[\"retry-clean-pending-files\"][\"task\"]}')
    print(f'       间隔: {schedule[\"retry-clean-pending-files\"][\"schedule\"]}秒')
else:
    print('  [MISSING] 定时任务未配置')
    exit(1)
"@ 2>&1

$beatCheck | ForEach-Object { Write-Host "    $_" }

# 代码修复验证
Write-Host "`n[6/6] 验证代码修复..." -ForegroundColor Yellow

$fixes = @(
    @{
        Name = "P0-1 硬删除权限检查"
        Pattern = "只有管理员可以彻底删除文件"
        File = "/data/spug/spug_api/apps/document/views/recycle_bin.py"
    },
    @{
        Name = "P0-2 分页ID冲突修复"
        Pattern = "_space_type"
        File = "/data/spug/spug_api/apps/document/views/recycle_bin.py"
    },
    @{
        Name = "P0-4 并发恢复行锁"
        Pattern = "select_for_update"
        File = "/data/spug/spug_api/apps/document/views/recycle_bin.py"
    },
    @{
        Name = "P0-5 用户状态校验"
        Pattern = "user.is_active"
        File = "/data/spug/spug_api/apps/document/tasks/cleanup.py"
    },
    @{
        Name = "P0-6 物理删除兜底"
        Pattern = "is_pending_clean"
        File = "/data/spug/spug_api/apps/document/models.py"
    },
    @{
        Name = "P0-7 清理任务重试"
        Pattern = "retry_clean_pending_files"
        File = "/data/spug/spug_api/apps/document/tasks/cleanup.py"
    }
)

foreach ($fix in $fixes) {
    $result = docker exec $ContainerName grep -n $fix.Pattern $fix.File 2>&1
    if ($result) {
        Write-Host "  [OK] $($fix.Name)" -ForegroundColor Green
    } else {
        Write-Host "  [MISSING] $($fix.Name)" -ForegroundColor Red
    }
}

Write-Host "`n======================================" -ForegroundColor Cyan
Write-Host "部署验证完成" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "`n后续操作:" -ForegroundColor Yellow
Write-Host "  1. 查看日志: docker logs $ContainerName -f | Select-String 'cleanup|pending|recycle'" -ForegroundColor Gray
Write-Host "  2. 手动触发清理任务: docker exec $ContainerName python -c 'from apps.document.tasks.cleanup import retry_clean_pending_files; retry_clean_pending_files.delay()'" -ForegroundColor Gray
Write-Host "  3. 检查数据库字段: docker exec tdyw-db mysql -uroot -p -e 'USE spug; SHOW COLUMNS FROM spug_document_file_private LIKE \"%pending%\";'" -ForegroundColor Gray
