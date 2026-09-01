#!/bin/bash
# 诊断：统计错误类型与前 3 个错误的完整上下文
set -u
OUT=/mnt/e/TDYW/spug-3.0/quality/reports/department_duty_log/pre_release_20260901_234841
F=$OUT/20_backend_existing_tests.txt

echo "=== ERROR/FAIL 汇总 ==="
grep -oE '^(ERROR|FAIL): [^ ]+' $F | sed 's/(\(.*\))//' | sort | uniq -c | sort -rn | head -40
echo
echo "=== 异常类型统计 ==="
grep -oE '^[A-Za-z_.]+(Error|Exception|Warning): ' $F | sort | uniq -c | sort -rn | head -20
echo
echo "=== 第一个错误上下文 ==="
awk '/^(ERROR|FAIL): /{n++} n<=1' $F | head -60
echo
echo "=== 涉及 deleted_by_id 的行 ==="
grep -n 'deleted_by_id' $F | head -10
