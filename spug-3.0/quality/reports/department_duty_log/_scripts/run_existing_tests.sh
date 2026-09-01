#!/bin/bash
# 运行部门值班日志现有后端测试套件（隔离测试容器 tdyw-test）
# 输出重定向到报告目录，避免 Windows 控制台中文乱码
set -u
OUT=/mnt/e/TDYW/spug-3.0/quality/reports/department_duty_log/pre_release_20260901_234841
TS=20260901_234841
CT=tdyw-test
WD=/data/spug/spug_api

echo "=== [1] Django check ==="
docker exec -e PYTHONIOENCODING=utf-8 -w $WD $CT python manage.py check 2>&1 | tee $OUT/10_django_check.txt

echo "=== [2] 模块级测试 discovery ==="
docker exec -e PYTHONIOENCODING=utf-8 -w $WD $CT python manage.py test apps.department_duty_log.tests --noinput -v 2 2>&1 | tee $OUT/20_backend_existing_tests.txt
echo "EXIT=${PIPESTATUS[0]}"
