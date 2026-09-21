#!/bin/bash
# 红-绿验证：逐个应用目标变异体 -> 跑对应新测试（期望 FAILED）-> 还原三个目标源文件
# 注意：只还原 models/views/tasks.py 三个被变异文件，绝不碰 tests/ 的未提交修改
cd /mnt/e/TDYW/spug-3.0 || exit 1
M=~/.local/bin/mutmut
SRC="spug_api/apps/contract_agreement/models.py spug_api/apps/contract_agreement/views.py spug_api/apps/contract_agreement/tasks.py"

run_one() {
  local id="$1" label="$2"
  $M apply "$id" || { echo "MUTANT $id APPLY_FAILED"; return; }
  local out
  out=$(docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test sh -c "python manage.py test $label --keepdb --parallel 1" 2>&1 | tail -4)
  if echo "$out" | grep -qE '^OK'; then
    echo "MUTANT $id -> NOT_KILLED(测试在变异下仍绿!)"
  else
    echo "MUTANT $id -> KILLED"
    echo "$out" | grep -E '^(FAIL|ERROR)' | head -2
  fi
  git checkout -- $SRC
}

run_one 407 "apps.contract_agreement.tests.stable_contract.test_permission_tenant.NoPermissionTest.test_create_denied_by_auth_decorator_exact_message"
run_one 612 "apps.contract_agreement.tests.stable_contract.test_permission_tenant.NoPermissionTest.test_preview_url_denied_exact_message"
run_one 252 "apps.contract_agreement.tests.stable_contract.test_attachments.AttachmentAccessTest.test_same_module_wrong_object_type_rejected"
run_one 437 "apps.contract_agreement.tests.stable_contract.test_crud.DetailAndEditTest.test_edit_overlong_fields_rejected"
run_one 486 "apps.contract_agreement.tests.stable_contract.test_crud.DetailAndEditTest.test_edit_validates_responsible_user"
run_one 453 "apps.contract_agreement.tests.stable_contract.test_crud.DetailAndEditTest.test_edit_allows_equal_start_and_end_dates"
run_one 654 "apps.contract_agreement.tests.stable_contract.test_status_reminder.ReminderPopupTest.test_ack_skips_only_acked_and_keeps_remaining_records"
run_one 652 "apps.contract_agreement.tests.stable_contract.test_status_reminder.ReminderPopupTest.test_ack_skips_only_acked_and_keeps_remaining_records"
run_one 690 "apps.contract_agreement.tests.stable_contract.test_status_reminder.ReminderPopupTest.test_ack_normal_contract_refused"
run_one 739 "apps.contract_agreement.tests.stable_contract.test_status_reminder.StatusCalculationTest.test_scan_single_respects_explicit_today"
echo "VERIFY_DONE"
git status --porcelain -- spug_api/apps/contract_agreement/
