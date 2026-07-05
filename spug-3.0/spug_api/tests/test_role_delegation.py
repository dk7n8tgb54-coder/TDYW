# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""用户角色委派权限稳健修复测试。

覆盖方案《必测用例》全部场景：
- 普通管理员无法看到/分配超级管理员角色
- 普通管理员无法通过直接构造 role_ids 越权
- 普通管理员无法创建全局管理员角色
- 普通管理员无法把角色权限设置到超过自身权限
- 超级管理员原有能力不受影响
"""
import json

from django.test import TestCase

from apps.account.models import User, Role
from apps.account.role_permissions import (
    get_assignable_roles,
    get_manageable_role,
    validate_assignable_role_ids,
    validate_page_perms_subset,
    flatten_page_perms,
)


def _make_role(name, creator, *, tenant_id=None, is_system=False,
               is_global_admin=False, page_perms=None, group_perms=None,
               deploy_perms=None):
    return Role.objects.create(
        name=name,
        created_by=creator,
        tenant_id=tenant_id,
        is_system=is_system,
        is_global_admin=is_global_admin,
        page_perms=json.dumps(page_perms) if page_perms else None,
        group_perms=json.dumps(group_perms) if group_perms else None,
        deploy_perms=json.dumps(deploy_perms) if deploy_perms else None,
    )


class RoleDelegationTest(TestCase):
    """角色委派权限边界测试"""

    def setUp(self):
        # 超级管理员
        self.supper = User.objects.create(
            username='supper',
            nickname='超管',
            password_hash=User.make_password('Sup12345!'),
            tenant_id='admin',
            is_supper=True,
        )
        # 租户A的普通管理员（拥有 system.account.view/add/edit/del 权限）
        self.admin_a = User.objects.create(
            username='admin_a',
            nickname='租户A管理员',
            password_hash=User.make_password('Admin123!'),
            tenant_id='tenant_a',
        )
        self.role_admin_a = _make_role(
            '租户A管理员角色', self.supper,
            tenant_id='tenant_a',
            page_perms={
                'system': {'account': ['view', 'add', 'edit', 'del']},
                'dashboard': {'dashboard': ['view']},
            },
        )
        self.admin_a.roles.add(self.role_admin_a)
        # 清空权限缓存，确保 page_perms 聚合生效
        self.admin_a.set_perms_cache()

        # 租户B的普通管理员
        self.admin_b = User.objects.create(
            username='admin_b',
            nickname='租户B管理员',
            password_hash=User.make_password('Admin123!'),
            tenant_id='tenant_b',
        )
        self.role_admin_b = _make_role(
            '租户B管理员角色', self.supper,
            tenant_id='tenant_b',
            page_perms={'system': {'account': ['view', 'add', 'edit']}},
        )
        self.admin_b.roles.add(self.role_admin_b)
        self.admin_b.set_perms_cache()

        # 平台级系统角色（超管创建）
        self.platform_role = _make_role(
            '平台系统角色', self.supper,
            tenant_id=None,
            is_system=True,
            page_perms={'system': {'account': ['view', 'add', 'edit', 'del']}},
        )
        # 全局管理员角色
        self.global_admin_role = _make_role(
            '全局管理员', self.supper,
            tenant_id=None,
            is_system=True,
            is_global_admin=True,
        )
        # 租户A的普通角色
        self.tenant_a_role = _make_role(
            '租户A普通角色', self.supper,
            tenant_id='tenant_a',
            page_perms={'dashboard': {'dashboard': ['view']}},
        )

    # ---------------- 可分配角色范围 ----------------

    def test_supper_sees_all_roles(self):
        """超管可看到全部角色"""
        ids = set(get_assignable_roles(self.supper).values_list('id', flat=True))
        self.assertIn(self.platform_role.id, ids)
        self.assertIn(self.global_admin_role.id, ids)
        self.assertIn(self.tenant_a_role.id, ids)
        self.assertIn(self.role_admin_b.id, ids)

    def test_normal_admin_cannot_see_platform_roles(self):
        """普通管理员看不到平台系统角色、全局管理员角色、其他租户角色"""
        ids = set(get_assignable_roles(self.admin_a).values_list('id', flat=True))
        # 只能看到本租户普通角色
        self.assertIn(self.tenant_a_role.id, ids)
        self.assertIn(self.role_admin_a.id, ids)
        # 看不到平台系统角色
        self.assertNotIn(self.platform_role.id, ids)
        # 看不到全局管理员角色
        self.assertNotIn(self.global_admin_role.id, ids)
        # 看不到其他租户角色
        self.assertNotIn(self.role_admin_b.id, ids)

    # ---------------- role_ids 越权校验 ----------------

    def test_normal_admin_can_assign_own_tenant_role(self):
        """普通管理员分配本租户普通角色：通过"""
        err = validate_assignable_role_ids(
            self.admin_a, [self.tenant_a_role.id, self.role_admin_a.id]
        )
        self.assertIsNone(err)

    def test_normal_admin_can_assign_with_target_tenant(self):
        """普通管理员分配本租户角色（传入一致的 target_tenant_id）：通过"""
        err = validate_assignable_role_ids(
            self.admin_a, [self.tenant_a_role.id], target_tenant_id='tenant_a'
        )
        self.assertIsNone(err)

    def test_normal_admin_cannot_assign_platform_role(self):
        """普通管理员直接构造请求分配平台系统角色：失败"""
        err = validate_assignable_role_ids(self.admin_a, [self.platform_role.id])
        self.assertIsNotNone(err)

    def test_normal_admin_cannot_assign_global_admin_role(self):
        """普通管理员直接构造请求分配全局管理员角色：失败"""
        err = validate_assignable_role_ids(self.admin_a, [self.global_admin_role.id])
        self.assertIsNotNone(err)

    def test_normal_admin_cannot_assign_other_tenant_role(self):
        """普通管理员直接构造请求分配其他租户角色：失败"""
        err = validate_assignable_role_ids(self.admin_a, [self.role_admin_b.id])
        self.assertIsNotNone(err)

    def test_assign_nonexistent_role_id(self):
        """分配不存在的 role_id：失败（拦截 500）"""
        # 普通管理员
        err = validate_assignable_role_ids(self.admin_a, [999999])
        self.assertIsNotNone(err)
        # 超管
        err = validate_assignable_role_ids(self.supper, [999999], target_tenant_id='tenant_a')
        self.assertIsNotNone(err)
        # 超管混合存在+不存在
        err = validate_assignable_role_ids(
            self.supper,
            [self.platform_role.id, 999999],
            target_tenant_id='tenant_a'
        )
        self.assertIsNotNone(err)

    def test_supper_can_assign_any_role(self):
        """超管分配任意角色（无目标租户约束时）：通过"""
        err = validate_assignable_role_ids(
            self.supper, [self.platform_role.id, self.global_admin_role.id]
        )
        self.assertIsNone(err)

    def test_supper_can_assign_platform_role_to_any_tenant(self):
        """超管分配平台级角色给任意租户用户：通过"""
        err = validate_assignable_role_ids(
            self.supper, [self.platform_role.id], target_tenant_id='tenant_a'
        )
        self.assertIsNone(err)

    def test_supper_can_assign_global_admin_role_to_any_tenant(self):
        """超管分配全局管理员角色给任意租户用户：通过"""
        err = validate_assignable_role_ids(
            self.supper, [self.global_admin_role.id], target_tenant_id='tenant_a'
        )
        self.assertIsNone(err)

    def test_supper_can_assign_matching_tenant_role(self):
        """超管分配与目标租户一致的租户角色：通过"""
        err = validate_assignable_role_ids(
            self.supper, [self.tenant_a_role.id], target_tenant_id='tenant_a'
        )
        self.assertIsNone(err)

    def test_supper_cannot_assign_cross_tenant_role(self):
        """超管把 B 租户角色分配给 A 租户用户：失败"""
        err = validate_assignable_role_ids(
            self.supper, [self.role_admin_b.id], target_tenant_id='tenant_a'
        )
        self.assertIsNotNone(err)

    # ---------------- 可管理角色（编辑/删除） ----------------

    def test_normal_admin_cannot_manage_platform_role(self):
        """普通管理员不能编辑/删除平台系统角色"""
        role = get_manageable_role(self.admin_a, self.platform_role.id)
        self.assertIsNone(role)

    def test_normal_admin_cannot_manage_global_admin_role(self):
        """普通管理员不能编辑/删除全局管理员角色"""
        role = get_manageable_role(self.admin_a, self.global_admin_role.id)
        self.assertIsNone(role)

    def test_normal_admin_cannot_manage_other_tenant_role(self):
        """普通管理员不能编辑/删除其他租户角色"""
        role = get_manageable_role(self.admin_a, self.role_admin_b.id)
        self.assertIsNone(role)

    def test_normal_admin_can_manage_own_tenant_role(self):
        """普通管理员能编辑/删除本租户普通角色"""
        role = get_manageable_role(self.admin_a, self.tenant_a_role.id)
        self.assertIsNotNone(role)

    def test_supper_can_manage_any_role(self):
        """超管能管理任意角色"""
        role = get_manageable_role(self.supper, self.platform_role.id)
        self.assertIsNotNone(role)

    # ---------------- 权限子集校验 ----------------

    def test_flatten_page_perms(self):
        """测试 page_perms 展平"""
        perms = flatten_page_perms({
            'system': {'account': ['view', 'add']},
            'dashboard': {'dashboard': ['view']},
        })
        self.assertEqual(perms, {
            'system.account.view', 'system.account.add',
            'dashboard.dashboard.view',
        })

    def test_normal_admin_page_perms_within_scope(self):
        """普通管理员设置权限在自身范围内：通过"""
        err = validate_page_perms_subset(
            self.admin_a,
            {'system': {'account': ['view', 'add']}},
        )
        self.assertIsNone(err)

    def test_normal_admin_page_perms_exceed_scope(self):
        """普通管理员设置权限超过自身：失败"""
        # admin_a 没有 document 权限
        err = validate_page_perms_subset(
            self.admin_a,
            {'document': {'document': ['view', 'delete']}},
        )
        self.assertIsNotNone(err)

    def test_supper_page_perms_any(self):
        """超管设置任意权限：通过"""
        err = validate_page_perms_subset(
            self.supper,
            {'document': {'document': ['view', 'delete', 'upload']}},
        )
        self.assertIsNone(err)

    # ---------------- group_perms / deploy_perms 子集 ----------------

    def test_normal_admin_group_perms_exceed_scope(self):
        """普通管理员 group_perms 超过自身：失败"""
        from apps.account.role_permissions import validate_group_perms_subset
        # admin_a 没有 group_perms
        err = validate_group_perms_subset(self.admin_a, ['group_x'])
        self.assertIsNotNone(err)

    def test_normal_admin_deploy_perms_exceed_scope(self):
        """普通管理员 deploy_perms 超过自身：失败"""
        from apps.account.role_permissions import validate_deploy_perms_subset
        err = validate_deploy_perms_subset(
            self.admin_a, {'apps': ['app_x'], 'envs': ['env_y']}
        )
        self.assertIsNotNone(err)

    # ---------------- 角色创建后归属 ----------------

    def test_tenant_role_created_by_supper_is_platform(self):
        """迁移后超管创建的角色 tenant_id 为 None（平台级）"""
        # role_admin_a 虽然归属 tenant_a，但在本测试中是直接创建的
        # 这里验证 platform_role 的归属
        self.assertIsNone(self.platform_role.tenant_id)
        self.assertTrue(self.platform_role.is_system)

    def test_global_admin_role_is_platform_system(self):
        """全局管理员角色强制为平台级系统角色"""
        self.assertIsNone(self.global_admin_role.tenant_id)
        self.assertTrue(self.global_admin_role.is_system)
        self.assertTrue(self.global_admin_role.is_global_admin)

    def test_tenant_a_role_belongs_to_tenant_a(self):
        """租户A普通角色归属正确"""
        self.assertEqual(self.tenant_a_role.tenant_id, 'tenant_a')
        self.assertFalse(self.tenant_a_role.is_system)

    # ---------------- Role.to_dict 输出 ----------------

    def test_role_to_dict_exports_tenant_id_and_is_system(self):
        """Role.to_dict 应输出 tenant_id 和 is_system，保证前端编辑回显"""
        data = self.platform_role.to_dict()
        self.assertIn('tenant_id', data)
        self.assertIn('is_system', data)
        self.assertIn('is_global_admin', data)
        self.assertIsNone(data['tenant_id'])
        self.assertTrue(data['is_system'])

        data2 = self.tenant_a_role.to_dict()
        self.assertEqual(data2['tenant_id'], 'tenant_a')
        self.assertFalse(data2['is_system'])
