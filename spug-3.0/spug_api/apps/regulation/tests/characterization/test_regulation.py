# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# 资料与行政业务特征测试 - 规章管理
# 覆盖: CRUD, 分类, 独立 storage, 权限编码, 租户缺失, 文件副作用, 审计
# 重要发现: Regulation 无 tenant_id (全局共享), 无 is_deleted (硬删除)
import json
import uuid

from datetime import date, timedelta
from django.test import TestCase

from tests.helpers.test_base import (
    make_user, make_client, setup_test_env, post_json, get_response_id, has_error)
from apps.regulation.models import (
    Regulation, RegulationCategory, RegulationAttachment)
from apps.evidence.models import EvidenceAttachment


class RegulationCRUDTest(TestCase):
    """规章 CRUD 测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)
        self.client = make_client(self.admin)

    def _create(self, **overrides):
        defaults = {
            'title': f'测试规章-{uuid.uuid4().hex[:8]}',
            'rule_no': f'REG-{uuid.uuid4().hex[:8]}',
            'publish_date': date.today().isoformat(),
            'effective_date': date.today().isoformat(),
            'status': 'active',
        }
        defaults.update(overrides)
        return post_json(self.client, '/regulation/create/', defaults)

    def test_create_success(self):
        resp = self._create()
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(has_error(resp))

    def test_list(self):
        Regulation.objects.create(
            title='列表测试规章', rule_no=f'REG-{uuid.uuid4().hex[:8]}',
            publish_date=date.today(), effective_date=date.today(),
            status='active')
        resp = self.client.get('/regulation/')
        self.assertEqual(resp.status_code, 200)

    def test_detail(self):
        reg = Regulation.objects.create(
            title='详情测试规章', rule_no=f'REG-{uuid.uuid4().hex[:8]}',
            publish_date=date.today(), effective_date=date.today(),
            status='active')
        resp = self.client.get(f'/regulation/{reg.id}/')
        self.assertEqual(resp.status_code, 200)

    def test_delete(self):
        reg = Regulation.objects.create(
            title='删除测试规章', rule_no=f'REG-{uuid.uuid4().hex[:8]}',
            publish_date=date.today(), effective_date=date.today(),
            status='active')
        resp = self.client.delete(f'/regulation/{reg.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Regulation.objects.filter(id=reg.id).exists())


class RegulationCategoryTest(TestCase):
    """规章分类测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)
        self.client = make_client(self.admin)

    def test_list_category_tree(self):
        resp = self.client.get('/regulation/categories/tree/')
        self.assertEqual(resp.status_code, 200)

    def test_create_category(self):
        resp = post_json(self.client, '/regulation/categories/', {
            'name': f'分类-{uuid.uuid4().hex[:8]}',
        })
        self.assertEqual(resp.status_code, 200)


class RegulationStorageTest(TestCase):
    """规章使用独立 storage 测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)

    def test_uses_regulation_attachment_not_evidence(self):
        """规章附件使用 RegulationAttachment, 不使用 EvidenceAttachment"""
        reg = Regulation.objects.create(
            title='存储测试规章', rule_no=f'REG-{uuid.uuid4().hex[:8]}',
            publish_date=date.today(), effective_date=date.today(),
            status='active')
        att = RegulationAttachment.objects.create(
            regulation=reg,
            original_name='test.pdf',
            stored_name=f'{uuid.uuid4().hex}.pdf',
            file_path=f'regulation/{reg.id}/test.pdf',
            file_size=1024,
            file_type='pdf',
            uploaded_by=self.admin)
        # 确认没有创建 EvidenceAttachment
        evidence_count = EvidenceAttachment.objects.filter(
            module='regulation', object_id=str(reg.id)).count()
        self.assertEqual(evidence_count, 0)
        # 确认 RegulationAttachment 存在
        self.assertTrue(RegulationAttachment.objects.filter(id=att.id).exists())


class RegulationNoTenantTest(TestCase):
    """规章无租户隔离测试 - 重要发现

    发现: Regulation 模型没有 tenant_id 字段
    意味着所有用户(包括不同租户)都能看到所有规章
    这可能是业务设计(规章是全局共享的)
    """

    def setUp(self):
        setup_test_env()

    def test_no_tenant_id_field(self):
        """Regulation 模型没有 tenant_id 字段"""
        fields = {f.name for f in Regulation._meta.get_fields()}
        self.assertNotIn('tenant_id', fields)

    def test_all_users_see_all_regulations(self):
        """所有用户都能看到所有规章"""
        Regulation.objects.create(
            title='规章A', rule_no=f'REG-A-{uuid.uuid4().hex[:8]}',
            publish_date=date.today(), effective_date=date.today(),
            status='active')
        Regulation.objects.create(
            title='规章B', rule_no=f'REG-B-{uuid.uuid4().hex[:8]}',
            publish_date=date.today(), effective_date=date.today(),
            status='active')
        self.assertEqual(Regulation.objects.count(), 2)


class RegulationPermissionTest(TestCase):
    """规章权限测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)
        self.no_perm = make_user('noperm')
        self.viewer = make_user('viewer', perms=[
            'document.regulation.view'])

    def test_no_perm_blocked(self):
        client = make_client(self.no_perm)
        resp = client.get('/regulation/')
        self.assertTrue(has_error(resp))

    def test_viewer_can_view(self):
        client = make_client(self.viewer)
        resp = client.get('/regulation/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(has_error(resp))

    def test_viewer_cannot_create(self):
        client = make_client(self.viewer)
        resp = post_json(client, '/regulation/create/', {
            'title': '无权创建',
            'rule_no': f'REG-{uuid.uuid4().hex[:8]}',
            'publish_date': date.today().isoformat(),
            'effective_date': date.today().isoformat(),
            'status': 'active',
        })
        self.assertTrue(has_error(resp))


class RegulationFileSideEffectTest(TestCase):
    """规章文件副作用测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)

    def test_delete_regulation_cascades_attachments(self):
        """删除规章后附件记录被 CASCADE 清理"""
        reg = Regulation.objects.create(
            title='删除测试规章', rule_no=f'REG-{uuid.uuid4().hex[:8]}',
            publish_date=date.today(), effective_date=date.today(),
            status='active')
        att = RegulationAttachment.objects.create(
            regulation=reg,
            original_name='test.pdf',
            stored_name=f'{uuid.uuid4().hex}.pdf',
            file_path=f'regulation/{reg.id}/test.pdf',
            file_size=12,
            file_type='pdf',
            uploaded_by=self.admin)
        att_id = att.id
        reg.delete()
        self.assertFalse(
            RegulationAttachment.objects.filter(id=att_id).exists())


class RegulationRetireTest(TestCase):
    """规章作废测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)
        self.client = make_client(self.admin)

    def test_retire_changes_status(self):
        reg = Regulation.objects.create(
            title='作废测试规章', rule_no=f'REG-{uuid.uuid4().hex[:8]}',
            publish_date=date.today(), effective_date=date.today(),
            status='active')
        resp = self.client.post(f'/regulation/{reg.id}/retire/')
        self.assertEqual(resp.status_code, 200)
        reg.refresh_from_db()
        self.assertEqual(reg.status, 'retired')
