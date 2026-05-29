@echo off
chcp 65001 >nul
echo ======================================
echo 回收站P0问题修复 - Docker部署脚本
echo ======================================

set CONTAINER_NAME=tdyw
set COMPOSE_FILE=docker-compose.custom.yml

echo.
echo [1/5] 检查Docker环境...
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker未运行
    exit /b 1
)
echo [OK] Docker运行正常

echo.
echo [2/5] 检查容器状态...
docker ps --format "{{.Names}}" | findstr /C:"%CONTAINER_NAME%" >nul
if errorlevel 1 (
    echo [WARNING] 容器 %CONTAINER_NAME% 未运行，尝试启动...
    docker-compose -f %COMPOSE_FILE% up -d
) else (
    echo [OK] 容器 %CONTAINER_NAME% 运行中
)

echo.
echo [3/5] 执行数据库迁移...
echo 进入容器执行迁移...
docker exec %CONTAINER_NAME% /bin/sh -c "cd /data/spug/spug_api && python manage.py migrate"
if errorlevel 1 (
    echo [WARNING] 迁移可能有问题
) else (
    echo [OK] 数据库迁移完成
)

echo.
echo [4/5] 重启Celery服务...
docker exec %CONTAINER_NAME% supervisorctl restart spug-beat spug-worker
timeout /t 3 /nobreak >nul
docker exec %CONTAINER_NAME% supervisorctl status spug-beat spug-worker

echo.
echo [5/5] 验证配置...
echo 检查Celery任务...
docker exec %CONTAINER_NAME% python -c "from spug.celery import app; tasks = [t for t in app.tasks.keys() if 'cleanup' in t]; print('清理任务:', len(tasks)); [print(' -', t) for t in tasks]"

echo.
echo 检查定时任务配置...
docker exec %CONTAINER_NAME% python -c "from django.conf import settings; s = settings.CELERY_BEAT_SCHEDULE; print('retry-clean-pending-files:', '已配置' if 'retry-clean-pending-files' in s else '未配置')"

echo.
echo ======================================
echo 部署完成
echo ======================================
echo.
echo 后续操作:
echo   查看日志: docker logs %CONTAINER_NAME% -f
echo   检查数据库: docker exec tdyw-db mysql -uroot -p -e "USE spug; SHOW COLUMNS FROM spug_document_file_private LIKE '%%pending%%';"
pause
