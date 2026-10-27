# -*- coding: utf-8 -*-
"""回归测试（2026-10-25）：系统档案编辑（HTTP 全链路）与健康状态重算并发。

问题：SystemDetailView.put 先经 _get_system_for_user 读取系统（含
health_status、无行锁），读取与 item.save() 之间存在真实缝隙；若此间
故障创建链路（create_operation_record → recompute_systems_health）把新
health_status 落库，全字段 item.save() 会把读取时点的陈旧健康状态写回
数据库（丢失更新）。修复：档案保存用 update_fields 限定到
SYSTEM_EDITABLE_FIELDS 白名单，健康状态由重算服务独占写入。

本文件与 test_system_edit_health_race.py 的差别：主路径走真实 HTTP 请求
（self.client 经认证中间件进入视图），并发写通过 unittest.mock.patch 在
读取缝隙（_get_system_for_user 返回前）注入，注入的写入本身调用真实生产
服务 create_operation_record（内部 recompute_systems_health 落库），
不 mock 任何被测业务逻辑；最终断言落在 HTTP 响应与数据库最终状态上。

审计说明（2026-10-25）：LifecycleSystem 实例的落库路径共四处——
档案编辑平铺/聚合两处（本测试覆盖）、启停用 SystemActiveView（本就
update_fields=['is_active','updated_at','updated_by']）、健康重算
recompute_systems_health（update_fields=['health_status']）；除档案编辑
两处外均无全量保存，无其他覆盖健康状态的路径。
"""
import json
from unittest import mock

from django.test import TestCase

from apps.equipment_lifecycle import operation_services
from apps.equipment_lifecycle.models import LifecycleSystem
from apps.equipment_lifecycle.tests.base import (
    ALL_SYSTEM_PERMS,
    URL_PREFIX,
    make_client,
    make_system,
    make_user,
    system_payload,
)
from apps.equipment_lifecycle.views import _get_system_for_user


class SystemEditHealthRaceHttpTest(TestCase):
    """档案保存（HTTP PUT）不得用读取时点的陈旧 health_status 覆盖重算结果。"""

    def setUp(self):
        self.admin = make_user('el_race_http_admin', ALL_SYSTEM_PERMS,
                               tenant_id='tenant_race_http')
        self.client_auth = make_client(self.admin)
        self.system = make_system(self.admin, tenant_id='tenant_race_http',
                                  name='HTTP竞态系统')
        self.detail_url = '%s/systems/%d/' % (URL_PREFIX, self.system.id)

    def _register_active_fault(self):
        """真实故障创建链路：落库故障记录并重算健康状态（interrupted）。"""
        return operation_services.create_operation_record(
            tenant_id=self.admin.tenant_id, created_by=self.admin,
            system=self.system, record_type='fault',
            occurred_at='2026-10-25 10:00:00',
            title='天线馈线故障', description='导致系统中断，影响系统运行',
            affects_system_operation=True, impact_status='interrupted',
        )

    def _patch_read_seam_with_concurrent_recompute(self):
        """在视图读取缝隙注入并发健康重算（读取返回前，真实服务落库）。"""
        original = _get_system_for_user

        def read_with_concurrent_write(pk, user):
            stale_item = original(pk, user)
            # 模拟另一事务在"读取之后、保存之前"提交的健康重算
            self._register_active_fault()
            return stale_item

        return mock.patch(
            'apps.equipment_lifecycle.views._get_system_for_user',
            side_effect=read_with_concurrent_write)

    def test_aggregate_edit_keeps_recalculated_health(self):
        with self._patch_read_seam_with_concurrent_recompute():
            response = self.client_auth.put(
                self.detail_url,
                data=json.dumps({'system': system_payload(name='HTTP竞态系统-改名')},
                                ensure_ascii=False),
                content_type='application/json')
        data = json.loads(response.content)
        self.assertFalse(data.get('error'), response.content)

        system = LifecycleSystem.objects.get(pk=self.system.id)
        # 固定字段正常保存
        self.assertEqual(system.name, 'HTTP竞态系统-改名')
        # 健康状态保留重算结果（修复前：全量 save 把读取时点的 normal 写回）
        self.assertEqual(
            system.health_status, 'interrupted',
            '档案聚合编辑把重算后的健康状态覆盖回读取时点的陈旧值')

    def test_flat_edit_keeps_recalculated_health(self):
        with self._patch_read_seam_with_concurrent_recompute():
            response = self.client_auth.put(
                self.detail_url,
                data=json.dumps(system_payload(name='HTTP竞态系统-平铺'),
                                ensure_ascii=False),
                content_type='application/json')
        data = json.loads(response.content)
        self.assertFalse(data.get('error'), response.content)

        system = LifecycleSystem.objects.get(pk=self.system.id)
        self.assertEqual(system.name, 'HTTP竞态系统-平铺')
        self.assertEqual(
            system.health_status, 'interrupted',
            '档案平铺编辑同样不能覆盖重算后的健康状态')

    def test_edit_without_concurrent_fault_keeps_normal(self):
        """护栏：无并发故障时档案编辑行为不变（健康状态保持 normal）。"""
        response = self.client_auth.put(
            self.detail_url,
            data=json.dumps({'system': system_payload(name='无并发改名')},
                            ensure_ascii=False),
            content_type='application/json')
        self.assertFalse(json.loads(response.content).get('error'),
                         response.content)
        system = LifecycleSystem.objects.get(pk=self.system.id)
        self.assertEqual(system.name, '无并发改名')
        self.assertEqual(system.health_status, LifecycleSystem.HEALTH_NORMAL)

    def test_health_recompute_path_still_writes_status(self):
        """护栏：档案保存加字段白名单后，健康重算链路本身照常写入。"""
        self._register_active_fault()
        system = LifecycleSystem.objects.get(pk=self.system.id)
        self.assertEqual(system.health_status, 'interrupted')
