#!/bin/bash
# 用 --keepdb 复跑同一套测试，判断是"全新建库"路径问题还是测试代码问题
set -u
OUT=/mnt/e/TDYW/spug-3.0/quality/reports/department_duty_log/pre_release_20260901_234841
CT=tdyw-test
WD=/data/spug/spug_api
docker exec -e PYTHONIOENCODING=utf-8 -w $WD $CT python manage.py test apps.department_duty_log.tests --noinput --keepdb -v 1 2>&1 | tail -40 | tee $OUT/41_keepdb_tests.txt
echo "EXIT=${PIPESTATUS[0]}"
