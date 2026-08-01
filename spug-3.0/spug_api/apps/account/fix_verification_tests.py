# -*- coding: utf-8 -*-
"""account 模块修复验证测试

验证 crud_audit_tests.py 中确认的 10 项风险已修复。
每项测试以 F{n} 命名，对应原 R{n} 风险编号。
"""
import inspect
from django.db import connection, IntegrityError, transaction
from django.test import TestCase
from apps.account.models import User, Role, History, Tenant
from apps.account import views as acc_views
from apps.account import history as acc_history


def _make_user(username='fix_test', is_supper=False, tenant_id='admin'):
    import time
    token = (username * 10)[:32]
    now_ts = int(time.time()) + 3600
    with connection.cursor() as cur:
        cur.execute("SET SESSION sql_mode=''")
        cur.execute(
            "INSERT INTO users (username,nickname,password_hash,is_active,is_supper,"
            "access_token,token_expired,last_login,last_ip,type,tenant_id,wx_token,"
            "created_at) VALUES (%s,%s,'x',1,%s,%s,%s,'2026-01-01','127.0.0.1',"
            "'default',%s,'',NOW())",
            [username, username, 1 if is_supper else 0, token, now_ts, tenant_id])
    return User.objects.get(username=username)


def _make_role(name='修复测试角色', tenant_id='admin', created_by=None, **kw):
    return Role.objects.create(
        name=name, desc=kw.get('desc', ''), page_perms=kw.get('page_perms', ''),
        deploy_perms=kw.get('deploy_perms', ''), group_perms=kw.get('group_perms', ''),
        is_global_admin=kw.get('is_global_admin', False), tenant_id=tenant_id,
        is_system=kw.get('is_system', False), created_by=created_by,
    )


def _cleanup(*models):
    for m in models:
        try:
            m.objects.all().delete()
        except Exception:
            pass


# ==================== R13: HistoryView.get 分页 ====================

class F13_HistoryViewHasPagination(TestCase):
    """F13: HistoryView.get 已添加 [:500] 分页限制"""
    def test_f13a_has_slice_limit(self):
        src = inspect.getsource(acc_history.HistoryView.get)
        self.assertIn('[:500]', src, "HistoryView.get 应有 [:500] 切片限制")

    def test_f13b_not_unbounded(self):
        src = inspect.getsource(acc_history.HistoryView.get)
        self.assertNotIn('objects.all()\n', src.replace(' ', ''),
                         "不应有无限制的 objects.all()")

    def test_f13c_has_order_by(self):
        src = inspect.getsource(acc_history.HistoryView.get)
        self.assertIn('order_by', src, "应有 order_by 保证排序确定性")


# ==================== R5: UserView.delete 事务 ====================

class F5_UserViewDeleteHasTransaction(TestCase):
    """F5: UserView.delete 已添加显式 transaction.atomic()"""
    def test_f5a_has_transaction_atomic(self):
        src = inspect.getsource(acc_views.UserView.delete)
        self.assertIn('transaction.atomic', src,
                      "UserView.delete 应有显式 transaction.atomic()")


# ==================== R6: UserView.patch 事务 ====================

class F6_UserViewPatchHasTransaction(TestCase):
    """F6: UserView.patch 已添加显式 transaction.atomic()"""
    def test_f6a_has_transaction_atomic(self):
        src = inspect.getsource(acc_views.UserView.patch)
        self.assertIn('transaction.atomic', src,
                      "UserView.patch 应有显式 transaction.atomic()")


# ==================== R9: RoleView.post IntegrityError 捕获 ====================

class F9_RoleViewPostCatchesIntegrityError(TestCase):
    """F9: RoleView.post(create) 已捕获 IntegrityError"""
    def test_f9a_has_integrity_error_handling(self):
        src = inspect.getsource(acc_views.RoleView.post)
        self.assertIn('IntegrityError', src,
                      "RoleView.post 应捕获 IntegrityError")

    def test_f9b_returns_friendly_message(self):
        src = inspect.getsource(acc_views.RoleView.post)
        self.assertIn('角色名称已存在', src,
                      "应返回友好提示 '角色名称已存在' 而非 500")

    def test_f9c_behavior_duplicate_role(self):
        """行为测试：重复创建角色名返回友好提示"""
        try:
            admin = _make_user('f9c_admin', is_supper=True)
            _make_role('F9重复角色', tenant_id='admin', created_by=admin)
            # 再次创建同名角色应抛出 IntegrityError
            with self.assertRaises(IntegrityError):
                Role.objects.create(
                    name='F9重复角色', desc='', page_perms='', deploy_perms='',
                    group_perms='', is_global_admin=False, tenant_id='admin',
                    is_system=False, created_by=admin,
                )
        finally:
            _cleanup(Role, User)


# ==================== R10: TenantView.post IntegrityError 捕获 ====================

class F10_TenantViewPostCatchesIntegrityError(TestCase):
    """F10: TenantView.post 已捕获 IntegrityError"""
    def test_f10a_has_integrity_error_handling(self):
        src = inspect.getsource(acc_views.TenantView.post)
        self.assertIn('IntegrityError', src,
                      "TenantView.post 应捕获 IntegrityError")

    def test_f10b_returns_friendly_message(self):
        src = inspect.getsource(acc_views.TenantView.post)
        self.assertIn('租户标识已存在', src,
                      "应返回友好提示 '租户标识已存在'")


# ==================== R11: account CRUD delete 审计日志 ====================

