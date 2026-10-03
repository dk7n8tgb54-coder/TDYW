# -*- coding: utf-8 -*-
"""升级编号契约测试（2026-10 编号回归）。

0021 曾删除 upgrade_no；本文件固化 2026-10 恢复编号后的新契约：
- 编号规则：SJ+创建日期+当日四位序号，当日序号跨租户共享（对齐故障 GZ/运行记录 YX）；
- 软删除记录的编号不回收复用；
- 创建服务/正式 API 创建入口自动分配编号；序号耗尽返回业务错误；
- (tenant_id, upgrade_no) 唯一约束兜底；序列化器与 Excel 导出携带编号。
"""
import json
import uuid

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from apps.utils.test_helpers import (
    make_upgrade_no, make_user, make_client, setup_test_env,
)
from apps.upgrade.models import UpgradeRecord
from apps.upgrade.exporters import EXCEL_COLUMNS
from apps.upgrade.services.record_service import (
    RecordService, UpgradeNoExhausted, generate_upgrade_no,
)
from apps.equipment_lifecycle.tests.base import make_system


def today_prefix():
    return 'SJ' + timezone.now().date().strftime('%Y%m%d') + '-'


def make_linked_system(user, **kwargs):
    """创建与用户同租户的系统档案（升级记录挂接用），system_code 默认唯一"""
    if 'system_code' not in kwargs:
        kwargs['system_code'] = f'SYS-{uuid.uuid4().hex[:8]}'
    return make_system(user, tenant_id=user.tenant_id, **kwargs)


def upgrade_data(**overrides):
    data = {
        'title': f'升级-{uuid.uuid4().hex[:6]}',
        'system': None,
        'upgrade_type': '功能升级',
        'upgrade_time': '2026-01-01 10:00:00',
        'status': '处理中', 'owner': '负责人',
        'upgrade_content': '升级内容描述',
    }
    data.update(overrides)
    return data


class GenerateUpgradeNoTest(TestCase):
    """generate_upgrade_no 编号规则（跨租户当日序号，口径同故障编号）"""

    def _fixture(self, no, tenant_id='tenant_a', **kwargs):
        return UpgradeRecord.objects.create(
            tenant_id=tenant_id, upgrade_no=no, title='夹具',
            upgrade_type='功能升级', created_by=self.user, **kwargs)

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('upg_no_gen', [])

    def test_first_no_of_today(self):
        self.assertEqual(generate_upgrade_no(), today_prefix() + '0001')

    def test_max_valid_suffix_plus_one(self):
        self._fixture(today_prefix() + '0007')
        self.assertEqual(generate_upgrade_no(), today_prefix() + '0008')

    def test_cross_tenant_sequence_shared(self):
        """跨租户共享当日序号：其他租户已占用的序号不被本租户复用"""
        self._fixture(today_prefix() + '0003', tenant_id='tenant_other')
        self.assertEqual(generate_upgrade_no(), today_prefix() + '0004')

    def test_invalid_suffixes_ignored(self):
        """非四位数字后缀不参与取最大（缺口不回填、脏数据不炸生成）"""
        self._fixture(today_prefix() + '0005')
        self._fixture(today_prefix() + '0012x')
        self._fixture(today_prefix() + '099')
        self.assertEqual(generate_upgrade_no(), today_prefix() + '0006')

    def test_soft_deleted_no_not_reused(self):
        """软删除记录的编号计入取最大，编号不回收复用"""
        record = self._fixture(today_prefix() + '0002')
        record.is_deleted = True
        record.save(update_fields=['is_deleted'])
        self.assertEqual(generate_upgrade_no(), today_prefix() + '0003')

    def test_exhausted_raises(self):
        self._fixture(today_prefix() + '9999')
        with self.assertRaises(UpgradeNoExhausted):
            generate_upgrade_no()

    def test_other_dates_do_not_interfere(self):
        """非当日前缀（含历史回填编号）不影响当日序号"""
        self._fixture('SJ20260101-9999')
        self.assertEqual(generate_upgrade_no(), today_prefix() + '0001')


