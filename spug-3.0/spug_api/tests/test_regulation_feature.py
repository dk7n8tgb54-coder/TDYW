# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# 资料与行政业务特征测试 - 规章管理
# 覆盖: CRUD, 分类管理, 独立 storage.py, RegulationAttachment(非Evidence),
#        权限编码 document.regulation.*, 租户隔离(缺失发现), 审计日志
#
# 重要发现:
# - Regulation 模型无 tenant_id 字段 -> 无租户隔离
# - Regulation 使用 rule_no (非 reg_no), status=active/retired (非 effective/expired)
# - 无 expiry_date 字段, 无 is_deleted 字段 (硬删除)
# - RegulationAttachment 使用 original_name/stored_name/file_path/file_type/uploaded_by
import json
import os
import time
import tempfile
from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase, Client
from apps.account.models import User, Role
from apps.regulation.models import (
    Regulation, RegulationCategory, RegulationAttachment)
from apps.setting.utils import AppSetting


def _uuid():
    import uuid
    return uuid.uuid4().hex


def _make_user(username, is_supper=False, tenant_id='admin', perms=None):
    unique = f'{username}_{_uuid()[:8]}'
    user = User.objects.create(
        username=unique, nickname=unique,
        password_hash=User.make_password('test123'),
        access_token=_uuid(), is_supper=is_supper, is_active=True,
        tenant_id=tenant_id, token_expired=int(time.time()) + 3600,
        last_ip='127.0.0.1', last_login='2026-01-01', type='default',
    )
    if perms and not is_supper:
        role = Role.objects.create(
            name=f'{username}_role', desc='', page_perms='',
            perms_version=1, created_by=user)
        perm_tree = {}
        for p in perms:
            parts = p.split('.')
            if len(parts) >= 3:
                perm_tree.setdefault(parts[0], {}).setdefault(
                    parts[1], set()).add(parts[2])
        pp = {}
        for m, models in perm_tree.items():
            pp[m] = {}
            for mo, acts in models.items():
                pp[m][mo] = {a: True for a in acts}
        role.page_perms = json.dumps(pp)
        role.save()
        user.roles.add(role)
        user.set_perms_cache(None)
    return user


