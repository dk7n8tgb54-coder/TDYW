#!/bin/bash
# 前端测试文件行尾转 LF
set -u
for f in \
  /mnt/e/TDYW/spug-3.0/spug_web/src/pages/departmentDutyLog/__tests__/release_gate.test.js \
  /mnt/e/TDYW/spug-3.0/spug_web/src/pages/departmentDutyLog/__tests__/defect_reproduction.test.js ; do
  before=$(grep -c $'\r' "$f" 2>/dev/null || true)
  sed -i "s/\r$//" "$f"
  after=$(grep -c $'\r' "$f" 2>/dev/null || true)
  echo "$(basename $f): CRLF_before=${before:-0} CRLF_after=${after:-0}"
done
