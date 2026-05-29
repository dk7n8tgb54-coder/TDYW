# 运行日志500错误快速修复脚本
# 用途：自动执行数据库迁移，修复运行日志模块500错误

Write-Host "=================================================="
Write-Host "  运行日志500错误快速修复"
Write-Host "=================================================="
Write-Host ""

# 检查是否在正确的目录
if (-not (Test-Path "spug_api\manage.py")) {
    Write-Host "❌ 错误：请在项目根目录（包含spug_api文件夹）运行此脚本" -ForegroundColor Red
    exit 1
}

# 进入spug_api目录
cd spug_api
Write-Host "✅ 当前目录: $PWD" -ForegroundColor Green
Write-Host ""

# 检查虚拟环境是否存在
if (-not (Test-Path "venv\Scripts\python.exe")) {
    Write-Host "❌ 错误：虚拟环境不存在" -ForegroundColor Red
    Write-Host "正在创建虚拟环境..."
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ 虚拟环境创建失败" -ForegroundColor Red
        exit 1
    }
    Write-Host "✅ 虚拟环境创建成功" -ForegroundColor Green
}

# 激活虚拟环境
Write-Host "✅ 激活虚拟环境..."
.\venv\Scripts\activate

# 检查Django是否已安装
Write-Host ""
Write-Host "检查Django安装..."
python -c "import django; print('Django版本:', django.get_version())" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Django未安装，正在安装..."
    pip install Django==2.2.28 djangorestframework
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Django安装失败" -ForegroundColor Red
        exit 1
    }
    Write-Host "✅ Django安装成功" -ForegroundColor Green
} else {
    Write-Host "✅ Django已安装" -ForegroundColor Green
}

# 检查数据库连接
Write-Host ""
Write-Host "检查数据库连接..."
python -c "from django.conf import settings; from django.db import connection; connection.ensure_connection(); print('✅ 数据库连接成功')" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ 数据库连接失败" -ForegroundColor Red
    Write-Host "请检查以下配置："
    Write-Host "  1. MySQL服务是否启动"
    Write-Host "  2. .env文件配置是否正确"
    Write-Host "  3. 数据库用户名密码是否正确"
    exit 1
}

# 运行Django检查
Write-Host ""
Write-Host "运行Django系统检查..."
python manage.py check
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️  Django检查发现问题，但继续执行迁移..." -ForegroundColor Yellow
}

# 查看待执行的迁移
Write-Host ""
Write-Host "查看运行日志模块迁移状态..."
python manage.py showmigrations runlog
Write-Host ""

# 运行迁移
Write-Host "=================================================="
Write-Host "  执行数据库迁移"
Write-Host "=================================================="
Write-Host ""

python manage.py migrate runlog
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ 运行日志模块迁移失败" -ForegroundColor Red
    Write-Host ""
    Write-Host "尝试执行所有迁移..."
    python manage.py migrate
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ 迁移失败" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "✅ 迁移执行成功" -ForegroundColor Green
Write-Host ""

# 验证表是否创建成功
Write-Host "验证表是否创建成功..."
python -c "
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute(\"\"\"
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
        AND table_name = 'runlog'
    \"\"\")
    count = cursor.fetchone()[0]
    if count > 0:
        print('✅ runlog表已创建')
    else:
        print('❌ runlog表未创建')
        exit(1)
    
    cursor.execute(\"\"\"
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
        AND table_name = 'runlog_update'
    \"\"\")
    count = cursor.fetchone()[0]
    if count > 0:
        print('✅ runlog_update表已创建')
    else:
        print('❌ runlog_update表未创建')
        exit(1)
"

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "=================================================="
    Write-Host "  ✅ 修复完成！"
    Write-Host "=================================================="
    Write-Host ""
    Write-Host "下一步操作："
    Write-Host "  1. 重启Django服务"
    Write-Host "  2. 访问运行日志页面验证"
    Write-Host "  3. 如果仍有问题，查看后端日志"
    Write-Host ""
    Write-Host "查看日志："
    Write-Host "  Get-Content logs\spug.log -Tail 50"
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "❌ 修复失败" -ForegroundColor Red
    Write-Host ""
    Write-Host "请手动检查："
    Write-Host "  1. 数据库连接配置"
    Write-Host "  2. 运行日志模块代码"
    Write-Host "  3. MySQL错误日志"
    Write-Host ""
    exit 1
}
