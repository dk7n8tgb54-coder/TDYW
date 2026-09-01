#!/bin/bash
# 清理残留测试库（仅 test_* 库），然后用项目自带隔离 settings 重跑后端测试
# 安全约束：只操作 test_spug / test_spug_isolated，绝不触碰 spug（开发库）
set -u
OUT=/mnt/e/TDYW/spug-3.0/quality/reports/department_duty_log/pre_release_20260901_234841
CT=tdyw-test
WD=/data/spug/spug_api

echo "=== [1] 列出数据库（只读，确认不会误删） ==="
docker exec -e MYSQL_PWD=spug.cc tdyw-db-test mysql -uspug -e 'SHOW DATABASES;' 2>&1

echo
echo "=== [2] 删除残留测试库 ==="
docker exec -e MYSQL_PWD=spug.cc tdyw-db-test mysql -uspug -e 'DROP DATABASE IF EXISTS test_spug; DROP DATABASE IF EXISTS test_spug_isolated;' 2>&1
echo "DROP_EXIT=$?"

echo
echo "=== [3] 运行部门值班日志后端测试（隔离库 test_spug_isolated） ==="
docker exec -e PYTHONIOENCODING=utf-8 -w $WD $CT python manage.py test apps.department_duty_log.tests \
  --settings=spug.settings_test_isolated --noinput -v 2 2>&1 | tee $OUT/50_backend_tests.txt | tail -60
echo "EXIT=${PIPESTATUS[0]}"
