# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

# 配置pymysql作为MySQL驱动（兼容MariaDB）
try:
    import pymysql
    pymysql.install_as_MySQLdb()
except ImportError:
    pass

# Celery 应用导入
# 这确保 Django 启动时加载 Celery 应用
from .celery import app as celery_app

__all__ = ('celery_app',)
