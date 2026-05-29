# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
清理过期分片文件的 Django 管理命令
用法: python manage.py cleanup_chunks
"""

from django.core.management.base import BaseCommand
from django.conf import settings
from apps.document.tasks.cleanup import cleanup_old_chunks
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '清理超过 24 小时的分片文件和合并任务文件'

    def handle(self, *args, **options):
        self.stdout.write('开始清理过期分片文件...')
        cleanup_old_chunks()
        self.stdout.write(self.style.SUCCESS('清理完成'))
