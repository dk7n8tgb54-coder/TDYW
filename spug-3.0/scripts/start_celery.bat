@echo off
REM Celery Windows 启动脚本

echo Starting Celery Worker...
start "Celery Worker" cmd /k "cd /d %~dp0\..\spug_api && celery -A spug worker -l info --concurrency=4"

echo Starting Celery Beat...
start "Celery Beat" cmd /k "cd /d %~dp0\..\spug_api && celery -A spug beat -l info"

echo Celery services started!
pause
