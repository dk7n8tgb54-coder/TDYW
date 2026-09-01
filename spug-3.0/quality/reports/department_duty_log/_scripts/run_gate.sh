#!/bin/bash
# 运行发布门禁补充测试（隔离库 test_spug_isolated）
set -u
OUT=/mnt/e/TDYW/spug-3.0/quality/reports/department_duty_log/pre_release_20260901_234841
CT=tdyw-test
WD=/data/spug/spug_api

echo "=== 行尾检查（必须无 CRLF） ==="
FILE=$WD/apps/department_duty_log/tests/release_gate/test_release_gate.py
docker exec $CT grep -c $'\r' $FILE 2>/dev/null || echo "no CRLF (grep exit 1 = clean)"

echo
echo "=== py_compile ==="
docker exec -e PYTHONIOENCODING=utf-8 -w $WD $CT python -m py_compile $FILE
echo "COMPILE_EXIT=$?"

echo
echo "=== 运行发布门禁测试 ==="
docker exec -e PYTHONIOENCODING=utf-8 -w $WD $CT python manage.py test \
  apps.department_duty_log.tests.release_gate.test_release_gate \
  --settings=spug.settings_test_isolated --noinput -v 2 2>&1 | tee $OUT/60_release_gate_tests.txt | tail -80
echo "EXIT=${PIPESTATUS[0]}"