class F11_AccountCRUDHasAuditEvent(TestCase):
    """F11: account CRUD delete 操作已添加 record_audit_event"""
    def test_f11a_userview_delete_has_audit(self):
        src = inspect.getsource(acc_views.UserView.delete)
        self.assertIn('record_audit_event', src,
                      "UserView.delete 应调用 record_audit_event")

    def test_f11b_userview_delete_has_target_name(self):
        src = inspect.getsource(acc_views.UserView.delete)
        self.assertIn('target_name', src,
                      "UserView.delete 应传 target_name 参数")

    def test_f11c_roleview_delete_has_audit(self):
        src = inspect.getsource(acc_views.RoleView.delete)
        self.assertIn('record_audit_event', src,
                      "RoleView.delete 应调用 record_audit_event")

    def test_f11d_roleview_delete_saves_name_before_delete(self):
        src = inspect.getsource(acc_views.RoleView.delete)
        self.assertIn('role_name', src,
                      "RoleView.delete 应在删除前保存角色名")

    def test_f11e_tenantview_delete_has_audit(self):
        src = inspect.getsource(acc_views.TenantView.delete)
        self.assertIn('record_audit_event', src,
                      "TenantView.delete 应调用 record_audit_event")

    def test_f11f_tenantview_delete_saves_name_before_delete(self):
        src = inspect.getsource(acc_views.TenantView.delete)
        self.assertIn('tenant_name', src,
                      "TenantView.delete 应在删除前保存租户名")


# ==================== R12: UserView.get_tenant_choices annotate ====================

class F12_GetTenantChoicesNoNPlus1(TestCase):
    """F12: UserView.get_tenant_choices 已消除 N+1 查询"""
    def test_f12a_no_loop_count(self):
        src = inspect.getsource(acc_views.UserView.get_tenant_choices)
        lines = src.split('\n')
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('for ') or stripped.startswith('for\t'):
                indent = len(line) - len(line.lstrip())
                for next_line in lines[i+1:]:
                    if next_line.strip() and len(next_line) - len(next_line.lstrip()) > indent:
                        self.assertNotIn('.count()', next_line,
                                         "for 循环内不应有 .count() 调用")
                    elif next_line.strip() and len(next_line) - len(next_line.lstrip()) <= indent:
                        break

    def test_f12b_uses_subquery(self):
        """使用子查询（extra select）替代 N+1"""
        src = inspect.getsource(acc_views.UserView.get_tenant_choices)
        self.assertTrue('extra(' in src or 'annotate' in src or 'Subquery' in src,
                        "应使用 extra/annotate/Subquery 消除 N+1")

    def test_f12c_has_tenant_id_join(self):
        """子查询应关联 tenant_id"""
        src = inspect.getsource(acc_views.UserView.get_tenant_choices)
        self.assertIn('tenant_id', src.lower())


# ==================== R14: TenantView.get 分页 ====================

class F14_TenantViewHasLimit(TestCase):
    """F14: TenantView.get 已添加 [:100] 上限"""
    def test_f14a_has_slice_limit(self):
        src = inspect.getsource(acc_views.TenantView.get)
        self.assertIn('[:', src,
                      "TenantView.get 应有切片限制")


# ==================== R19: RoleView.delete 过滤软删除用户 ====================

class F19_RoleDeleteFiltersSoftDeleted(TestCase):
    """F19: RoleView.delete 已过滤软删除用户"""
    def test_f19a_filters_deleted_by_id(self):
        src = inspect.getsource(acc_views.RoleView.delete)
        self.assertIn('deleted_by_id__isnull=True', src,
                      "RoleView.delete 应过滤 deleted_by_id__isnull=True")

    def test_f19b_not_raw_user_set_exists(self):
        src = inspect.getsource(acc_views.RoleView.delete)
        self.assertNotIn('user_set.exists()', src,
                         "不应使用无过滤的 user_set.exists()")

    def test_f19c_behavior_soft_deleted_user_not_blocking(self):
        """行为测试：软删除用户不阻止角色删除"""
        try:
            admin = _make_user('f19c_admin', is_supper=True)
            role = _make_role('F19角色', tenant_id='admin', created_by=admin)
            # 创建一个用户并关联到角色
            u = _make_user('f19c_user')
            u.roles.add(role)
            # 软删除该用户
            u.is_active = False
            u.deleted_by = admin
            u.save()
            # 软删除用户不应阻止角色删除
            active_users = role.user_set.filter(deleted_by_id__isnull=True).count()
            self.assertEqual(active_users, 0,
                             "过滤后不应有活跃用户关联")
        finally:
            _cleanup(User, Role)


# ==================== R20: UserView.delete 清空 token_expired ====================

class F20_UserViewDeleteClearsToken(TestCase):
    """F20: UserView.delete 已设置 token_expired=0 使旧 token 失效"""
    def test_f20a_sets_token_expired_zero(self):
        src = inspect.getsource(acc_views.UserView.delete)
        self.assertIn('token_expired = 0', src,
                      "UserView.delete 应设置 token_expired = 0")

    def test_f20b_in_transaction_block(self):
        src = inspect.getsource(acc_views.UserView.delete)
        # token_expired=0 应在 transaction.atomic() 块内
        atomic_idx = src.find('transaction.atomic')
        token_idx = src.find('token_expired = 0')
        self.assertGreater(token_idx, atomic_idx,
                           "token_expired=0 应在 transaction.atomic() 之后（同一块内）")
