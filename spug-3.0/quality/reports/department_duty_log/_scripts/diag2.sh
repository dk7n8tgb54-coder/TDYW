#!/bin/bash
# 诊断 deleted_by_id NOT NULL 问题：模型/迁移漂移 + 实际列定义
set -u
OUT=/mnt/e/TDYW/spug-3.0/quality/reports/department_duty_log/pre_release_20260901_234841
CT=tdyw-test
WD=/data/spug/spug_api

echo "=== [1] makemigrations --check (全 app 漂移检测，只读) ==="
docker exec -e PYTHONIOENCODING=utf-8 -w $WD $CT python manage.py makemigrations --check --dry-run -v 2 2>&1 | tee $OUT/30_migration_drift.txt
echo "EXIT=${PIPESTATUS[0]}"

echo
echo "=== [2] 实际列定义（spug 库，只读） ==="
docker exec -i -e PYTHONIOENCODING=utf-8 -w $WD $CT python manage.py shell -c "
from django.db import connection
with connection.cursor() as c:
    c.execute(\"SELECT TABLE_NAME, COLUMN_NAME, IS_NULLABLE, COLUMN_TYPE, COLUMN_DEFAULT FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='spug' AND COLUMN_NAME LIKE '%deleted_by%' ORDER BY TABLE_NAME\")
    for r in c.fetchall():
        print(r)
" 2>&1 | tail -40
