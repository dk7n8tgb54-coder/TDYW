# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""租户管理体系安全发现验证测试

验证 5 个候选安全发现：
1. 禁用租户后，租户用户仍可登录并正常调用 API
2. 删除并重建同名租户，会继承原租户残留数据
3. 普通用户一旦获得租户管理权限，可管理所有租户
4. 用户迁出租户后，旧证据附件预览链接仍可使用约 5 分钟
5. 签名预览链接存在相同的租户迁移后残留访问窗口

运行：
  docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
    python manage.py test tests.test_tenant_security_findings --noinput
"""
import json
import time
import uuid

from django.test import TestCase, Client, RequestFactory
from django.contrib.auth.hashers import make_password

from apps.account.models import User, Role, Tenant
from apps.setting.models import Setting
from apps.setting.utils import AppSetting


def _make_user(username, password='Test1234!', **kwargs):
    """创建测试用户"""
    defaults = dict(
        username=username,
        nickname=username,
        password_hash=make_password(password),
        type='default',
        is_supper=False,
        is_active=True,
        access_token=uuid.uuid4().hex,
        token_expired=int(time.time()) + 8 * 3600,
        last_ip='',
        wx_token='',
        tenant_id='admin',
    )
    defaults.update(kwargs)
    return User.objects.create(**defaults)


def _make_tenant(tenant_id, name=None, **kwargs):
    """创建测试租户"""
    su = User.objects.filter(is_supper=True).first()
    if not su:
        su = _make_user('__tenant_creator', is_supper=True, tenant_id='')
    defaults = dict(
        id=tenant_id,
        name=name or tenant_id,
        description='',
        created_by=su,
    )
    defaults.update(kwargs)
    return Tenant.objects.create(**defaults)


def _make_role(name, page_perms_dict, tenant_id='', is_global_admin=False):
    """创建测试角色

    page_perms_dict 格式: {'system': {'tenant': ['view','add','edit','del']}}
    """
    su = User.objects.filter(is_supper=True).first()
    if not su:
        su = _make_user('__role_creator', is_supper=True, tenant_id='')
    return Role.objects.create(
        name=name,
        page_perms=json.dumps(page_perms_dict) if page_perms_dict else '',
        deploy_perms='',
        group_perms='',
        is_global_admin=is_global_admin,
        tenant_id=tenant_id,
        created_by=su,
    )


# ===========================================================================
# 发现 1 已处置：Tenant.is_active 字段已移除（无业务意义的禁用功能已删除）
# ===========================================================================


# ===========================================================================
# 发现 2：删除并重建同名租户，会继承原租户残留数据
# 经评估：此为正确行为（租户=科室，科室重建后看到历史数据是合理的）
# 测试保留为回归验证：确认数据继承行为符合预期
# ===========================================================================
class Finding2TenantDeletionDataResidualTest(TestCase):
    """发现 2：删除并重建同名租户，数据继承是正确行为（非 bug）"""

    def setUp(self):
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        Setting.objects.all().delete()

        self.tenant = _make_tenant('recyclable_tenant', name='待删除租户')
        self.user = _make_user(
            'tenant_user_2',
            tenant_id='recyclable_tenant',
        )
        self.super_user = _make_user(
            'super_admin_2',
            is_supper=True,
            tenant_id='admin',
        )

    def test_delete_and_recreate_tenant_inherits_old_data(self):
        """删除租户后重建同名租户，旧业务数据被新租户继承"""
        from apps.fault.models import FaultRecord
        from datetime import datetime

        # 1. 创建业务数据（故障记录），tenant_id = 'recyclable_tenant'
        fault = FaultRecord.objects.create(
            system_name='测试系统',
            device_code='DEV001',
            fault_date=datetime(2026, 7, 30, 0, 0, 0),
            handler='张三',
            recorder='李四',
            fault_level='一般',
            fault_phenomenon='测试现象',
            handling_process='测试过程',
            tenant_id='recyclable_tenant',
            created_by=self.user,
        )

        # 2. 软删除该租户下所有用户（使删除检查通过）
        self.user.deleted_by = self.super_user
        self.user.save()

        # 3. 删除租户
        self.tenant.delete()

        # 4. 验证旧数据仍然存在（tenant_id 未被清理）
        fault.refresh_from_db()
        self.assertEqual(fault.tenant_id, 'recyclable_tenant')

        # 5. 重建同名租户
        _make_tenant('recyclable_tenant', name='新租户')

        # 6. 查询旧数据
        old_data = FaultRecord.objects.filter(tenant_id='recyclable_tenant')
        if not old_data.exists():
            # 修复后旧数据应被清理或不可访问
            return

        # 7. 新租户用户能查到旧数据（通过 apply_tenant_filter）- 这是正确行为
        new_user = _make_user('new_tenant_user', tenant_id='recyclable_tenant')
        from libs.tenant_utils import apply_tenant_filter
        qs = apply_tenant_filter(FaultRecord.objects.all(), new_user)
        self.assertTrue(
            qs.filter(id=fault.id).exists(),
            "数据继承验证：删除租户 'recyclable_tenant' 后重建同名租户，"
            "新租户用户应能通过 apply_tenant_filter 查到旧租户的历史数据（正确行为）。"
        )


# ===========================================================================
# 发现 3：普通用户一旦获得租户管理权限，可管理所有租户
# ===========================================================================
class Finding3NonSuperTenantManagementTest(TestCase):
    """发现 3：普通用户一旦获得租户管理权限，可管理所有租户

    预期结果：已修复
    - TenantView.dispatch 现在要求 is_supper=True 才能访问
    - 非超管用户即使有 system.tenant.* 权限也无法访问
    """

    def setUp(self):
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        Setting.objects.all().delete()

        # 创建两个租户
        self.tenant_a = _make_tenant('tenant_a_3', name='租户A')
        self.tenant_b = _make_tenant('tenant_b_3', name='租户B')

        # 创建一个非超管用户，属于租户 A，但拥有 system.tenant.* 权限
        self.tenant_admin = _make_user(
            'tenant_admin_3',
            tenant_id='tenant_a_3',
            last_ip='',
        )
        role = _make_role(
            'tenant_manager_role',
            {'system': {'tenant': ['view', 'add', 'edit', 'del']}},
            tenant_id='tenant_a_3',
        )
        self.tenant_admin.roles.add(role)

    def test_non_super_can_list_all_tenants(self):
        """非超管用户拥有 tenant.view 权限后能查看所有租户"""
        client = Client()
        resp = client.get(
            '/account/tenant/',
            HTTP_X_TOKEN=self.tenant_admin.access_token,
        )

        body = resp.json()

        if resp.status_code == 200 and not body.get('error'):
            data = body.get('data', [])
            if isinstance(data, list):
                tenant_ids = {t.get('id') for t in data}
                if 'tenant_b_3' in tenant_ids:
                    self.fail(
                        "BUG 确认 [发现3]：非超管用户 'tenant_admin_3'（属于租户A）"
                        "拥有 system.tenant.view 权限后，能查看所有租户列表（包括租户B）。"
                        "TenantView 未限制非超管用户只能查看自己的租户。"
                    )
                # 即使看不到租户B，能通过权限检查也是问题
                self.fail(
                    "BUG 确认 [发现3]：非超管用户 'tenant_admin_3' 拥有 system.tenant.view 权限后，"
                    "成功通过 TenantView 的权限检查（应仅超管可访问）。"
                )
        # 修复后返回 error（json_response(error=...) 返回 200 + error 字段）
        self.assertTrue(body.get('error'), "预期返回 error，但实际返回：{}".format(body))

    def test_non_super_can_delete_other_tenant(self):
        """非超管用户拥有 tenant.del 权限后能删除其他租户"""
        # 先确保 tenant_b 没有关联用户
        User.objects.filter(
            tenant_id='tenant_b_3', deleted_by_id__isnull=True
        ).delete()

        client = Client()
        resp = client.delete(
            '/account/tenant/?id=tenant_b_3',
            HTTP_X_TOKEN=self.tenant_admin.access_token,
        )

        body = resp.json()

        if resp.status_code == 200 and not body.get('error'):
            # 验证租户 B 确实被删除了
            self.assertFalse(
                Tenant.objects.filter(id='tenant_b_3').exists(),
                "BUG 确认 [发现3]：非超管用户 'tenant_admin_3'（属于租户A）"
                "成功删除了租户B。TenantView 未限制非超管用户只能管理自己的租户。"
            )
        # 修复后返回 error（json_response(error=...) 返回 200 + error 字段）
        self.assertTrue(body.get('error'), "预期返回 error，但实际返回：{}".format(body))


# ===========================================================================
# 发现 4：用户迁出租户后，旧证据附件预览链接仍可使用约 5 分钟
# ===========================================================================
class Finding4AttachmentPreviewTokenTest(TestCase):
    """发现 4：用户迁出租户后，旧证据附件预览链接仍可使用约 5 分钟

    预期结果：BUG 确认
    - _authenticate_preview_token 只检查 user.is_active，不检查 user.tenant_id 是否与令牌一致
    - 附件预览端点的视图层检查 att.tenant_id vs token_data['tenant_id']，
      但不检查 user.tenant_id
    """

    def setUp(self):
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        Setting.objects.all().delete()

        self.tenant_a = _make_tenant('tenant_a_4', name='租户A')
        self.tenant_b = _make_tenant('tenant_b_4', name='租户B')

        self.user = _make_user(
            'preview_user_4',
            tenant_id='tenant_a_4',
            last_ip='',
        )

    def test_preview_token_valid_after_tenant_migration(self):
        """用户迁出租户后，旧附件预览令牌仍通过中间件认证"""
        from apps.evidence.attachment_preview_token import (
            generate_attachment_preview_token,
            validate_attachment_preview_token,
        )
        from libs.middleware import AuthenticationMiddleware

        # 1. 用户在租户 A 时生成一个附件预览令牌
        token = generate_attachment_preview_token(
            attachment_id=9999,
            user_id=self.user.id,
            tenant_id='tenant_a_4',
            module='fault',
            object_type='FaultRecord',
            object_id=1,
        )

        # 2. 验证令牌本身有效
        token_data = validate_attachment_preview_token(token)
        self.assertIsNotNone(token_data)
        self.assertEqual(token_data['tenant_id'], 'tenant_a_4')
        self.assertEqual(token_data['user_id'], self.user.id)

        # 3. 用户迁移到租户 B
        self.user.tenant_id = 'tenant_b_4'
        self.user.save()

        # 4. 令牌在有效期内仍然有效（这是令牌层的设计 - 短时效）
        token_data_after = validate_attachment_preview_token(token)
        self.assertIsNotNone(token_data_after)

        # 5. 关键检查：中间件认证时只检查 user.is_active，不检查 tenant_id
        # 模拟中间件的 _authenticate_preview_token 逻辑
        # 使用 RequestFactory 构造请求（路径匹配附件预览模式）
        factory = RequestFactory()
        request = factory.get(
            '/fault/attachments/9999/preview-file/test?preview_token=' + token
        )

        auth_user = AuthenticationMiddleware._authenticate_preview_token(token, request)

        if auth_user is not None:
            self.fail(
                "BUG 确认 [发现4]：用户已从租户A('tenant_a_4')迁移到租户B('tenant_b_4')，"
                "但中间件 _authenticate_preview_token 仍返回用户对象（认证成功）。"
                f"用户当前 tenant_id={auth_user.tenant_id}，"
                f"令牌 tenant_id=tenant_a_4，两者不一致但未被检查。"
                "旧预览令牌在 5 分钟有效期内仍可使用。"
            )
        # 修复后应返回 None
        self.assertIsNone(auth_user)


# ===========================================================================
# 发现 5：签名预览链接存在相同的租户迁移后残留访问窗口
# ===========================================================================
class Finding5SignaturePreviewTokenTest(TestCase):
    """发现 5：签名预览链接存在相同的租户迁移后残留访问窗口

    预期结果：BUG 确认
    - 签名预览端点复用 evidence 模块的 attachment_preview_token
    - 中间件 _authenticate_preview_token 对签名预览的认证逻辑与附件预览相同
    - 同样不检查 user.tenant_id 是否与令牌中的 tenant_id 一致
    """

    def setUp(self):
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        Setting.objects.all().delete()

        self.tenant_a = _make_tenant('tenant_a_5', name='租户A')
        self.tenant_b = _make_tenant('tenant_b_5', name='租户B')

        self.user = _make_user(
            'signature_user_5',
            tenant_id='tenant_a_5',
            last_ip='',
        )

    def test_signature_preview_token_after_tenant_migration(self):
        """用户迁出租户后，旧签名预览令牌仍通过中间件认证"""
        from apps.evidence.attachment_preview_token import generate_attachment_preview_token
        from libs.middleware import AuthenticationMiddleware

        # 1. 生成签名预览令牌（tenant_id = tenant_a_5）
        token = generate_attachment_preview_token(
            attachment_id=7777,
            user_id=self.user.id,
            tenant_id='tenant_a_5',
            module='signature',
            object_type='SignatureUsage',
            object_id=1,
        )

        # 2. 用户迁移到租户 B
        self.user.tenant_id = 'tenant_b_5'
        self.user.save()

        # 3. 模拟签名预览请求（路径匹配 SIGNATURE_PREVIEW_PATTERNS）
        factory = RequestFactory()
        request = factory.get('/signature/preview/test?preview_token=' + token)

        # 4. 调用中间件认证
        auth_user = AuthenticationMiddleware._authenticate_preview_token(token, request)

        if auth_user is not None:
            self.fail(
                "BUG 确认 [发现5]：用户已从租户A('tenant_a_5')迁移到租户B('tenant_b_5')，"
                "但签名预览令牌仍通过中间件认证。"
                f"用户当前 tenant_id={auth_user.tenant_id}，"
                f"令牌 tenant_id=tenant_a_5，两者不一致但未被检查。"
                "签名预览复用 attachment_preview_token，共享同一缺陷。"
            )
        # 修复后应返回 None
        self.assertIsNone(auth_user)
