#!/bin/bash
# 最终验证：E2E 测试数据残留检查 + 后端全量回归（隔离库）
set -u
OUT=/mnt/e/TDYW/spug-3.0/quality/reports/department_duty_log/pre_release_20260901_234841
CT=tdyw-test
WD=/data/spug/spug_api

echo "=== [1] E2E 测试数据残留检查（应只有既有 8 条业务数据，无 E2E_DDL_RG_） ==="
docker exec -e MYSQL_PWD=spug.cc tdyw-db-test mysql -uspug -N -e \
  "SELECT CONCAT('total=', COUNT(*)) FROM spug.tdyw_department_duty_log; \
   SELECT CONCAT('e2e_leftover=', COUNT(*)) FROM spug.tdyw_department_duty_log WHERE duty_record LIKE 'E2E_DDL_RG_%'; \
   SELECT CONCAT('deleted=', COUNT(*)) FROM spug.tdyw_department_duty_log WHERE deleted_at IS NOT NULL;"

echo
echo "=== [2] 后端全量回归（既有 + 发布门禁，隔离库） ==="
docker exec -e PYTHONIOENCODING=utf-8 -w $WD $CT python manage.py test apps.department_duty_log.tests \
  --settings=spug.settings_test_isolated --noinput -v 0 2>&1 | tail -6 | tee $OUT/90_final_backend_regression.txt
echo "EXIT=${PIPESTATUS[0]}"

echo
echo "=== [3] 临时诊断脚本清理复核 ==="
docker exec $CT ls $WD/apps/department_duty_log/ | grep -E '^_' || echo "无临时脚本残留"
