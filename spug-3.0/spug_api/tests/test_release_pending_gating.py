# -*- coding: utf-8 -*-
"""RELEASE_PENDING_APPS 部署门控回归测试（真实启动路径，子进程验证）。

门控语义（spug/settings.py 的 INSTALLED_APPS 过滤 + spug/urls.py 的延迟路由注册）：
- RELEASE_PENDING_APPS 含 equipment_lifecycle：该 app 摘出 INSTALLED_APPS、
  路由不注册，Django 必须能正常完成 apps.populate 启动，其余应用照常加载；
- 不含时：全部模块照常加载。

历史上 apps/upgrade/models.py 曾在模块级导入 equipment_lifecycle 的
LifecycleSystem（并用作外键类引用），导致门控开启时 Django 启动即崩溃
（RuntimeError: Model ... isn't in an application in INSTALLED_APPS）。
外键已改为字符串引用、views/services 改为函数内导入后，两种门控情形都必须能走完
真实启动路径。

进程内无法安全切换 app registry（apps.populate 不可重入），因此用隔离子进程
执行 manage.py shell -c 探针验证：探针只读取 settings/apps registry/URL
resolver，不做任何数据库访问。
"""
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

MANAGE_PY = Path(__file__).resolve().parents[1] / 'manage.py'

# 只读探针：settings 已加载后检查 app registry 与根路由表，再验证 upgrade
# 模型（外键为字符串引用）可独立于 equipment_lifecycle 是否安装而导入。
PROBE = (
    "from django.apps import apps;"
    "from django.urls import get_resolver;"
    "print('EL_INSTALLED=', apps.is_installed('apps.equipment_lifecycle'));"
    "routes = [str(getattr(p.pattern, '_route', None) or getattr(p.pattern, '_regex', ''))"
    " for p in get_resolver().url_patterns];"
    "print('EL_ROUTE=', any('equipment-lifecycle' in r for r in routes));"
    "print('UPGRADE_INSTALLED=', apps.is_installed('apps.upgrade'));"
    "from apps.upgrade.models import UpgradeRecord;"
    "print('UPGRADE_MODEL_OK=1')"
)


class ReleasePendingGatingTests(SimpleTestCase):
    """门控开/关两种情形的真实启动验证（子进程隔离，不触数据库）。"""

    def _run_probe(self, release_pending_apps):
        env = dict(os.environ)
        env['PYTHONIOENCODING'] = 'utf-8'
        if release_pending_apps is None:
            env.pop('RELEASE_PENDING_APPS', None)
        else:
            env['RELEASE_PENDING_APPS'] = release_pending_apps
        return subprocess.run(
            [sys.executable, str(MANAGE_PY), 'shell', '-c', PROBE],
            cwd=str(MANAGE_PY.parent), env=env, timeout=120,
            capture_output=True, text=True, encoding='utf-8', errors='replace')

    def test_gate_off_all_modules_load(self):
        """不设置门控变量：equipment_lifecycle 安装且路由注册（现状语义）。"""
        proc = self._run_probe(release_pending_apps=None)
        self.assertEqual(
            proc.returncode, 0,
            '门控关闭时启动失败\nstdout:%s\nstderr:%s'
            % (proc.stdout[-2000:], proc.stderr[-2000:]))
        self.assertIn('EL_INSTALLED= True', proc.stdout)
        self.assertIn('EL_ROUTE= True', proc.stdout)
        self.assertIn('UPGRADE_INSTALLED= True', proc.stdout)
        self.assertIn('UPGRADE_MODEL_OK=1', proc.stdout)

    def test_gate_on_el_hidden_and_startup_survives(self):
        """门控含 equipment_lifecycle：启动必须成功（不再崩溃），EL 应用与
        路由均不加载，upgrade 应用照常安装且模型可导入。"""
        proc = self._run_probe(release_pending_apps='equipment_lifecycle')
        self.assertEqual(
            proc.returncode, 0,
            '门控开启时启动崩溃\nstdout:%s\nstderr:%s'
            % (proc.stdout[-2000:], proc.stderr[-2000:]))
        self.assertIn('EL_INSTALLED= False', proc.stdout)
        self.assertIn('EL_ROUTE= False', proc.stdout)
        self.assertIn('UPGRADE_INSTALLED= True', proc.stdout)
        self.assertIn('UPGRADE_MODEL_OK=1', proc.stdout)

    def test_gate_on_system_checks_pass(self):
        """门控开启时部署命令链第一关（manage.py check，entrypoint migrate
        前置）不因字符串外键引用未安装应用而报 fields.E300/E307。
        check 命令不访问数据库。"""
        env = dict(os.environ)
        env['PYTHONIOENCODING'] = 'utf-8'
        env['RELEASE_PENDING_APPS'] = 'equipment_lifecycle'
        proc = subprocess.run(
            [sys.executable, str(MANAGE_PY), 'check'], cwd=str(MANAGE_PY.parent),
            env=env, timeout=120, capture_output=True, text=True,
            encoding='utf-8', errors='replace')
        self.assertEqual(
            proc.returncode, 0,
            '门控开启时系统检查失败\nstdout:%s\nstderr:%s'
            % (proc.stdout[-2000:], proc.stderr[-2000:]))
        self.assertNotIn('fields.E300', proc.stdout + proc.stderr)
        self.assertNotIn('fields.E307', proc.stdout + proc.stderr)
