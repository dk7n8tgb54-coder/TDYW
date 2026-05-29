"""
# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
WSGI config for spug project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/2.2/howto/deployment/wsgi/
"""

# 【关键】gevent 猴子补丁 - 必须在导入任何其他模块前执行！
import gevent.monkey
gevent.monkey.patch_all()

import os

from django.core.wsgi import get_wsgi_application


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

application = get_wsgi_application()

# 【Celery迁移】APScheduler 已移除，使用 Celery 处理异步任务
# Celery Worker 和 Beat 由 Supervisor 管理启动
