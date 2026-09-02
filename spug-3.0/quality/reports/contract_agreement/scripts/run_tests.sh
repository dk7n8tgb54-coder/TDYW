#!/bin/bash
# 合同协议模块上线前测试 - 后端测试执行器
# 用法： wsl bash /mnt/e/TDYW/spug-3.0/quality/reports/contract_agreement/scripts/run_tests.sh [模块名...]
# 未指定模块名时执行合同协议全部测试（稳定契约 + 现有冒烟测试）
#
# 产物：
#   quality/reports/contract_agreement/logs/backend_tests_<时间戳>.log  完整执行日志
set -u
BASE=/mnt/e/TDYW/spug-3.0/quality/reports/contract_agreement
SCRIPTS="$BASE/scripts"
LOGS="$BASE/logs"
CONTAINER=tdyw-test
WORKDIR=/data/spug/spug_api
STAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$LOGS"

docker cp "$SCRIPTS/contract_qa_runner.py" "$CONTAINER":/tmp/contract_qa_runner.py

if [ "$#" -gt 0 ]; then
  printf '%s\n' "$@" > /tmp/contract_qa_modules.txt
else
  cat > /tmp/contract_qa_modules.txt <<'EOF'
apps.contract_agreement.tests.stable_contract.test_list_query
apps.contract_agreement.tests.stable_contract.test_crud
apps.contract_agreement.tests.stable_contract.test_status_reminder
apps.contract_agreement.tests.stable_contract.test_permission_tenant
apps.contract_agreement.tests.stable_contract.test_attachments
apps.contract_agreement.tests.stable_contract.test_audit_async
apps.contract_agreement.tests.test_smoke
EOF
fi
docker cp /tmp/contract_qa_modules.txt "$CONTAINER":/tmp/contract_qa_modules.txt

docker cp "$CONTAINER":/tmp/contract_qa_modules.txt /dev/null 2>/dev/null
docker exec -e PYTHONIOENCODING=utf-8 -w "$WORKDIR" "$CONTAINER" \
  python /tmp/contract_qa_runner.py /tmp/contract_qa_modules.txt > /tmp/contract_qa_out.log 2>&1
EXIT_CODE=$?

cp /tmp/contract_qa_out.log "$LOGS/backend_tests_$STAMP.log"

echo "===== 摘要 ====="
grep -E "^test_|^Ran |^OK$|^FAILED|^FAIL: |^ERROR: " "$LOGS/backend_tests_$STAMP.log"
echo "===== 失败明细 ====="
sed -n '/^======*$/,/^Ran /p' "$LOGS/backend_tests_$STAMP.log" | head -200
echo "---- 完整日志: logs/backend_tests_$STAMP.log (exit=$EXIT_CODE) ----"
exit $EXIT_CODE
