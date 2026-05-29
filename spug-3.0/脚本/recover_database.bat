@echo off
echo 等待数据库启动...
for /l %%i in (1,1,60) do (
    docker exec spug-db mysqladmin ping -h localhost -uroot -pSpug@888 >nul 2>&1
    if !errorlevel! equ 0 (
        echo 数据库已启动
        goto :restore
    )
    echo 等待中... %%i/60
    timeout /t 5 >nul
)

echo 数据库启动超时
exit /b 1

:restore
echo 开始恢复数据库...
docker cp e:/TDYW/spug-3.0/backups/spug_backup_20260227_140639.sql spug-db:/tmp/spug_backup.sql
docker exec spug-db mysql -uroot -pSpug@888 spug < /tmp/spug_backup.sql
echo 数据库恢复完成
