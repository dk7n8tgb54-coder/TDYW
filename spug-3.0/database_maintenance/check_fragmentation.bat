@echo off

REM 检查数据库碎片情况
mysql -h 127.0.0.1 -P 3306 -u spug -pspug.cc -e "SELECT table_schema, table_name, data_free, engine FROM information_schema.tables WHERE table_schema = 'spug' AND data_free > 0 ORDER BY data_free DESC"

echo.
echo 所有表状态：
mysql -h 127.0.0.1 -P 3306 -u spug -pspug.cc -e "SELECT table_name, table_rows, data_length, index_length, data_length + index_length as total_size FROM information_schema.tables WHERE table_schema = 'spug' ORDER BY total_size DESC"

echo.
echo 按任意键退出...
pause > nul
