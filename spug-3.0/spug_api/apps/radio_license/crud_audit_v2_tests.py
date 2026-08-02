"""
无线电台执照 + 台站频率批复 CRUD 可靠性深度审计 v2

本轮聚焦"影响运行稳定"的深层风险：

  批复（StationFrequencyApproval）- 修复后验证：
    R-AP-1 (FIXED): create 的 scan+audit 已移入事务内
    R-AP-2 (FIXED): edit 的 scan+audit 已移入事务内
    R-AP-3 (FIXED): delete 的 audit 已移入事务内
    R-AP-4 (FIXED): ack 的 audit 已移入事务内

  执照（RadioLicense）- 对照基线：
    R-RL-1 (PASS): create 的 scan+audit 在事务内
    R-RL-2 (PASS): edit 的 scan+audit 在事务内
    R-RL-3 (PASS): delete 的 audit 在事务内

运行方式:
  docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
    python manage.py test apps.radio_license.crud_audit_v2_tests \
    --keepdb --noinput -v2
"""

import inspect

from django.test import SimpleTestCase

from apps.radio_license import views as license_views
from apps.radio_license import approval_views


def _is_inside_atomic(src, func_name):
    """判断 func_name 是否在 transaction.atomic() 块内调用。"""
    lines = src.split('\n')
    atomic_indent = None
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if 'with transaction.atomic' in line:
            atomic_indent = indent
            continue

        if atomic_indent is not None and func_name in line and not stripped.startswith('#'):
            return indent > atomic_indent

        if atomic_indent is not None and stripped and indent <= atomic_indent:
            atomic_indent = None

    return False


# ============================================================
# 批复模块修复验证
# ============================================================

class ApprovalFixVerificationTests(SimpleTestCase):
    """台站频率批复模块修复验证：scan+audit 均在事务内"""

    # ---------- R-AP-1: create scan+audit 已移入事务内 ----------

    def test_R_AP_1_create_scan_inside_transaction(self):
        """R-AP-1 (FIXED): create 的 scan_single_approval 已在事务内"""
        src = inspect.getsource(approval_views.StationFrequencyApprovalView._handle_create)
        self.assertTrue(
            _is_inside_atomic(src, 'scan_single_approval'),
            'scan_single_approval 应在事务内（已修复）'
        )

    def test_R_AP_1_create_audit_inside_transaction(self):
        """R-AP-1 (FIXED): create 的 _record_approval_audit 已在事务内"""
        src = inspect.getsource(approval_views.StationFrequencyApprovalView._handle_create)
        self.assertTrue(
            _is_inside_atomic(src, '_record_approval_audit'),
            '_record_approval_audit 应在事务内（已修复）'
        )

    # ---------- R-AP-2: edit scan+audit 已移入事务内 ----------

    def test_R_AP_2_edit_scan_inside_transaction(self):
        """R-AP-2 (FIXED): edit 的 scan_single_approval 已在事务内"""
        src = inspect.getsource(approval_views.StationFrequencyApprovalView._handle_edit)
        self.assertTrue(
            _is_inside_atomic(src, 'scan_single_approval'),
            'edit 的 scan_single_approval 应在事务内（已修复）'
        )

    def test_R_AP_2_edit_audit_inside_transaction(self):
        """R-AP-2 (FIXED): edit 的 _record_approval_audit 已在事务内"""
        src = inspect.getsource(approval_views.StationFrequencyApprovalView._handle_edit)
        self.assertTrue(
            _is_inside_atomic(src, '_record_approval_audit'),
            'edit 的 _record_approval_audit 应在事务内（已修复）'
        )

    # ---------- R-AP-3: delete audit 已移入事务内 ----------

    def test_R_AP_3_delete_audit_inside_transaction(self):
        """R-AP-3 (FIXED): delete 的 _record_approval_audit 已在事务内"""
        src = inspect.getsource(approval_views.StationFrequencyApprovalView.delete)
        self.assertTrue(
            _is_inside_atomic(src, '_record_approval_audit'),
            'delete 的 _record_approval_audit 应在事务内（已修复）'
        )

    def test_R_AP_3_delete_soft_delete_inside_transaction(self):
        """R-AP-3: delete 的 soft_delete 在事务内"""
        src = inspect.getsource(approval_views.StationFrequencyApprovalView.delete)
        self.assertTrue(
            _is_inside_atomic(src, 'soft_delete_by_object'),
            'delete 的 soft_delete_by_object 应在事务内'
        )

    def test_R_AP_3_delete_obj_inside_transaction(self):
        """R-AP-3: delete 的 approval.delete() 在事务内"""
        src = inspect.getsource(approval_views.StationFrequencyApprovalView.delete)
        self.assertTrue(
            _is_inside_atomic(src, 'approval.delete'),
            'delete 的 approval.delete() 应在事务内'
        )

    # ---------- R-AP-4: ack audit 已移入事务内 ----------

    def test_R_AP_4_ack_audit_inside_transaction(self):
        """R-AP-4 (FIXED): ack 的 _record_approval_audit 已在事务内"""
        src = inspect.getsource(approval_views.ApprovalReminderAckView.post)
        self.assertTrue(
            _is_inside_atomic(src, '_record_approval_audit'),
            'ack 的 _record_approval_audit 应在事务内（已修复）'
        )

    def test_R_AP_4_ack_create_inside_transaction(self):
        """R-AP-4: ack 的 get_or_create 在事务内"""
        src = inspect.getsource(approval_views.ApprovalReminderAckView.post)
        self.assertTrue(
            _is_inside_atomic(src, 'get_or_create'),
            'ack 的 get_or_create 应在事务内'
        )


