# -*- coding: utf-8 -*-
"""系统档案详情弹窗三页签下线（2026-10-11）稳定契约测试。

系统详情弹窗移除"周月维护台账""季维护台账""系统履历"三个页签后：
1. 页签专用端点 systems/<pk>/ledger-items/ 不再注册（认证用户真实请求
   404；原为详情弹窗台账页签专用，页签移除后无其他调用方）；
2. 三项业务的独立入口不受影响：
   - 周月/季维护台账仍由独立菜单页面 + ledgers 列表接口承载；
   - 系统履历仍由独立菜单页面（system-events）与事项聚合接口承载，
     按系统查询履历端点 systems/<pk>/system-events/ 仍注册可用
     （履历分组视图"状态变化"面板等场景使用）；
3. 历史数据与既有接口零迁移（模型零改动）。

全部通过真实 HTTP 路径 + 隔离测试数据库执行。
"""
from django.test import TestCase

from apps.equipment_lifecycle.tests.base import (
    URL_PREFIX, make_client, make_system, make_user,
)

LEDGER_URL = URL_PREFIX + '/ledgers'


class SystemDetailTabsRemovalTest(TestCase):
    """详情弹窗页签下线后的端点契约。"""

    def setUp(self):
        self.user = make_user(
            'tabs_removed_op',
            ['equipment_lifecycle.system.view',
             'equipment_lifecycle.ledger.view',
             'equipment_lifecycle.system_event.view'])
        self.client = make_client(self.user)
        self.system = make_system(self.user, tenant_id='default')

    def test_system_ledger_items_endpoint_removed(self):
        """页签专用 ledger-items 端点 404（路由已注销）。"""
        resp = self.client.get(
            f'{URL_PREFIX}/systems/{self.system.id}/ledger-items/')
        self.assertEqual(resp.status_code, 404, resp.content)

    def test_system_events_endpoint_still_alive(self):
        """按系统查询履历端点仍注册（独立系统履历页/分组视图使用）。"""
        body = self.client.get(
            f'{URL_PREFIX}/systems/{self.system.id}/system-events/').json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['data'], [])

    def test_ledger_lists_still_alive(self):
        """周月/季维护台账独立列表接口不受页签下线影响。"""
        for ledger_type in ('week_month', 'seasonal'):
            body = self.client.get(
                LEDGER_URL + '/', {'ledger_type': ledger_type}).json()
            self.assertFalse(body.get('error'), body)
            self.assertEqual(body['data']['data'], [])
