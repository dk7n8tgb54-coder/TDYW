#!/bin/bash
# 合同协议模块上线前测试 - 数据库只读检查（sql_mode / 列定义）
set -u
BASE=/mnt/e/TDYW/spug-3.0/quality/reports/contract_agreement
docker cp "$BASE/scripts/check_db_mode.py" tdyw-test:/tmp/check_db_mode.py
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python /tmp/check_db_mode.py
