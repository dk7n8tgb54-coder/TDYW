#!/bin/bash
# [1] 对照实验：默认 test_spug 库（已 DROP 重建后）是否仍失败
# [2] 导出现有测试清单，用于覆盖面差距分析
set -u
OUT=/mnt/e/TDYW/spug-3.0/quality/reports/department_duty_log/pre_release_20260901_234841
CT=tdyw-test
WD=/data/spug/spug_api

echo "=== [1] 对照：默认 test_spug 库 ==="
docker exec -e PYTHONIOENCODING=utf-8 -w $WD $CT python manage.py test apps.department_duty_log.tests --noinput -v 0 2>&1 | tail -8 | tee $OUT/51_control_test_spug.txt
echo "CTRL_EXIT=${PIPESTATUS[0]}"

echo
echo "=== [2] 现有测试用例清单 ==="
docker exec -e PYTHONIOENCODING=utf-8 -w $WD $CT python manage.py test apps.department_duty_log.tests \
  --settings=spug.settings_test_isolated --noinput -v 2 --keepdb 2>&1 \
  | grep -oE '^test_[a-zA-Z0-9_]+ \(apps\.department_duty_log[^)]*\)' \
  | sort -u > $OUT/52_existing_test_inventory.txt
wc -l < $OUT/52_existing_test_inventory.txt
