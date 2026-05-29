# 运行日志模块压力测试 - Windows PowerShell 脚本
# 用于快速运行 Locust 压力测试

param(
    [string]$Host = "http://localhost:80",
    [int]$Users = 50,
    [int]$SpawnRate = 10,
    [string]$Duration = "5m",
    [switch]$Interactive = $false
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  运行日志模块压力测试" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查 Locust 是否安装
Write-Host "检查 Locust 是否安装..." -ForegroundColor Yellow
try {
    $locustVersion = python -m locust --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Locust 已安装: $locustVersion" -ForegroundColor Green
    }
} catch {
    Write-Host "✗ Locust 未安装" -ForegroundColor Red
    Write-Host "请运行: python -m pip install locust" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "测试配置:" -ForegroundColor Cyan
Write-Host "  Host: $Host" -ForegroundColor White
Write-Host "  Users: $Users" -ForegroundColor White
Write-Host "  Spawn Rate: $SpawnRate" -ForegroundColor White
Write-Host "  Duration: $Duration" -ForegroundColor White
Write-Host "  Mode: $(if ($Interactive) { '交互式' } else { '命令行' })" -ForegroundColor White
Write-Host ""

# 检查服务是否可访问
Write-Host "检查服务是否可访问..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$Host/api/account/login/" -Method POST -Body '{"username":"admin","password":"test","type":"default"}' -ContentType "application/json" -TimeoutSec 5 -ErrorAction Stop
    Write-Host "✓ 服务可访问" -ForegroundColor Green
} catch {
    Write-Host "⚠ 服务访问异常，但这可能是正常的（测试会先登录）" -ForegroundColor Yellow
}

Write-Host ""

# 运行测试
Write-Host "开始压力测试..." -ForegroundColor Green
Write-Host ""

if ($Interactive) {
    # 交互式模式
    Write-Host "启动交互式模式，请在浏览器中打开 http://localhost:8089" -ForegroundColor Cyan
    Write-Host ""

    locust -f locustfile/locustfile_runlog.py -H $Host
} else {
    # 命令行模式
    Write-Host "运行命令行模式测试..." -ForegroundColor Cyan
    Write-Host ""

    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $csvPrefix = "runlog_test_$timestamp"

    locust -f locustfile/locustfile_runlog.py `
        -H $Host `
        --users $Users `
        --spawn-rate $SpawnRate `
        --run-time $Duration `
        --headless `
        --csv $csvPrefix

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "测试完成！" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "测试报告已生成:" -ForegroundColor Yellow
    Write-Host "  - $csvPrefix_stats.csv" -ForegroundColor White
    Write-Host "  - $csvPrefix_stats_history.csv" -ForegroundColor White
    Write-Host "  - $csvPrefix_failures.csv" -ForegroundColor White
    Write-Host ""
}

# 测试场景说明
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "测试场景说明" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. 高频查询 (weight=15):" -ForegroundColor White
Write-Host "   - 获取日志列表" -ForegroundColor Gray
Write-Host ""
Write-Host "2. 中频查询 (weight=8):" -ForegroundColor White
Write-Host "   - 获取事件详情" -ForegroundColor Gray
Write-Host "   - 获取统计数据 (weight=5)" -ForegroundColor Gray
Write-Host ""
Write-Host "3. 中频操作 (weight=8):" -ForegroundColor White
Write-Host "   - 添加动态" -ForegroundColor Gray
Write-Host ""
Write-Host "4. 低频操作:" -ForegroundColor White
Write-Host "   - 创建事件 (weight=3)" -ForegroundColor Gray
Write-Host "   - 更新事件 (weight=4)" -ForegroundColor Gray
Write-Host "   - 编辑动态 (weight=2)" -ForegroundColor Gray
Write-Host "   - 上传图片 (weight=3)" -ForegroundColor Gray
Write-Host ""
Write-Host "5. 极低频 (weight=1):" -ForegroundColor White
Write-Host "   - 删除事件" -ForegroundColor Gray
Write-Host "   - 删除动态 (weight=1)" -ForegroundColor Gray
Write-Host ""
Write-Host "6. 高并发测试 (weight=5):" -ForegroundColor White
Write-Host "   - 同时添加动态（测试序号计算）" -ForegroundColor Gray
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
