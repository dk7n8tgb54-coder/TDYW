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
        'kwargs': {'days': 30},
        'options': {'queue': 'document.cleanup'},
    },
    
    # ========================================
    # 【V3新增】软删除文件清理任务 - 每天凌晨4点执行
    # 清理软删除超过30天的物理文件
    # ========================================
    'document-cleanup-soft-deleted-files': {
        'task': 'apps.document.tasks.cleanup.cleanup_soft_deleted_files',
        'schedule': crontab(hour=4, minute=0),
        'kwargs': {
            'retention_days': 30,  # 保留30天
            'dry_run': False       # 实际删除（非模拟）
        },
        'options': {
            'queue': 'document.cleanup',
            'time_limit': 7200,    # 2小时超时
        },
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
}


# 可选：更激进的清理策略（用于磁盘紧张环境）
AGGRESSIVE_BEAT_SCHEDULE = {
    # 每天运行两次清理
    'document-cleanup-soft-deleted-files-aggressive': {
        'task': 'apps.document.tasks.cleanup.cleanup_soft_deleted_files',
        'schedule': crontab(hour='2,14', minute=0),  # 每天2点和14点
        'kwargs': {
            'retention_days': 7,   # 只保留7天
            'dry_run': False
        },
        'options': {
            'queue': 'document.cleanup',
            'time_limit': 7200,
        },
    },
}
