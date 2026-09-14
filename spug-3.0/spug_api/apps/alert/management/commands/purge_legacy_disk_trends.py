# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License
"""一次性清理旧口径磁盘趋势 ZSet 的管理命令。

背景：2026-09 前 check_disk_space 用 shutil.disk_usage 记录磁盘趋势，
写入的是目录所在文件系统的 used 字节。三个存储目录（documents/chunks/media）
可能共用同一底层文件系统，导致三条曲线完全重合。指标口径改为 du 统计的
目录实际占用后，因 Redis ZSet 为追加语义（record_metric 每次追加历史成员），
旧口径历史无法被覆盖，上线时必须执行一次本命令清除：

    docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw \
        python manage.py purge_legacy_disk_trends

说明：
- 不影响新增的 metric:disk:total（无需清理）；
- 清理后由下一轮 30 分钟采集写入正确口径；
- 连接信息来自 Django settings（django_redis），不硬编码 Redis 密码；
- 该清理逻辑不在每轮定时任务中，本命令仅用于一次性迁移。
"""
from django.core.management.base import BaseCommand
from django_redis import get_redis_connection

# 旧口径（文件系统 used 字节）趋势 ZSet；新口径键名相同但口径已变，必须清除重建
LEGACY_TREND_KEYS = [
    'metric:disk:documents',
    'metric:disk:chunks',
    'metric:disk:media',
]


class Command(BaseCommand):
    help = '一次性删除旧口径（文件系统占用）的磁盘趋势 ZSet，由下一轮 30 分钟采集写入新口径（目录实际占用）'

    def handle(self, *args, **options):
        conn = get_redis_connection()
        existing = [key for key in LEGACY_TREND_KEYS if conn.exists(key)]
        if not existing:
            self.stdout.write('未发现旧口径磁盘趋势键，无需清理')
            return
        conn.delete(*existing)
        self.stdout.write(self.style.SUCCESS(f'已删除旧口径磁盘趋势键: {", ".join(existing)}'))
