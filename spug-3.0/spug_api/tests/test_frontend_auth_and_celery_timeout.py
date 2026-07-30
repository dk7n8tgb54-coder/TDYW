# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""前端 auth 覆盖 + Celery 超时配置验证测试

验证两个候选发现：
1. 前端按钮缺少 auth 属性 → 验证后端是否有 @auth/PERM_MAP 兜底
2. Celery 任务缺少超时配置 → 验证全局/逐任务超时是否覆盖

运行：
  docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
    python manage.py test tests.test_frontend_auth_and_celery_timeout --noinput
"""
import inspect
import json
import time
import uuid

from django.test import TestCase, Client
from django.contrib.auth.hashers import make_password

from apps.account.models import User, Role, Tenant
from apps.setting.models import Setting
from apps.setting.utils import AppSetting


def _make_user(username, password='Test1234!', **kwargs):
    defaults = dict(
        username=username,
        nickname=username,
        password_hash=make_password(password),
        type='default',
        is_supper=False,
        is_active=True,
        access_token=uuid.uuid4().hex,
        token_expired=int(time.time()) + 8 * 3600,
        last_ip='',
        wx_token='',
        tenant_id='admin',
    )
    defaults.update(kwargs)
    return User.objects.create(**defaults)


def _make_role(name, page_perms_dict, tenant_id=''):
    su = User.objects.filter(is_supper=True).first()
    if not su:
        su = _make_user('__role_creator', is_supper=True, tenant_id='')
    return Role.objects.create(
        name=name,
        page_perms=json.dumps(page_perms_dict) if page_perms_dict else '',
        deploy_perms='',
        group_perms='',
        is_global_admin=False,
        tenant_id=tenant_id,
        created_by=su,
    )


# ===========================================================================
# 发现 1：前端按钮缺少 auth 属性，后端是否有兜底？
# ===========================================================================
class Finding1FrontendAuthBackendCheckTest(TestCase):
    """发现 1：前端按钮缺少 auth → 验证后端 @auth/PERM_MAP 是否兜底

    前端 Table.js 中以下按钮缺少 auth 属性：
    - system/role/Table.js: 编辑/功能权限/删除/新建
    - system/account/Table.js: 恢复/启用禁用/编辑/重置密码/删除/签名/新建
    - exec/fault/part/Table.js: 新建/编辑/删除

    预期：后端 @auth 装饰器 / PERM_MAP 会拦截未授权请求
    所以前端缺 auth 只是 UX 问题（看到按钮但点了报错），不是安全问题
    """

    def setUp(self):
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        Setting.objects.all().delete()

        # 创建一个只有 view 权限、没有 add/edit/del 的普通用户
        self.viewer = _make_user('viewer_1', tenant_id='admin', last_ip='')
        role = _make_role('viewer_role', {
            'system': {'account': ['view'], 'role': ['view']},
            'fault': {'faultpart': ['view']},
        })
        self.viewer.roles.add(role)

        self.client = Client()

    def test_role_edit_blocked_without_permission(self):
        """无 system.account.edit 权限的用户不能编辑角色"""
        resp = self.client.patch(
            '/account/role/',
            data=json.dumps({'id': 999, 'name': 'hacked'}),
            content_type='application/json',
            HTTP_X_TOKEN=self.viewer.access_token,
        )
        body = resp.json()
        self.assertTrue(
            body.get('error'),
            "无 edit 权限的用户应被后端 PERM_MAP 拦截，但请求通过了"
        )

    def test_role_delete_blocked_without_permission(self):
        """无 system.account.del 权限的用户不能删除角色"""
        resp = self.client.delete(
            '/account/role/?id=999',
            HTTP_X_TOKEN=self.viewer.access_token,
        )
        body = resp.json()
        self.assertTrue(
            body.get('error'),
            "无 del 权限的用户应被后端 PERM_MAP 拦截，但请求通过了"
        )

    def test_account_edit_blocked_without_permission(self):
        """无 system.account.edit 权限的用户不能编辑用户"""
        resp = self.client.patch(
            '/account/user/',
            data=json.dumps({'id': 999, 'nickname': 'hacked'}),
            content_type='application/json',
            HTTP_X_TOKEN=self.viewer.access_token,
        )
        body = resp.json()
        self.assertTrue(
            body.get('error'),
            "无 edit 权限的用户应被后端 PERM_MAP 拦截，但请求通过了"
        )

    def test_account_delete_blocked_without_permission(self):
        """无 system.account.del 权限的用户不能删除用户"""
        resp = self.client.delete(
            '/account/user/?id=999',
            HTTP_X_TOKEN=self.viewer.access_token,
        )
        body = resp.json()
        self.assertTrue(
            body.get('error'),
            "无 del 权限的用户应被后端 PERM_MAP 拦截，但请求通过了"
        )

    def test_faultpart_edit_blocked_without_permission(self):
        """无 fault.faultpart.edit 权限的用户不能编辑故障件"""
        resp = self.client.post(
            '/fault/faultpart/',
            data=json.dumps({'id': 999, 'name': 'hacked'}),
            content_type='application/json',
            HTTP_X_TOKEN=self.viewer.access_token,
        )
        body = resp.json()
        # @auth('fault.faultpart.add|fault.faultpart.edit') 装饰器应拦截
        self.assertTrue(
            body.get('error'),
            "无 add/edit 权限的用户应被后端 @auth 拦截，但请求通过了"
        )

    def test_faultpart_delete_blocked_without_permission(self):
        """无 fault.faultpart.del 权限的用户不能删除故障件"""
        resp = self.client.delete(
            '/fault/faultpart/?id=999',
            HTTP_X_TOKEN=self.viewer.access_token,
        )
        body = resp.json()
        # @auth('fault.faultpart.del') 装饰器应拦截
        self.assertTrue(
            body.get('error'),
            "无 del 权限的用户应被后端 @auth 拦截，但请求通过了"
        )


# ===========================================================================
# 发现 2：Celery 任务超时配置检查
# ===========================================================================
class Finding2CeleryTimeoutCheckTest(TestCase):
    """发现 2：Celery 任务是否有超时配置

    验证：
    - 全局 CELERY_TASK_SOFT_TIME_LIMIT / CELERY_TASK_TIME_LIMIT 是否设置
    - 每个 @shared_task 是否有显式 soft_time_limit / time_limit
    - 没有显式超时的任务是否有全局兜底
    """

    def test_global_timeout_configured(self):
        """全局 Celery 超时配置存在"""
        from django.conf import settings
        soft = getattr(settings, 'CELERY_TASK_SOFT_TIME_LIMIT', None)
        hard = getattr(settings, 'CELERY_TASK_TIME_LIMIT', None)

        self.assertIsNotNone(
            soft,
            "全局 CELERY_TASK_SOFT_TIME_LIMIT 未设置，无显式超时的任务将无超时保护"
        )
        self.assertIsNotNone(
            hard,
            "CELERY_TASK_TIME_LIMIT 未设置，无显式超时的任务将无超时保护"
        )
        self.assertGreater(soft, 0, "CELERY_TASK_SOFT_TIME_LIMIT 应为正数")
        self.assertGreater(hard, 0, "CELERY_TASK_TIME_LIMIT 应为正数")
        self.assertGreater(
            hard, soft,
            "CELERY_TASK_TIME_LIMIT 应大于 CELERY_TASK_SOFT_TIME_LIMIT"
        )

    def test_all_shared_tasks_have_timeout(self):
        """所有 @shared_task 应有显式超时或全局兜底"""
        from django.conf import settings
        global_soft = getattr(settings, 'CELERY_TASK_SOFT_TIME_LIMIT', None)
        global_hard = getattr(settings, 'CELERY_TASK_TIME_LIMIT', None)

        # 收集所有 @shared_task 装饰的函数
        tasks_without_explicit_timeout = []
        tasks_checked = 0

        # 遍历 Celery app 注册的所有任务
        from spug.celery import app as celery_app
        inspect_result = celery_app.control.inspect(timeout=1.0)

        # 直接检查已注册的任务名称
        registered = celery_app.tasks
        for task_name, task_obj in registered.items():
            # 跳过 Celery 内置任务
            if task_name.startswith('celery.'):
                continue
            # 只检查项目自己的任务（以 apps. 开头）
            if not task_name.startswith('apps.'):
                continue

            tasks_checked += 1
            soft = getattr(task_obj, 'soft_time_limit', None)
            hard = getattr(task_obj, 'time_limit', None)

            # 如果任务没有显式超时，检查全局是否有兜底
            if soft is None and global_soft is None:
                tasks_without_explicit_timeout.append(task_name)
            if hard is None and global_hard is None:
                tasks_without_explicit_timeout.append(task_name)

        self.assertEqual(
            len(tasks_without_explicit_timeout), 0,
            "以下 Celery 任务既无显式超时也无全局兜底：\n  {}\n"
            "建议在 @shared_task 装饰器中添加 soft_time_limit 和 time_limit，"
            "或在 settings.py 中设置全局 CELERY_TASK_SOFT_TIME_LIMIT / CELERY_TASK_TIME_LIMIT".format(
                '\n  '.join(tasks_without_explicit_timeout) or '(无)'
            )
        )

        # 确保至少检查了一些任务（验证测试本身有效）
        self.assertGreater(
            tasks_checked, 0,
            "未找到任何项目 Celery 任务，测试可能无效"
        )

    def test_alert_tasks_have_global_fallback(self):
        """alert 模块的任务无显式超时，验证全局兜底生效"""
        from django.conf import settings
        from apps.alert.tasks import check_disk_space, collect_db_metrics, run_data_quality_check

        global_soft = getattr(settings, 'CELERY_TASK_SOFT_TIME_LIMIT', None)
        global_hard = getattr(settings, 'CELERY_TASK_TIME_LIMIT', None)

        self.assertIsNotNone(global_soft, "全局 soft_time_limit 未设置，alert 任务无超时保护")
        self.assertIsNotNone(global_hard, "全局 time_limit 未设置，alert 任务无超时保护")

        # alert 任务没有显式超时，但全局配置应该兜底
        # 验证 Celery app 配置中有全局设置
        from spug.celery import app as celery_app
        app_soft = celery_app.conf.task_soft_time_limit
        app_hard = celery_app.conf.task_time_limit

        self.assertEqual(
            app_soft, global_soft,
            "Celery app 的 task_soft_time_limit 应等于 settings 中的全局配置"
        )
        self.assertEqual(
            app_hard, global_hard,
            "Celery app 的 task_time_limit 应等于 settings 中的全局配置"
        )
