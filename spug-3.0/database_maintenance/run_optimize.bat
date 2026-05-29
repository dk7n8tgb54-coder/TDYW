@echo off

REM 执行数据库优化
mysql -h 127.0.0.1 -P 3306 -u spug -pspug.cc < check_and_optimize.sql

echo.
echo 优化操作完成！
echo.
echo 按任意键退出...
pause > nul
