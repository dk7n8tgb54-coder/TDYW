# Docker Volume 迁移脚本
# 从分立 volumes 迁移到统一 spug-data volume
# 仅在已创建旧 volumes 的情况下使用

Write-Host "=== Docker Volume 迁移脚本 ===" -ForegroundColor Cyan
Write-Host ""

# 检查是否需要迁移
$needMigration = $false

$volumesToCheck = @(
    "spug-3.0_frontend-data",
    "spug-3.0_backend-data",
    "spug-3.0_repos-data",
    "spug-3.0_document-files"
)

Write-Host "检查现有 volumes..." -ForegroundColor Yellow
foreach ($vol in $volumesToCheck) {
    $exists = docker volume ls -q -f name=$vol
    if ($exists) {
        Write-Host "  ✓ 找到: $vol" -ForegroundColor Green
        $needMigration = $true
    } else {
        Write-Host "  - 未找到: $vol" -ForegroundColor Gray
    }
}

if (-not $needMigration) {
    Write-Host ""
    Write-Host "未找到需要迁移的 volumes，无需执行迁移。" -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "是否执行迁移？" -ForegroundColor Yellow
$confirm = Read-Host "输入 'yes' 继续，其他键取消"

if ($confirm -ne 'yes') {
    Write-Host "已取消迁移。" -ForegroundColor Red
    exit 0
}

Write-Host ""
Write-Host "开始迁移..." -ForegroundColor Cyan

# 创建目标 volume
Write-Host "  创建 spug-data volume..." -ForegroundColor Yellow
$exists = docker volume ls -q -f name=spug-3.0_spug-data
if (-not $exists) {
    docker volume create spug-3.0_spug-data
    Write-Host "  ✓ spug-data 创建成功" -ForegroundColor Green
} else {
    Write-Host "  ! spug-data 已存在" -ForegroundColor Yellow
}

# 启动临时容器进行迁移
Write-Host "  启动迁移容器..." -ForegroundColor Yellow

$mountArgs = ""
if (docker volume ls -q -f name=spug-3.0_frontend-data) { $mountArgs += "-v spug-3.0_frontend-data:/from/frontend " }
if (docker volume ls -q -f name=spug-3.0_backend-data) { $mountArgs += "-v spug-3.0_backend-data:/from/backend " }
if (docker volume ls -q -f name=spug-3.0_repos-data) { $mountArgs += "-v spug-3.0_repos-data:/from/repos " }
if (docker volume ls -q -f name=spug-3.0_document-files) { $mountArgs += "-v spug-3.0_document-files:/from/documents " }
$mountArgs += "-v spug-3.0_spug-data:/to alpine"

docker run --rm $mountArgs sh -c "
    echo '迁移前端数据...'
    if [ -d /from/frontend ]; then
        mkdir -p /to/spug_web
        cp -a /from/frontend /to/spug_web/build
        echo '✓ 前端数据迁移完成'
    fi

    echo '迁移后端数据...'
    if [ -d /from/backend ]; then
        mkdir -p /to/spug_api
        cp -a /from/backend /to/spug_api
        echo '✓ 后端数据迁移完成'
    fi

    echo '迁移代码仓库...'
    if [ -d /from/repos ]; then
        mkdir -p /to
        cp -a /from/repos /to/
        echo '✓ 代码仓库迁移完成'
    fi

    echo '迁移文档文件...'
    if [ -d /from/documents ]; then
        mkdir -p /to/spug_api/storage
        cp -a /from/documents /to/spug_api/storage/
        echo '✓ 文档文件迁移完成'
    fi

    echo '迁移完成！'
    ls -la /to/
"

Write-Host ""
Write-Host "=== 迁移完成 ===" -ForegroundColor Green
Write-Host ""
Write-Host "下一步：" -ForegroundColor Yellow
Write-Host "1. 备份旧 volumes（可选）：" -ForegroundColor White
Write-Host "   docker volume create spug-3.0_backup-$(Get-Date -Format 'yyyyMMdd')" -ForegroundColor Gray
Write-Host ""
Write-Host "2. 删除旧 volumes（确认备份后）：" -ForegroundColor White
Write-Host "   docker volume rm spug-3.0_frontend-data" -ForegroundColor Gray
Write-Host "   docker volume rm spug-3.0_backend-data" -ForegroundColor Gray
Write-Host "   docker volume rm spug-3.0_repos-data" -ForegroundColor Gray
Write-Host "   docker volume rm spug-3.0_document-files" -ForegroundColor Gray