# ============================================================
# 执照模块对照基线（无变化，继续 PASS）
# ============================================================

class LicenseBaselineTests(SimpleTestCase):
    """无线电台执照模块审计基线"""

    def test_R_RL_1_create_scan_inside_transaction(self):
        """R-RL-1 (PASS): create 的 scan 在事务内"""
        src = inspect.getsource(license_views.RadioLicenseView._handle_create)
        self.assertTrue(_is_inside_atomic(src, 'scan_single_license'))

    def test_R_RL_1_create_audit_inside_transaction(self):
        """R-RL-1 (PASS): create 的 audit 在事务内"""
        src = inspect.getsource(license_views.RadioLicenseView._handle_create)
        self.assertTrue(_is_inside_atomic(src, 'record_audit_event'))

    def test_R_RL_2_edit_scan_inside_transaction(self):
        """R-RL-2 (PASS): edit 的 scan 在事务内"""
        src = inspect.getsource(license_views.RadioLicenseView._handle_edit)
        self.assertTrue(_is_inside_atomic(src, 'scan_single_license'))

    def test_R_RL_2_edit_audit_inside_transaction(self):
        """R-RL-2 (PASS): edit 的 audit 在事务内"""
        src = inspect.getsource(license_views.RadioLicenseView._handle_edit)
        self.assertTrue(_is_inside_atomic(src, 'record_audit_event'))

    def test_R_RL_3_delete_audit_inside_transaction(self):
        """R-RL-3 (PASS): delete 的 audit 在事务内"""
        src = inspect.getsource(license_views.RadioLicenseView.delete)
        self.assertTrue(_is_inside_atomic(src, 'record_audit_event'))

    def test_R_RL_3_delete_soft_delete_inside_transaction(self):
        """R-RL-3 (PASS): delete 的 soft_delete 在事务内"""
        src = inspect.getsource(license_views.RadioLicenseView.delete)
        self.assertTrue(_is_inside_atomic(src, 'soft_delete_by_object'))

    def test_R_RL_3_delete_obj_inside_transaction(self):
        """R-RL-3 (PASS): delete 的 license_obj.delete() 在事务内"""
        src = inspect.getsource(license_views.RadioLicenseView.delete)
        self.assertTrue(_is_inside_atomic(src, 'license_obj.delete'))
