# -*- coding: utf-8 -*-
"""设备位置（当前位置 + 位置变更历史）stable_contract 测试。

固化以下业务不变量：
1. 当前位置属于设备档案：建档可填写（含初始位置历史），普通编辑接口
   不接收位置字段，位置只能通过独立变更接口修改；
2. 位置历史只进不出：变更 = 封存旧有效时段 + 新建历史快照，历史记录
   与快照永不被修改或删除；同位置重复提交不产生重复历史；
3. 位置变更原子性：档案与历史同事务，任何一步失败整体回滚；
4. 并发安全：同设备并发位置变更至多一条有效记录（命名锁串行化）；
5. 权限与租户隔离：查看用 device.view，变更用 device.manage，全部
   租户隔离；篡改 device_id/tenant_id 参数无法越权。
"""
import json
import threading
from datetime import datetime
from unittest import mock

from django.db import DatabaseError, connections
from django.test import TestCase, TransactionTestCase, Client

from apps.utils.test_helpers import make_user, make_client, setup_test_env
from apps.logs.models import AuditLog

from apps.equipment_lifecycle.models import LifecycleDevice, LifecycleDeviceLocation

DEVICE_URL = '/equipment-lifecycle/devices/'
CHANGE_URL = '/equipment-lifecycle/devices/location-change/'
HISTORY_URL = '/equipment-lifecycle/devices/location-history/'

PERM_DEVICE_VIEW = 'equipment_lifecycle.device.view'
PERM_DEVICE_MANAGE = 'equipment_lifecycle.device.manage'

LOCATION_A = '一号机房-A区-机柜03-机位12'
LOCATION_B = '二号机房-B区-机柜01-机位05'
LOCATION_C = '三号机房-C区-机柜02-机位08'


def make_device_record(tenant_id, user, sn, **overrides):
    data = dict(
        tenant_id=tenant_id, device_sn=sn, device_name='设备-' + sn,
        device_model='Model-A', current_status='1', created_by=user,
    )
    data.update(overrides)
    return LifecycleDevice.objects.create(**data)


def device_payload(sn='EL-LOC-001', **overrides):
    data = {
        'device_sn': sn,
        'device_name': '测向仪',
        'device_model': 'Model-B',
        'current_status': '1',
        'current_location': LOCATION_A,
    }
    data.update(overrides)
    return data


def change_payload(device_id, new_location=LOCATION_B, **overrides):
    data = {
        'device_id': device_id,
        'new_location': new_location,
        'change_type': 'relocation',
        'reason': '机房设备重新布置',
    }
    data.update(overrides)
    return data


def active_history(device_id):
    """当前有效位置记录（同设备至多一条）"""
    return LifecycleDeviceLocation.objects.filter(
        device_id=device_id, ended_at__isnull=True).first()


