# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
Document 模块 Celery Beat 定时任务配置
需要在主项目的 settings.py 中导入并合并到 CELERY_BEAT_SCHEDULE

使用方式：
1. 在 spug/settings.py 中添加：
   from celery.schedules import crontab
   from apps.document.celery_beat_schedule import DOCUMENT_BEAT_SCHEDULE
   CELERY_BEAT_SCHEDULE.update(DOCUMENT_BEAT_SCHEDULE)

2. 启动 Celery Beat：
   celery -A spug beat -l info
"""
from celery.schedules import crontab

# Document 模块定时任务配置
DOCUMENT_BEAT_SCHEDULE = {
    # ========================================
    # 分片清理任务 - 每天凌晨2点执行
    # 清理7天前的过期分片文件
    # ========================================
    'document-cleanup-old-chunks': {
        'task': 'apps.document.tasks.cleanup.cleanup_old_chunks',
        'schedule': crontab(hour=2, minute=0),
        'kwargs': {'days': 7},
        'options': {'queue': 'document.cleanup'},
    },
    
    # ========================================
    # 传输记录清理任务 - 每天凌晨3点执行
    # 清理30天前的已完成/失败/取消传输记录
    # ========================================
    'document-cleanup-expired-transfers': {
        'task': 'apps.document.tasks.cleanup.cleanup_expired_transfers',
        'schedule': crontab(hour=3, minute=0),
        'kwargs': {},
        'options': {'queue': 'document.cleanup'},
    },
    
    # ========================================
    # 【P2优化】合并任务超时检测 - 每10分钟执行一次
    # 检测卡在merging状态超过30分钟的任务
    # ========================================
    'document-check-merge-timeout': {
        'task': 'apps.document.tasks.timeout_checker.check_merge_timeout',
        'schedule': crontab(minute='*/10'),  # 每10分钟
        'kwargs': {'timeout_minutes': 30},
        'options': {'queue': 'document.cleanup'},
    },
    
    # ========================================
    # 【P2优化】僵尸任务清理 - 每天凌晨5点执行
    # 清理超过24小时仍卡在merging状态的任务
    # ========================================
    'document-cleanup-stale-merging': {
        'task': 'apps.document.tasks.timeout_checker.cleanup_stale_merging_tasks',
        'schedule': crontab(hour=5, minute=0),
        'kwargs': {'older_than_hours': 24},
        'options': {'queue': 'document.cleanup'},
    },

    # ========================================
    # 孤儿传输记录清理 - 每6小时执行
    # 清理 PENDING/UPLOADING/MERGING 超时 + 终态超龄的 transfer 记录
    # ========================================
    'document-cleanup-orphan-transfers': {
        'task': 'apps.document.tasks.cleanup.orphan_transfers.cleanup_orphan_transfers',
        'schedule': crontab(minute=0, hour='*/6'),
        'kwargs': {'dry_run': False},
        'options': {'queue': 'document.cleanup'},
    },

    # ========================================
    # 打包任务文件清理 - 每天凌晨6点执行
    # 清理超过 24 小时的打包 ZIP 文件
    # 【修复】原 cleanup_expired_pack_tasks 已定义但无 Beat 调度也无 delay 调用，
    # 导致 storage/document_pack_tasks/ 下的 zip 永久堆积
    # ========================================
    'document-cleanup-expired-pack-tasks': {
        'task': 'apps.document.tasks.pack.cleanup_expired_pack_tasks',
        'schedule': crontab(hour=6, minute=0),
        'kwargs': {'max_age_hours': 24},
        'options': {'queue': 'document.pack'},
    },
}