class UpgradeNoConstraintTest(TestCase):
    """(tenant_id, upgrade_no) 唯一约束兜底"""

    def setUp(self):
        self.user = make_user('upg_no_uniq', [])

    def test_duplicate_no_in_same_tenant_rejected(self):
        UpgradeRecord.objects.create(
            tenant_id='t', upgrade_no='SJ20260101-0001', title='A',
            upgrade_type='功能升级', created_by=self.user)
        with self.assertRaises(IntegrityError):
            UpgradeRecord.objects.create(
                tenant_id='t', upgrade_no='SJ20260101-0001', title='B',
                upgrade_type='功能升级', created_by=self.user)

    def test_same_no_in_different_tenants_allowed_by_db(self):
        """约束为租户级：跨租户不冲突（全局唯一由生成逻辑保证）"""
        UpgradeRecord.objects.create(
            tenant_id='t1', upgrade_no='SJ20260101-0001', title='A',
            upgrade_type='功能升级', created_by=self.user)
        UpgradeRecord.objects.create(
            tenant_id='t2', upgrade_no='SJ20260101-0001', title='B',
            upgrade_type='功能升级', created_by=self.user)


class CreateRecordAssignsNoTest(TestCase):
    """创建服务与正式 API 创建入口自动分配编号"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('upg_no_create', ['upgrade.upgrade.view', 'upgrade.upgrade.add'])
        self.client = make_client(self.user)
        self.system = make_linked_system(self.user)

    def test_service_assigns_today_no(self):
        from types import SimpleNamespace
        form = SimpleNamespace(
            title='编号分配', system=self.system.id, upgrade_type='功能升级',
            upgrade_time='2026-01-01 10:00:00', status='处理中', owner='李四',
            upgrade_content='升级内容',
        )
        record, error = RecordService.create_record(self.user, form)
        self.assertIsNone(error, f'创建失败: {error}')
        self.assertTrue(record.upgrade_no.startswith(today_prefix()))
        self.assertRegex(record.upgrade_no, r'^SJ\d{8}-\d{4}$')

    def test_service_sequence_continues(self):
        from types import SimpleNamespace
        UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, upgrade_no=today_prefix() + '0005',
            title='已有', upgrade_type='功能升级', created_by=self.user)
        form = SimpleNamespace(
            title='编号续接', system=self.system.id, upgrade_type='功能升级',
            upgrade_time='2026-01-01 10:00:00', status='处理中', owner='李四',
            upgrade_content='升级内容',
        )
        record, error = RecordService.create_record(self.user, form)
        self.assertIsNone(error)
        self.assertEqual(record.upgrade_no, today_prefix() + '0006')

    def test_service_exhausted_returns_business_error(self):
        from types import SimpleNamespace
        UpgradeRecord.objects.create(
            tenant_id=self.user.tenant_id, upgrade_no=today_prefix() + '9999',
            title='占满', upgrade_type='功能升级', created_by=self.user)
        form = SimpleNamespace(
            title='溢出', system=self.system.id, upgrade_type='功能升级',
            upgrade_time='2026-01-01 10:00:00', status='处理中', owner='李四',
            upgrade_content='升级内容',
        )
        record, error = RecordService.create_record(self.user, form)
        self.assertIsNone(record)
        self.assertIn('已达上限', error)
        self.assertFalse(UpgradeRecord.objects.filter(title='溢出').exists())

    def test_api_create_returns_upgrade_no(self):
        resp = self.client.post('/upgrade/records/create/',
            data=json.dumps(upgrade_data(system=self.system.id)),
            content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'))
        # json_response 对 dict 载荷包装为 {error, data}
        payload = body.get('data') or body
        self.assertTrue(payload['upgrade_no'].startswith(today_prefix()))
        record = UpgradeRecord.objects.get(pk=payload['id'])
        self.assertEqual(record.upgrade_no, payload['upgrade_no'])


class SerializerExportNoTest(TestCase):
    """序列化器与导出列携带编号"""

    def setUp(self):
        self.user = make_user('upg_no_ser', [])

    def test_list_and_detail_view_contain_upgrade_no(self):
        record = UpgradeRecord.objects.create(
            tenant_id='t', upgrade_no='SJ20260101-0042', title='序列化',
            upgrade_type='功能升级', created_by=self.user)
        from apps.upgrade.serializers import UpgradeRecordSerializer
        list_view = UpgradeRecordSerializer.to_list_view(record)
        detail_view = UpgradeRecordSerializer.to_detail_view(record)
        for view in (list_view, detail_view):
            self.assertEqual(view['upgrade_no'], 'SJ20260101-0042')

    def test_export_first_column_is_upgrade_no(self):
        self.assertEqual(EXCEL_COLUMNS[0], ('upgrade_no', '编号'))
