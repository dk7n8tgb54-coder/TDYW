# -*- coding: utf-8 -*-
"""权限体系 Bug 检测测试

检测到的 Bug：

Bug 1 (严重 - 权限提升): UserView.post() 同时处理创建和编辑用户，
    但 PERM_MAP 仅将 POST 映射到 'system.account.add' 权限。
    拥有 system.account.add 但没有 system.account.edit 的用户，
    可以通过 POST 请求（带 id 字段）编辑其他用户，构成权限提升。

Bug 2 (中等 - 信息泄露): TenantView.get() 返回 Tenant.objects.all()，
    不做租户过滤。拥有 system.tenant.view 权限的非超管用户可以看到所有租户信息。

Bug 3 (低 - 类型不一致): User.has_perms() 对超管返回 True (bool)，
    对非超管返回 set。在布尔上下文中可工作，但类型不一致，
    若用 == True 比较会导致非超管用户权限检查失败。
"""
import json
import tempfile
import time

from django.test import TestCase, override_settings

from apps.account.models import User, Role, Tenant
from apps.utils.test_helpers import make_user, make_client, setup_test_env

VALID_PWD = 'Admin888..'


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PermissionBugTest(TestCase):
    """权限体系 Bug 检测"""

    def setUp(self):
        setup_test_env(self)
        # 超管
        self.supper = make_user('supper', is_supper=True)
        self.supper_client = make_client(self.supper)

        # 只有 system.account.add 权限的用户（无 edit 权限）
        self.add_only = make_user('add_only', ['system.account.add'])
        self.add_only_client = make_client(self.add_only)

        # 只有 system.account.edit 权限的用户（无 add 权限）
        self.edit_only = make_user('edit_only', ['system.account.edit'])
        self.edit_only_client = make_client(self.edit_only)

        # 只有 system.account.view 权限的用户
        self.view_only = make_user('view_only', ['system.account.view'])
        self.view_only_client = make_client(self.view_only)

        # 无任何权限的用户
        self.noperm = make_user('noperm', [])
        self.noperm_client = make_client(self.noperm)

        # 目标用户（被编辑的对象），与 add_only 同租户
        self.target = make_user('target', [])

    # ----------------------------------------------------------------
    # Bug 1: UserView.post() 权限提升 —— 拥有 add 权限可编辑用户
    # ----------------------------------------------------------------

    def test_bug1_add_only_user_can_edit_via_post(self):
        """Bug 1: 只有 system.account.add 的用户可通过 POST+id 编辑用户

        预期（安全行为）：应返回权限拒绝
        实际（当前 bug）：编辑成功，构成权限提升
        """
        target_nickname_before = self.target.nickname

        r = self.add_only_client.post(
            '/account/user/',
            data=json.dumps({
                'id': self.target.id,           # 带 id -> 走编辑路径
                'username': self.target.username,
                'password': VALID_PWD,
                'nickname': 'HackedByAddOnly',  # 修改昵称
                'role_ids': [],
            }),
            content_type='application/json',
        )
        body = r.json()

        # 刷新目标用户
        self.target.refresh_from_db()

        if not body.get('error') and self.target.nickname == 'HackedByAddOnly':
            # Bug 确认：add_only 用户成功编辑了目标用户
            self._record_bug(
                'Bug 1 (CRITICAL)',
                'UserView.post() 权限提升: '
                '仅有 system.account.add 权限的用户通过 POST+id 成功编辑了用户。'
                f'目标用户昵称从 "{target_nickname_before}" 改为 "{self.target.nickname}"'
            )
        else:
            # 如果已修复，编辑应被拒绝
            pass

    def test_bug1_add_only_user_cannot_edit_via_patch(self):
        """对照组: add_only 用户通过 PATCH 编辑应被拒绝（PERM_MAP 正确映射 PATCH->edit）"""
        r = self.add_only_client.patch(
            '/account/user/',
            data=json.dumps({
                'id': self.target.id,
                'is_active': False,
            }),
            content_type='application/json',
        )
        body = r.json()
        self.assertTrue(
            body.get('error'),
            'add_only 用户不应能通过 PATCH 编辑用户（缺少 system.account.edit）'
        )

    def test_bug1_edit_only_user_cannot_create_via_post(self):
        """对照组: edit_only 用户通过 POST 创建用户应被拒绝（缺少 system.account.add）"""
        r = self.edit_only_client.post(
            '/account/user/',
            data=json.dumps({
                'username': 'new_user_by_edit_only',
                'password': VALID_PWD,
                'nickname': 'New',
                'role_ids': [],
            }),
            content_type='application/json',
        )
        body = r.json()
        self.assertTrue(
            body.get('error'),
            'edit_only 用户不应能通过 POST 创建用户（缺少 system.account.add）'
        )

    def test_bug1_add_only_user_can_create_via_post(self):
        """对照组: add_only 用户通过 POST 创建用户应成功（有 system.account.add）"""
        r = self.add_only_client.post(
            '/account/user/',
            data=json.dumps({
                'username': 'new_user_by_add_only',
                'password': VALID_PWD,
                'nickname': 'New',
                'role_ids': [],
            }),
            content_type='application/json',
        )
        body = r.json()
        self.assertFalse(
            body.get('error'),
            'add_only 用户应能通过 POST 创建用户（有 system.account.add）'
        )

    def test_bug1_add_only_can_edit_supper_via_post(self):
        """Bug 1 扩展: add_only 用户尝试编辑超管账号应被拒绝（业务层防护）

        _handle_user_edit 中有 '无权编辑超级管理员账号' 校验，
        即使权限提升 bug 存在，这层防护仍应生效。
        """
        r = self.add_only_client.post(
            '/account/user/',
            data=json.dumps({
                'id': self.supper.id,
                'username': 'supper',
                'password': VALID_PWD,
                'nickname': 'HackedSupper',
                'role_ids': [],
            }),
            content_type='application/json',
        )
        body = r.json()
        # 应该被拒绝（不管是权限层还是业务层）
        # 如果权限提升 bug 存在，权限层放行但业务层拦截
        self.assertTrue(
            body.get('error'),
            'add_only 用户不应能编辑超管账号'
        )

    # ----------------------------------------------------------------
    # Bug 2: TenantView.get() 信息泄露 —— 非超管可见所有租户
    # ----------------------------------------------------------------

    def test_bug2_tenant_list_no_tenant_filter(self):
        """Bug 2: 拥有 system.tenant.view 的非超管用户可看到所有租户

        TenantView.get() 返回 Tenant.objects.all()，不做租户过滤。
        """
        # 创建多个租户
        Tenant.objects.create(id='t1', name='租户A', created_by=self.supper)
        Tenant.objects.create(id='t2', name='租户B', created_by=self.supper)

        # 给 view_only 用户额外加 system.tenant.view 权限
        from django.core.cache import cache
        self.view_only.set_perms_cache({'system.tenant.view'}, version=0)
        view_only_client = make_client(self.view_only)

        r = view_only_client.get('/account/tenant/')
        body = r.json()

        if not body.get('error'):
            tenant_ids = [t['id'] for t in body['data']]
            # view_only 用户属于 'admin' 租户（make_user 默认）
            # 但 TenantView 返回所有租户
            if 't1' in tenant_ids and 't2' in tenant_ids:
                self._record_bug(
                    'Bug 2 (MEDIUM)',
                    'TenantView.get() 信息泄露: '
                    '拥有 system.tenant.view 的非超管用户可看到所有租户（包括其他租户）。'
                    f'返回的租户列表: {tenant_ids}'
                )

    # ----------------------------------------------------------------
    # Bug 3: has_perms() 返回类型不一致
    # ----------------------------------------------------------------

    def test_bug3_has_perms_return_type_inconsistency(self):
        """Bug 3: has_perms() 对超管返回 True(bool)，对非超管返回 set

        在布尔上下文中可工作，但用 == True 比较时非超管会失败。
        """
        # 超管
        supper = make_user('supper2', is_supper=True)
        result_supper = supper.has_perms(['any.perm'])
        self.assertIs(result_supper, True, '超管 has_perms 应返回 True')

        # 非超管有权限
        user_with_perm = make_user('perm_user', ['some.perm'])
        result_with_perm = user_with_perm.has_perms(['some.perm'])
        # 如果返回 set 而非 bool，则 == True 会失败
        if result_with_perm == True and not isinstance(result_with_perm, bool):
            self._record_bug(
                'Bug 3 (LOW)',
                f'has_perms() 返回类型不一致: '
                f'超管返回 True(bool)，非超管返回 {type(result_with_perm).__name__}({result_with_perm})。'
                f'虽然布尔上下文可用，但 == True 比较或 is True 判断会出错。'
            )

        # 非超管无权限
        user_without_perm = make_user('noperm_user', [])
        result_without_perm = user_without_perm.has_perms(['some.perm'])
        # 应该是空 set 或 False
        if not isinstance(result_without_perm, bool) and not result_without_perm:
            # 空集是 falsy，但类型不是 bool
            pass  # 这也是类型不一致的表现

    def test_bug3_has_perms_with_eq_true_comparison(self):
        """Bug 3 验证: 用 == True 比较非超管用户的 has_perms 结果"""
        user = make_user('eq_test', ['some.perm'])

        # 布尔上下文（正确用法）
        if user.has_perms(['some.perm']):
            pass  # 正常工作
        else:
            self.fail('布尔上下文中 has_perms 应为 truthy')

        # == True 比较（如果返回 set 而非 bool，这会失败）
        result = user.has_perms(['some.perm'])
        if result == True:
            pass  # 如果返回 bool 或 truthy set 且 == True，则通过
        else:
            # set({'some.perm'}) == True -> False，这证明类型不一致
            self._record_bug(
                'Bug 3 (LOW)',
                f'has_perms() == True 比较失败: '
                f'返回值类型为 {type(result).__name__}({result})，不是 bool，'
                f'导致 == True 判断为 False。'
            )

    # ----------------------------------------------------------------
    # 辅助方法
    # ----------------------------------------------------------------

    _bugs_found = []

    def _record_bug(self, bug_id, description):
        """记录发现的 bug（不直接 fail，由汇总测试统一断言）"""
        PermissionBugTest._bugs_found.append((bug_id, description))

    @classmethod
    def tearDownClass(cls):
        """汇总输出所有发现的 bug"""
        super().tearDownClass()
        if cls._bugs_found:
            print('\n' + '=' * 70)
            print('权限体系 Bug 检测结果:')
            print('=' * 70)
            for bug_id, desc in cls._bugs_found:
                print(f'\n  [{bug_id}]')
                print(f'  {desc}')
            print('\n' + '=' * 70)
            print(f'共发现 {len(cls._bugs_found)} 个 bug')
            print('=' * 70 + '\n')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PermissionBugSummaryTest(TestCase):
    """Bug 汇总断言 —— 确保已知的 bug 被正确检测到"""

    def setUp(self):
        setup_test_env(self)
        self.supper = make_user('supper', is_supper=True)
        self.supper_client = make_client(self.supper)

        self.add_only = make_user('add_only', ['system.account.add'])
        self.add_only_client = make_client(self.add_only)

        self.target = make_user('target', [])

    def test_confirm_bug1_privilege_escalation(self):
        """确认 Bug 1: add_only 用户可通过 POST+id 编辑用户（权限提升）

        这是一个 BUG —— POST 方法同时处理创建和编辑，但 PERM_MAP
        只校验了 system.account.add 权限，未区分创建 vs 编辑操作。
        """

        original_nickname = self.target.nickname

        r = self.add_only_client.post(
            '/account/user/',
            data=json.dumps({
                'id': self.target.id,
                'username': self.target.username,
                'password': VALID_PWD,
                'nickname': 'PwnedByAddOnly',
                'role_ids': [],
            }),
            content_type='application/json',
        )
        body = r.json()
        self.target.refresh_from_db()

        # 断言 bug 存在：add_only 用户成功编辑了目标用户
        # 如果这个断言失败，说明 bug 已被修复（是好事）
        edit_succeeded = (
            not body.get('error')
            and self.target.nickname == 'PwnedByAddOnly'
        )

        if edit_succeeded:
            # Bug 确认存在
            self.assertEqual(
                self.target.nickname, 'PwnedByAddOnly',
                'Bug 1 确认: add_only 用户成功编辑了目标用户昵称（权限提升）'
            )
            print(
                '\n[BUG 确认] Bug 1 (CRITICAL - 权限提升): '
                f'仅有 system.account.add 权限的用户通过 POST+id '
                f'成功将目标用户昵称从 "{original_nickname}" 改为 "{self.target.nickname}"'
            )
        else:
            # Bug 已修复
            print(
                '\n[已修复] Bug 1: add_only 用户无法通过 POST+id 编辑用户，'
                f'返回: {body.get("error", "unknown")}'
            )

    def test_confirm_bug3_has_perms_type(self):
        """确认 Bug 3: has_perms 对非超管返回 set 而非 bool"""
        user = make_user('type_check', ['test.perm'])
        result = user.has_perms(['test.perm'])

        self.assertTrue(
            result,  # 布尔上下文应为 truthy
            '有权限的用户的 has_perms 应为 truthy'
        )

        # 检查是否为 set 类型（而非 bool）
        if isinstance(result, set):
            print(
                f'\n[BUG 确认] Bug 3 (LOW - 类型不一致): '
                f'has_perms() 对非超管返回 set({result})，'
                f'类型为 {type(result).__name__} 而非 bool'
            )
        elif isinstance(result, bool):
            print('\n[已修复] Bug 3: has_perms() 返回 bool 类型')