class DeviceCreateWithLocationTest(TestCase):
    """建档时当前位置的保存与初始位置历史"""

    def setUp(self):
        setup_test_env(self)
        self.manager = make_user('el_loc_create', [PERM_DEVICE_VIEW, PERM_DEVICE_MANAGE])
        self.c = make_client(self.manager)

    def test_create_with_location_saves_and_creates_initial_history(self):
        resp = self.c.post(DEVICE_URL, data=json.dumps(device_payload()),
                           content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['current_location'], LOCATION_A)

        device = LifecycleDevice.objects.get(device_sn='EL-LOC-001')
        self.assertEqual(device.current_location, LOCATION_A)
        histories = LifecycleDeviceLocation.objects.filter(device_id=device.id)
        self.assertEqual(histories.count(), 1)
        initial = histories.first()
        self.assertEqual(initial.change_type, 'initial')
        self.assertEqual(initial.old_location, '')
        self.assertEqual(initial.new_location, LOCATION_A)
        self.assertIsNone(initial.ended_at)
        self.assertEqual(initial.tenant_id, self.manager.tenant_id)

    def test_create_without_location_ok_no_history(self):
        resp = self.c.post(DEVICE_URL, data=json.dumps(device_payload(
            sn='EL-LOC-002', current_location='')),
            content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'))
        device = LifecycleDevice.objects.get(device_sn='EL-LOC-002')
        # 兼容存量语义：空位置存空字符串，不允许 NULL
        self.assertEqual(device.current_location, '')
        self.assertEqual(LifecycleDeviceLocation.objects.filter(device_id=device.id).count(), 0)

    def test_create_location_too_long_rejected(self):
        resp = self.c.post(DEVICE_URL, data=json.dumps(device_payload(
            sn='EL-LOC-003', current_location='位' * 201)),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertFalse(LifecycleDevice.objects.filter(device_sn='EL-LOC-003').exists())


class DeviceEditCannotChangeLocationTest(TestCase):
    """普通编辑接口不得静默修改当前位置；详情返回当前位置"""

    def setUp(self):
        setup_test_env(self)
        self.manager = make_user('el_loc_edit', [PERM_DEVICE_VIEW, PERM_DEVICE_MANAGE])
        self.c = make_client(self.manager)
        self.device = make_device_record(self.manager.tenant_id, self.manager,
                                         'EL-LOC-EDIT', current_location=LOCATION_A)

    def test_put_ignores_current_location(self):
        resp = self.c.put(DEVICE_URL, data=json.dumps({
            'id': self.device.id, 'device_name': '改名设备',
            'current_location': LOCATION_B, 'remark': '改备注'}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        self.device.refresh_from_db()
        self.assertEqual(self.device.device_name, '改名设备')
        self.assertEqual(self.device.current_location, LOCATION_A)
        self.assertEqual(LifecycleDeviceLocation.objects.filter(
            device_id=self.device.id).count(), 0)

    def test_detail_response_contains_current_location(self):
        body = self.c.get(DEVICE_URL, {'id': self.device.id}).json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['current_location'], LOCATION_A)


class DeviceLocationChangeTest(TestCase):
    """独立位置变更接口：主流程、校验、快照不可变、原子性、删除守卫"""

    def setUp(self):
        setup_test_env(self)
        self.manager = make_user('el_loc_change', [PERM_DEVICE_VIEW, PERM_DEVICE_MANAGE])
        self.c = make_client(self.manager)
        # 走建档接口创建，自带初始位置历史
        resp = self.c.post(DEVICE_URL, data=json.dumps(device_payload(sn='EL-LOC-M-001')),
                           content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        self.device = LifecycleDevice.objects.get(device_sn='EL-LOC-M-001')

    def test_change_a_to_b_full_chain(self):
        resp = self.c.post(CHANGE_URL, data=json.dumps(change_payload(self.device.id)),
                           content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'))

        self.device.refresh_from_db()
        self.assertEqual(self.device.current_location, LOCATION_B)
        self.assertIsNotNone(self.device.updated_at)
        self.assertEqual(self.device.updated_by_id, self.manager.id)

        # 旧时段（初始登记）已封存，新时段生效
        initial = LifecycleDeviceLocation.objects.get(
            device_id=self.device.id, change_type='initial')
        self.assertIsNotNone(initial.ended_at)
        current = active_history(self.device.id)
        self.assertIsNotNone(current)
        self.assertEqual(current.old_location, LOCATION_A)
        self.assertEqual(current.new_location, LOCATION_B)
        self.assertEqual(current.change_type, 'relocation')
        self.assertEqual(current.reason, '机房设备重新布置')
        self.assertEqual(current.tenant_id, self.manager.tenant_id)
        # 旧时段结束时间 = 新时段生效时间（半开区间衔接）
        self.assertEqual(initial.ended_at, current.effective_at)

        self.assertTrue(AuditLog.objects.filter(
            target_type='el_device_location', action='update',
            target_id=str(self.device.id)).exists())

    def test_change_with_custom_effective_at(self):
        resp = self.c.post(CHANGE_URL, data=json.dumps(change_payload(
            self.device.id, effective_at='2026-09-01 08:30:00')),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        current = active_history(self.device.id)
        self.assertEqual(current.effective_at, datetime(2026, 9, 1, 8, 30, 0))
        initial = LifecycleDeviceLocation.objects.get(
            device_id=self.device.id, change_type='initial')
        self.assertEqual(initial.ended_at, datetime(2026, 9, 1, 8, 30, 0))

    def test_change_default_effective_at_server_now(self):
        resp = self.c.post(CHANGE_URL, data=json.dumps(
            {'device_id': self.device.id, 'new_location': LOCATION_B, 'reason': '默认生效时间'}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        current = active_history(self.device.id)
        self.assertIsNotNone(current.effective_at)

    def test_change_type_correction_allowed(self):
        resp = self.c.post(CHANGE_URL, data=json.dumps(change_payload(
            self.device.id, change_type='correction', reason='录入位置有误')),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        self.assertEqual(active_history(self.device.id).change_type, 'correction')

    def test_change_type_invalid_rejected(self):
        for bad in ('initial', 'weird', ''):
            resp = self.c.post(CHANGE_URL, data=json.dumps(change_payload(
                self.device.id, change_type=bad)),
                content_type='application/json')
            self.assertTrue(resp.json().get('error'), f'change_type={bad!r} 应被拒绝')
        self.device.refresh_from_db()
        self.assertEqual(self.device.current_location, LOCATION_A)
        self.assertEqual(LifecycleDeviceLocation.objects.filter(
            device_id=self.device.id).count(), 1)

    def test_effective_at_invalid_format_rejected(self):
        resp = self.c.post(CHANGE_URL, data=json.dumps(change_payload(
            self.device.id, effective_at='2026/09/01 08:30')),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertEqual(active_history(self.device.id).new_location, LOCATION_A)

    def test_same_location_rejected_no_duplicate_history(self):
        resp = self.c.post(CHANGE_URL, data=json.dumps(change_payload(
            self.device.id, new_location=LOCATION_A)),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertEqual(LifecycleDeviceLocation.objects.filter(
            device_id=self.device.id).count(), 1)
        self.device.refresh_from_db()
        self.assertEqual(self.device.current_location, LOCATION_A)

    def test_reason_required_when_device_has_location(self):
        resp = self.c.post(CHANGE_URL, data=json.dumps(change_payload(
            self.device.id, reason='')),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.device.refresh_from_db()
        self.assertEqual(self.device.current_location, LOCATION_A)

    def test_first_entry_via_change_api_reason_optional(self):
        """存量设备无位置：通过变更接口首次登记，无需原因"""
        bare = make_device_record(self.manager.tenant_id, self.manager, 'EL-LOC-M-002')
        resp = self.c.post(CHANGE_URL, data=json.dumps(
            {'device_id': bare.id, 'new_location': LOCATION_B, 'change_type': 'relocation'}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        bare.refresh_from_db()
        self.assertEqual(bare.current_location, LOCATION_B)
        current = active_history(bare.id)
        self.assertEqual(current.old_location, '')
        self.assertEqual(current.new_location, LOCATION_B)

    def test_history_snapshot_immutable_across_changes(self):
        """连续变更：已保存的历史快照与时段不被后续变更修改"""
        self.c.post(CHANGE_URL, data=json.dumps(change_payload(
            self.device.id, new_location=LOCATION_B, reason='第一次搬迁')),
            content_type='application/json')
        self.c.post(CHANGE_URL, data=json.dumps(change_payload(
            self.device.id, new_location=LOCATION_C, reason='第二次搬迁')),
            content_type='application/json')

        histories = list(LifecycleDeviceLocation.objects.filter(
            device_id=self.device.id).order_by('effective_at'))
        self.assertEqual(len(histories), 3)  # initial + 两次变更
        first_change = histories[1]
        self.assertEqual(first_change.old_location, LOCATION_A)
        self.assertEqual(first_change.new_location, LOCATION_B)
        self.assertEqual(first_change.reason, '第一次搬迁')
        self.assertIsNotNone(first_change.ended_at)  # 已被 B→C 封存
        second_change = histories[2]
        self.assertEqual(second_change.old_location, LOCATION_B)
        self.assertEqual(second_change.new_location, LOCATION_C)
        self.assertEqual(second_change.reason, '第二次搬迁')
        self.assertIsNone(second_change.ended_at)
        # 时段衔接：B 时段结束 = C 时段生效
        self.assertEqual(first_change.ended_at, second_change.effective_at)

    def test_change_atomic_on_db_error(self):
        """历史创建失败时整体回滚：档案与旧时段保持原状"""
        with mock.patch.object(LifecycleDeviceLocation.objects, 'create',
                               side_effect=DatabaseError('模拟故障')):
            resp = self.c.post(CHANGE_URL, data=json.dumps(change_payload(self.device.id)),
                               content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.device.refresh_from_db()
        self.assertEqual(self.device.current_location, LOCATION_A)
        initial = LifecycleDeviceLocation.objects.get(
            device_id=self.device.id, change_type='initial')
        self.assertIsNone(initial.ended_at)
        self.assertEqual(LifecycleDeviceLocation.objects.filter(
            device_id=self.device.id).count(), 1)

    def test_device_with_location_history_cannot_be_deleted(self):
        resp = self.c.delete(f'{DEVICE_URL}?id={self.device.id}')
        self.assertTrue(resp.json().get('error'))
        self.assertTrue(LifecycleDevice.objects.filter(pk=self.device.id).exists())
        self.assertEqual(LifecycleDeviceLocation.objects.filter(
            device_id=self.device.id).count(), 1)

    def test_device_without_history_still_deletable(self):
        bare = make_device_record(self.manager.tenant_id, self.manager, 'EL-LOC-M-003')
        resp = self.c.delete(f'{DEVICE_URL}?id={bare.id}')
        self.assertFalse(resp.json().get('error'))
        self.assertFalse(LifecycleDevice.objects.filter(pk=bare.id).exists())


class DeviceLocationHistoryViewTest(TestCase):
    """位置历史查询：排序、字段、权限"""

    def setUp(self):
        setup_test_env(self)
        self.manager = make_user('el_loc_hist', [PERM_DEVICE_VIEW, PERM_DEVICE_MANAGE])
        self.c = make_client(self.manager)
        resp = self.c.post(DEVICE_URL, data=json.dumps(device_payload(sn='EL-LOC-H-001')),
                           content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        self.device = LifecycleDevice.objects.get(device_sn='EL-LOC-H-001')
        resp = self.c.post(CHANGE_URL, data=json.dumps(change_payload(self.device.id)),
                           content_type='application/json')
        self.assertFalse(resp.json().get('error'))

    def test_history_list_order_and_fields(self):
        resp = self.c.get(HISTORY_URL, {'device_id': self.device.id})
        body = resp.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['total'], 2)
        # 最新变更在前
        self.assertEqual(body['data']['data'][0]['new_location'], LOCATION_B)
        self.assertEqual(body['data']['data'][0]['old_location'], LOCATION_A)
        self.assertEqual(body['data']['data'][0]['change_type_text'], '位置搬迁')
        self.assertEqual(body['data']['data'][1]['change_type_text'], '初始登记')
        self.assertEqual(body['data']['data'][1]['old_location'], '')
        for item in body['data']['data']:
            self.assertIn('effective_at', item)
            self.assertIn('created_by_name', item)

    def test_history_requires_device_id(self):
        self.assertTrue(self.c.get(HISTORY_URL).json().get('error'))

    def test_history_nonexistent_device_rejected(self):
        resp = self.c.get(HISTORY_URL, {'device_id': 999999})
        self.assertTrue(resp.json().get('error'))

    def test_view_only_perm_can_view_history(self):
        viewer = make_user('el_loc_hist_v', [PERM_DEVICE_VIEW])
        body = make_client(viewer).get(HISTORY_URL, {'device_id': self.device.id}).json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['total'], 2)

    def test_no_perm_cannot_view_history(self):
        no_perm = make_user('el_loc_hist_n', [])
        body = make_client(no_perm).get(HISTORY_URL, {'device_id': self.device.id}).json()
        self.assertTrue(body.get('error'))


class DeviceLocationPermissionTest(TestCase):
    """位置变更权限与租户越权防护"""

    def setUp(self):
        setup_test_env(self)
        self.user_a = make_user('el_loc_ta', [PERM_DEVICE_VIEW, PERM_DEVICE_MANAGE])
        self.user_a.tenant_id = 'el_loc_tenant_a'
        self.user_a.save()
        self.user_b = make_user('el_loc_tb', [PERM_DEVICE_VIEW, PERM_DEVICE_MANAGE])
        self.user_b.tenant_id = 'el_loc_tenant_b'
        self.user_b.save()
        self.c_a = make_client(self.user_a)
        self.dev_a = make_device_record('el_loc_tenant_a', self.user_a,
                                        'EL-LOC-TA', current_location=LOCATION_A)
        self.dev_b = make_device_record('el_loc_tenant_b', self.user_b,
                                        'EL-LOC-TB', current_location=LOCATION_B)

    def test_view_only_cannot_change_location(self):
        viewer = make_user('el_loc_vonly', [PERM_DEVICE_VIEW])
        resp = make_client(viewer).post(CHANGE_URL, data=json.dumps(change_payload(self.dev_a.id)),
                                        content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.dev_a.refresh_from_db()
        self.assertEqual(self.dev_a.current_location, LOCATION_A)
        self.assertEqual(LifecycleDeviceLocation.objects.filter(device_id=self.dev_a.id).count(), 0)

    def test_relation_perm_cannot_change_location(self):
        rel_only = make_user('el_loc_ronly', [
            'equipment_lifecycle.relation.view', 'equipment_lifecycle.relation.manage'])
        resp = make_client(rel_only).post(CHANGE_URL, data=json.dumps(change_payload(self.dev_a.id)),
                                          content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_change_cross_tenant_device_blocked(self):
        resp = self.c_a.post(CHANGE_URL, data=json.dumps(change_payload(self.dev_b.id)),
                             content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.dev_b.refresh_from_db()
        self.assertEqual(self.dev_b.current_location, LOCATION_B)
        self.assertEqual(LifecycleDeviceLocation.objects.count(), 0)

    def test_history_cross_tenant_blocked(self):
        resp = self.c_a.get(HISTORY_URL, {'device_id': self.dev_b.id})
        self.assertTrue(resp.json().get('error'))

    def test_tampered_tenant_id_param_ignored(self):
        """篡改租户参数：服务端一律取当前用户租户"""
        resp = self.c_a.post(CHANGE_URL, data=json.dumps(change_payload(
            self.dev_a.id, tenant_id='el_loc_tenant_b')),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        self.dev_a.refresh_from_db()
        self.assertEqual(self.dev_a.current_location, LOCATION_B)
        history = active_history(self.dev_a.id)
        self.assertEqual(history.tenant_id, 'el_loc_tenant_a')

    def test_tampered_device_id_fails_closed(self):
        resp = self.c_a.post(CHANGE_URL, data=json.dumps(change_payload(999999)),
                             content_type='application/json')
        self.assertTrue(resp.json().get('error'))


class DeviceLocationConcurrencyTest(TransactionTestCase):
    """并发位置变更：同设备至多一条有效记录，至多一次成功"""

    def setUp(self):
        setup_test_env(self)
        self.manager = make_user('el_loc_conc', [PERM_DEVICE_VIEW, PERM_DEVICE_MANAGE])
        self.device = make_device_record(self.manager.tenant_id, self.manager,
                                         'EL-LOC-CONC', current_location=LOCATION_A)

    def test_concurrent_same_location_change_only_one_wins(self):
        results = []
        barrier = threading.Barrier(2)

        def worker():
            client = Client()
            client.defaults['HTTP_X_TOKEN'] = self.manager.access_token
            client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
            payload = {'device_id': self.device.id, 'new_location': LOCATION_B,
                       'change_type': 'relocation', 'reason': '并发搬迁'}
            try:
                barrier.wait(timeout=15)
                resp = client.post(CHANGE_URL, data=json.dumps(payload),
                                   content_type='application/json')
                try:
                    body = resp.json()
                except Exception:
                    body = {'_non_json_status': resp.status_code}
                results.append(body)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=90)

        self.assertEqual(len(results), 2, '两个并发请求都应返回结果')
        succeeded = [r for r in results if not r.get('error')]
        self.assertLessEqual(len(succeeded), 1, f'并发变更出现双成功: {results}')
        # 关键不变量：任何时刻同设备至多一条有效位置记录
        active_count = LifecycleDeviceLocation.objects.filter(
            device_id=self.device.id, ended_at__isnull=True).count()
        self.assertEqual(active_count, len(succeeded), f'有效记录数与成功数不一致: {results}')
        if succeeded:
            self.device.refresh_from_db()
            self.assertEqual(self.device.current_location, LOCATION_B)
            current = LifecycleDeviceLocation.objects.get(
                device_id=self.device.id, ended_at__isnull=True)
            self.assertEqual(current.new_location, LOCATION_B)
            self.assertEqual(current.old_location, LOCATION_A)
