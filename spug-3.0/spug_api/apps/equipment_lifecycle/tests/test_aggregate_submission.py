# -*- coding: utf-8 -*-
"""系统新增/编辑聚合提交与扩展信息固定字段稳定契约测试。

覆盖：一次提交（{"system": {...}} 结构化载荷）、扩展信息固定字段
（callsign 呼号 / geo_coordinate 安装经纬度 / work_frequency 工作频率，
均选填）的新增/编辑/详情回显、平铺与聚合两种载荷等价、
已下线的 custom_fields / config_values / components 键随载荷被忽略、
经纬度格式校验、审计留痕。
"""
from django.test import TestCase

from apps.equipment_lifecycle.models import LifecycleSystem
from apps.logs.models import AuditLog

from apps.equipment_lifecycle.tests.base import (
    ALL_SYSTEM_PERMS,
    make_client, make_system, make_user, system_payload,
)

URL = '/equipment-lifecycle/systems'


class ExtendedFieldsCreateTest(TestCase):
    def setUp(self):
        self.admin = make_user('ext_admin', ALL_SYSTEM_PERMS, tenant_id='t9')
        self.client = make_client(self.admin)

    def test_flat_payload_with_extended_fields(self):
        """平铺载荷：呼号/工作频率选填，填写后随创建落库并可回显。"""
        payload = system_payload(callsign='XZ5792', work_frequency='438.500MHz')
        resp = self.client.post(URL + '/', payload, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        data = resp.json()['data']
        self.assertEqual(data['callsign'], 'XZ5792')
        self.assertEqual(data['work_frequency'], '438.500MHz')
        self.assertEqual(data['geo_coordinate'], '121.5,37.5')

    def test_extended_fields_optional(self):
        """呼号/工作频率缺省时落空串，不阻断创建。"""
        payload = system_payload()
        payload.pop('callsign')
        payload.pop('work_frequency')
        resp = self.client.post(URL + '/', payload, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(resp.json()['data']['callsign'], '')

    def test_aggregate_payload_with_extended_fields(self):
        """结构化载荷 {"system": {...}}：扩展信息随聚合提交落库。"""
        payload = {'system': system_payload(
            callsign='XZ5793', work_frequency='118-137MHz')}
        resp = self.client.post(URL + '/', payload, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        system = LifecycleSystem.objects.get(
            tenant_id='t9', system_code=resp.json()['data']['system_code'])
        self.assertEqual(system.callsign, 'XZ5793')
        self.assertEqual(system.work_frequency, '118-137MHz')
        # 审计留痕（变更历史已下线，留痕由业务审计承载）
        self.assertTrue(AuditLog.objects.filter(
            tenant_id='t9', action='create', target_type='el_system',
            target_id=str(system.id)).exists())

    def test_deprecated_payload_keys_ignored(self):
        """已下线的 custom_fields / config_values / components 键被忽略，
        不再产生自定义字段数据（模型已删除）。"""
        payload = system_payload(
            custom_fields=[{'client_key': 't1', 'name': '天线高度', 'value': '1'}],
            config_values={'1': 'x'},
            components=[],
        )
        resp = self.client.post(URL + '/', payload, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(
            LifecycleSystem.objects.filter(tenant_id='t9').count(), 1)

    def test_geo_coordinate_validation(self):
        payload = system_payload(geo_coordinate='200,37')
        resp = self.client.post(URL + '/', payload, content_type='application/json')
        self.assertIn('经纬度', resp.json()['error'])

    def test_install_enable_time_date_only(self):
        """安装/启用时间只需日期：按日期落库并回显（不含时分）；
        兼容历史调用仍提交带时分的值，时间部分丢弃。"""
        payload = system_payload(install_time='2026-03-01', enable_time='2026-03-10')
        resp = self.client.post(URL + '/', payload, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        data = resp.json()['data']
        self.assertEqual(data['install_time'], '2026-03-01')
        self.assertEqual(data['enable_time'], '2026-03-10')
        legacy = system_payload(install_time='2026-03-01 08:00',
                                enable_time='2026-03-10T09:30')
        resp = self.client.post(URL + '/', legacy, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(resp.json()['data']['install_time'], '2026-03-01')
        # 非法日期被拒
        bad = system_payload(install_time='03/01/2026')
        resp = self.client.post(URL + '/', bad, content_type='application/json')
        self.assertIn('YYYY-MM-DD', resp.json()['error'])


class ExtendedFieldsUpdateTest(TestCase):
    def setUp(self):
        self.admin = make_user('extu_admin', ALL_SYSTEM_PERMS, tenant_id='t8')
        self.client = make_client(self.admin)
        self.system = make_system(self.admin, tenant_id='t8', system_code='ED-001')

    def test_update_extended_fields_aggregate(self):
        """聚合编辑：呼号/工作频率与固定字段一次提交生效。"""
        payload = {'system': system_payload(
            name='烟台中心站通信系统',
            manufacturer='某通信设备厂',
            install_unit='安装一队',
            use_unit='运行一科',
            install_time='2026-01-01',
            enable_time='2026-02-01',
            responsible_user_name='张三',
            callsign='XZ9001', work_frequency='156.800MHz', geo_coordinate=''),
        }
        resp = self.client.put(f'{URL}/{self.system.id}/', payload,
                               content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.system.refresh_from_db()
        self.assertEqual(self.system.callsign, 'XZ9001')
        self.assertEqual(self.system.work_frequency, '156.800MHz')
        # 审计记录变更字段名（含扩展信息字段）
        log = AuditLog.objects.filter(
            tenant_id='t8', target_type='el_system', action='update',
            target_id=str(self.system.id)).latest('id')
        self.assertIn('呼号', log.detail)
        self.assertIn('工作频率', log.detail)

    def test_detail_returns_extended_fields(self):
        """详情接口回显扩展信息固定字段。"""
        self.system.callsign = 'XZ0001'
        self.system.work_frequency = '243.000MHz'
        self.system.save()
        resp = self.client.get(f'{URL}/{self.system.id}/')
        self.assertFalse(resp.json().get('error'), resp.content)
        data = resp.json()['data']
        self.assertEqual(data['callsign'], 'XZ0001')
        self.assertEqual(data['work_frequency'], '243.000MHz')
        self.assertNotIn('config_fields', data)

    def test_export_includes_extended_fields(self):
        """系统列表导出含呼号/工作频率列。"""
        self.system.callsign = 'XZ0002'
        self.system.work_frequency = '121.500MHz'
        self.system.save()
        resp = self.client.get(f'{URL}/export/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('呼号'.encode('utf-8'), resp.content)
        self.assertIn('工作频率'.encode('utf-8'), resp.content)
        self.assertIn('XZ0002'.encode('utf-8'), resp.content)
