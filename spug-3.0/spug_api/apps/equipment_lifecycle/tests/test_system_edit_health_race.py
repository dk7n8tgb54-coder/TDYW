# -*- coding: utf-8 -*-
"""回归测试（2026-10-25）：系统档案编辑与健康状态重算并发丢失更新。

问题：SystemDetailView.put 在读取系统（无行锁）之后，_update_flat/
_update_aggregate 以全字段 item.save() 落库——若读与写之间故障创建链路
（create_operation_record → recompute_systems_health）已提交新的
health_status，档案保存会把内存里的陈旧健康状态写回数据库。

复现方式：按真实并发交错顺序执行三步真实生产代码（仅模拟挂钟交错，
不 mock 任何被测逻辑）：
  T0 用视图 put 所用的同一个读取辅助 _get_system_for_user 加载实例；
  T1 走真实 create_operation_record 服务登记影响系统运行的设备故障，
     其内部 recompute_systems_health 把健康状态落库；
  T2 用 T0 的实例调用真实 _update_aggregate 保存路径（与 put 相同的
     解析/赋值/审计/保存代码）。
期望：档案保存只写固定字段，健康状态保留重算结果 'interrupted'。
"""
import json

from django.test import RequestFactory, TestCase

from apps.equipment_lifecycle import operation_services
from apps.equipment_lifecycle.models import LifecycleSystem
from apps.equipment_lifecycle.tests.base import (
    ALL_SYSTEM_PERMS,
    make_system,
    make_user,
    system_payload,
)
from apps.equipment_lifecycle.views import SystemDetailView, _get_system_for_user


class SystemEditHealthRaceTest(TestCase):
    def setUp(self):
        self.admin = make_user('el_race_admin', ALL_SYSTEM_PERMS,
                               tenant_id='tenant_race')
        self.system = make_system(self.admin, tenant_id='tenant_race',
                                  name='并发竞态系统')

    def _aggregate_body(self):
        return {'system': system_payload(name='并发竞态系统-改名')}

    def _update_request(self, body):
        request = RequestFactory().put(
            '/equipment-lifecycle/systems/%d/' % self.system.id,
            data=json.dumps(body), content_type='application/json')
        request.user = self.admin
        return request

    def _register_active_fault(self):
        return operation_services.create_operation_record(
            tenant_id=self.admin.tenant_id, created_by=self.admin,
            system=self.system, record_type='fault',
            occurred_at='2026-10-25 10:00:00',
            title='天线馈线故障', description='导致系统中断，影响系统运行',
            affects_system_operation=True, impact_status='interrupted',
        )

    def test_edit_after_health_recompute_keeps_recalculated_status(self):
        # T0：视图 put 的读取时点（同一辅助函数）
        stale_item = _get_system_for_user(self.system.id, self.admin)
        self.assertEqual(stale_item.health_status, LifecycleSystem.HEALTH_NORMAL)

        # T1：真实故障创建链路提交了新的健康状态
        self._register_active_fault()
        self.system.refresh_from_db()
        self.assertEqual(self.system.health_status, 'interrupted')

        # T2：用 T0 的实例执行真实保存路径
        body = self._aggregate_body()
        response = SystemDetailView()._update_aggregate(
            self._update_request(body), stale_item, body)
        self.assertFalse(json.loads(response.content).get('error'),
                         response.content)

        system = LifecycleSystem.objects.get(pk=self.system.id)
        # 固定字段正常保存
        self.assertEqual(system.name, '并发竞态系统-改名')
        # 健康状态不被档案保存覆盖（修复前这里回落为 normal）
        self.assertEqual(
            system.health_status, 'interrupted',
            '档案全字段保存把重算后的健康状态覆盖回了读取时点的陈旧值')

    def test_flat_edit_after_health_recompute_keeps_recalculated_status(self):
        stale_item = _get_system_for_user(self.system.id, self.admin)
        self._register_active_fault()

        from apps.equipment_lifecycle.views import _parse_system_fields
        form, error = _parse_system_fields(system_payload(name='平铺改名'))
        self.assertIsNone(error)
        response = SystemDetailView()._update_flat(
            self._update_request({'name': '平铺改名'}), stale_item, form)
        self.assertFalse(json.loads(response.content).get('error'),
                         response.content)

        system = LifecycleSystem.objects.get(pk=self.system.id)
        self.assertEqual(system.name, '平铺改名')
        self.assertEqual(
            system.health_status, 'interrupted',
            '平铺编辑路径同样不能覆盖重算后的健康状态')

    def test_fault_creation_recompute_still_writes_status(self):
        """护栏：约束档案保存字段后，健康重算链路本身不受影响。"""
        self._register_active_fault()
        self.system.refresh_from_db()
        self.assertEqual(self.system.health_status, 'interrupted')
