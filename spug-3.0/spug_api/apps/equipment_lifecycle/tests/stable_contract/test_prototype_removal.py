# -*- coding: utf-8 -*-
"""模板导入验证原型下线后的路由边界稳定契约（2026-10-01）。

原型模块 apps.ledger_prototype 已整体删除（零迁移、文件存储，无数据库表），
本套件固化下线事实与正式 Excel 路线不受影响：
- /ledger-prototype/ 前缀不再注册，任何子路径都不允许解析（404）；
- 正式 Excel 模板与 Excel 台账路由仍正常解析到原视图。
通过真实 URL 解析器执行，不读取源码做正则匹配。
"""
from django.test import TestCase
from django.urls import Resolver404, resolve

from apps.equipment_lifecycle.tests.base import URL_PREFIX


class PrototypeRouteRemovedTests(TestCase):

    def test_ledger_prototype_prefix_not_resolvable(self):
        for path in (
            '/ledger-prototype/templates/',
            '/ledger-prototype/sample-template/',
            '/ledger-prototype/',
        ):
            with self.subTest(path=path):
                with self.assertRaises(Resolver404):
                    resolve(path)

    def test_excel_template_routes_still_resolve(self):
        match = resolve(URL_PREFIX + '/excel-templates/')
        self.assertEqual(match.func.view_class.__name__, 'ExcelTemplateView')

    def test_excel_ledger_routes_still_resolve(self):
        match = resolve(URL_PREFIX + '/excel-ledgers/')
        self.assertEqual(match.func.view_class.__name__, 'ExcelLedgerView')
