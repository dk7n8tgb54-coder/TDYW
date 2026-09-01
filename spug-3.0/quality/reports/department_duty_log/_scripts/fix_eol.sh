#!/bin/bash
# 将本次新增/修改的源码文件统一为 LF 行尾，并删除临时诊断脚本
set -u
WD=/data/spug/spug_api
CT=tdyw-test

echo "=== 删除临时诊断脚本 ==="
rm -f /mnt/e/TDYW/spug-3.0/spug_api/apps/department_duty_log/_env_probe.py
rm -f /mnt/e/TDYW/spug-3.0/spug_api/apps/department_duty_log/_repro.py
docker exec $CT rm -f $WD/apps/department_duty_log/_env_probe.py $WD/apps/department_duty_log/_repro.py

echo "=== CRLF -> LF ==="
for f in \
  apps/department_duty_log/tests/release_gate/__init__.py \
  apps/department_duty_log/tests/release_gate/test_release_gate.py ; do
  before=$(docker exec $CT grep -c $'\r' $WD/$f 2>/dev/null || true)
  docker exec $CT sed -i "s/\r$//" $WD/$f
  after=$(docker exec $CT grep -c $'\r' $WD/$f 2>/dev/null || true)
  echo "$f : CRLF_lines_before=${before:-0} CRLF_lines_after=${after:-0}"
done

echo "=== 复检（0 表示全部 LF） ==="
docker exec $CT grep -c $'\r' $WD/apps/department_duty_log/tests/release_gate/test_release_gate.py || echo "test_release_gate.py: clean (LF)"
docker exec $CT grep -c $'\r' $WD/apps/department_duty_log/tests/release_gate/__init__.py || echo "__init__.py: clean (LF)"