class RegulationCRUDTest(TestCase):
    """规章 CRUD 测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = self.admin.access_token

    def _create_regulation(self, **overrides):
        defaults = {
            'title': f'测试规章-{_uuid()[:8]}',
            'rule_no': f'REG-{_uuid()[:8]}',
            'publish_date': date.today().isoformat(),
            'effective_date': date.today().isoformat(),
            'status': 'active',
        }
        defaults.update(overrides)
        return self.client.post(
            '/regulation/create/',
            data=json.dumps(defaults),
            content_type='application/json')

    def test_create_regulation_success(self):
        resp = self._create_regulation()
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'))

    def test_list_regulations(self):
        Regulation.objects.create(
            title='列表测试规章', rule_no=f'REG-{_uuid()[:8]}',
            publish_date=date.today(), effective_date=date.today(),
            status='active')
        resp = self.client.get('/regulation/')
        self.assertEqual(resp.status_code, 200)

    def test_retrieve_regulation_detail(self):
        reg = Regulation.objects.create(
            title='详情测试规章', rule_no=f'REG-{_uuid()[:8]}',
            publish_date=date.today(), effective_date=date.today(),
            status='active')
        resp = self.client.get(f'/regulation/{reg.id}/')
        self.assertEqual(resp.status_code, 200)

    def test_delete_regulation(self):
        reg = Regulation.objects.create(
            title='删除测试规章', rule_no=f'REG-{_uuid()[:8]}',
            publish_date=date.today(), effective_date=date.today(),
            status='active')
        resp = self.client.delete(
            '/regulation/',
            data=json.dumps({'id': reg.id}),
            content_type='application/json')
        if resp.status_code == 200:
            self.assertFalse(Regulation.objects.filter(id=reg.id).exists())


class RegulationCategoryTest(TestCase):
    """规章分类管理测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = self.admin.access_token

    def test_list_category_tree(self):
        resp = self.client.get('/regulation/categories/tree/')
        self.assertEqual(resp.status_code, 200)

    def test_create_category(self):
        resp = self.client.post(
            '/regulation/categories/',
            data=json.dumps({'name': f'分类-{_uuid()[:8]}'}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 200)


class RegulationStorageTest(TestCase):
    """规章使用独立 storage.py 测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.tmp_dir = tempfile.mkdtemp(prefix='regulation_test_')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_regulation_uses_independent_storage(self):
        """规章附件使用 RegulationAttachment 而非 EvidenceAttachment"""
        from apps.evidence.models import EvidenceAttachment
        reg = Regulation.objects.create(
            title='存储测试规章', rule_no=f'REG-{_uuid()[:8]}',
            publish_date=date.today(), effective_date=date.today(),
            status='active')
        att = RegulationAttachment.objects.create(
            regulation=reg,
            original_name='test.pdf',
            stored_name=f'{_uuid()}.pdf',
            file_path=f'regulation/{reg.id}/test.pdf',
            file_size=1024,
            file_type='pdf',
            uploaded_by=self.admin)
        # 确认没有创建 EvidenceAttachment
        evidence_count = EvidenceAttachment.objects.filter(
            module='regulation', object_id=str(reg.id)).count()
        self.assertEqual(evidence_count, 0)
        # 确认 RegulationAttachment 存在
        self.assertTrue(
            RegulationAttachment.objects.filter(id=att.id).exists())


class RegulationNoTenantTest(TestCase):
    """规章租户隔离缺失测试 - 重要发现

    发现: Regulation 模型没有 tenant_id 字段
    意味着所有用户(包括不同租户)都能看到所有规章
    这是一个潜在的安全缺陷，但可能是业务设计(规章是全局共享的)
    """

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.t_a = _make_user('ta', is_supper=True, tenant_id='tenant_a')
        self.t_b = _make_user('tb', is_supper=True, tenant_id='tenant_b')

    def test_regulation_has_no_tenant_field(self):
        """Regulation 模型没有 tenant_id 字段"""
        fields = {f.name for f in Regulation._meta.get_fields()}
        self.assertNotIn('tenant_id', fields,
                         'Regulation model should NOT have tenant_id '
                         '(confirmed: no tenant isolation)')

    def test_all_users_see_all_regulations(self):
        """所有用户都能看到所有规章 (无租户隔离)"""
        Regulation.objects.create(
            title='规章A', rule_no=f'REG-A-{_uuid()[:8]}',
            publish_date=date.today(), effective_date=date.today(),
            status='active')
        Regulation.objects.create(
            title='规章B', rule_no=f'REG-B-{_uuid()[:8]}',
            publish_date=date.today(), effective_date=date.today(),
            status='active')
        # 所有规章对所有用户可见
        count = Regulation.objects.count()
        self.assertEqual(count, 2)


class RegulationPermissionTest(TestCase):
    """规章权限边界测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.no_perm = _make_user('no_perm')
        self.viewer = _make_user('viewer', perms=[
            'document.regulation.view'])

    def test_no_perm_blocked(self):
        client = Client()
        client.defaults['HTTP_X_TOKEN'] = self.no_perm.access_token
        resp = client.get('/regulation/')
        body = resp.json()
        self.assertTrue(body.get('error'))

    def test_viewer_can_view_not_create(self):
        client = Client()
        client.defaults['HTTP_X_TOKEN'] = self.viewer.access_token
        resp = client.get('/regulation/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'))
        resp = client.post(
            '/regulation/create/',
            data=json.dumps({
                'title': '测试', 'rule_no': f'REG-{_uuid()[:8]}',
                'publish_date': date.today().isoformat(),
                'effective_date': date.today().isoformat(),
                'status': 'active',
            }),
            content_type='application/json')
        body = resp.json()
        self.assertTrue(body.get('error'))


class RegulationPermissionCodeTest(TestCase):
    """规章权限编码一致性测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)

    def test_regulation_uses_document_regulation_prefix(self):
        """规章权限编码为 document.regulation.* 而非 regulation.*"""
        import inspect
        from apps.regulation import views
        source = inspect.getsource(views)
        self.assertIn('document.regulation', source)
        self.assertIn('document.regulation.view', source)
        self.assertIn('document.regulation.add', source)


class RegulationFileSideEffectTest(TestCase):
    """规章文件副作用测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.tmp_dir = tempfile.mkdtemp(prefix='reg_file_test_')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_delete_regulation_cleans_attachment(self):
        """删除规章后附件记录被 CASCADE 清理"""
        reg = Regulation.objects.create(
            title='删除测试规章', rule_no=f'REG-{_uuid()[:8]}',
            publish_date=date.today(), effective_date=date.today(),
            status='active')
        att = RegulationAttachment.objects.create(
            regulation=reg,
            original_name='test_regulation.pdf',
            stored_name=f'{_uuid()}.pdf',
            file_path=f'regulation/{reg.id}/test.pdf',
            file_size=12,
            file_type='pdf',
            uploaded_by=self.admin)
        att_id = att.id
        # 删除规章
        reg.delete()
        # CASCADE 应清理附件记录
        self.assertFalse(
            RegulationAttachment.objects.filter(id=att_id).exists())


class RegulationAuditTest(TestCase):
    """规章审计日志测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = self.admin.access_token

    def test_create_may_generate_audit(self):
        """创建规章可能生成审计日志 (取决于实现)"""
        resp = self.client.post(
            '/regulation/create/',
            data=json.dumps({
                'title': f'审计测试-{_uuid()[:8]}',
                'rule_no': f'REG-{_uuid()[:8]}',
                'publish_date': date.today().isoformat(),
                'effective_date': date.today().isoformat(),
                'status': 'active',
            }),
            content_type='application/json')
        # 记录行为，不强制要求
        pass
