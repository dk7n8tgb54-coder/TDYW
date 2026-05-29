@echo off
chcp 65001
echo ========================================
echo 多租户数据隔离部署脚本
echo ========================================
echo.

echo [1/3] 检查Python环境...
python --version
if errorlevel 1 (
    echo 错误: 未找到Python,请先安装Python
    pause
    exit /b 1
)
echo Python环境检查通过
echo.

echo [2/3] 执行租户数据初始化...
python init_tenant_data.py
if errorlevel 1 (
    echo 错误: 数据初始化失败
    pause
    exit /b 1
)
echo 数据初始化完成
echo.

echo [3/3] 重启Docker容器...
docker restart spug
if errorlevel 1 (
    echo 警告: Docker容器重启失败,请手动重启
    echo 命令: docker restart spug
) else (
    echo Docker容器重启成功
)
echo.

echo ========================================
echo 多租户数据隔离部署完成!
echo ========================================
echo.
echo 验证步骤:
echo 1. 使用admin账号登录,应能看到所有数据
echo 2. 使用普通账号登录,只能看到自己租户的数据
echo 3. 测试新增数据,确认自动分配租户
echo.
pause
