# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
清理任务 - 软删除数据清理
"""
import logging
import os
from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from django.db import DatabaseError

logger = logging.getLogger(__name__)


@shared_task(bind=True, soft_time_limit=3600, time_limit=7200, queue='document.cleanup')
def cleanup_soft_deleted_files(self, retention_days=30, dry_run=False):
    """
    【V3】清理软删除文件的物理文件
    
    定时清理超过保留期的软删除文件物理文件
    
    Args:
        retention_days: 保留天数（默认30天）
        dry_run: 仅模拟运行，不实际删除（用于测试）
        
    Returns:
        dict: 清理统计
    """
    from apps.document.models import DocumentFilePrivate, DocumentFilePublic
    
    cutoff_time = timezone.now() - timedelta(days=retention_days)
    
    logger.info(f'[Celery][Cleanup] 开始清理软删除文件，保留天数：{retention_days}，截止时间：{cutoff_time}')
    
    stats = {
        'private': {'checked': 0, 'deleted': 0, 'errors': 0, 'not_found': 0, 'failed_file_ids': []},
        'public': {'checked': 0, 'deleted': 0, 'errors': 0, 'not_found': 0, 'failed_file_ids': []}
    }
    
    # 清理私有文件（使用 iterator 分页，避免 OOM）
    private_files = DocumentFilePrivate.all_objects.filter(
        is_deleted=True,
        deleted_at__lte=cutoff_time
    ).iterator(chunk_size=1000)

    for file in private_files:
        stats['private']['checked'] += 1
        
        if dry_run:
            logger.info(f'[Celery][Cleanup][DryRun] 将清理私有文件：{file.file_path}')
            continue
        
        try:
            if os.path.exists(file.file_path):
                os.remove(file.file_path)
                logger.info(f'[Celery][Cleanup] 已清理私有文件：{file.file_path}')
                stats['private']['deleted'] += 1
            else:
                logger.warning(f'[Celery][Cleanup] 私有文件不存在：{file.file_path}')
                stats['private']['not_found'] += 1
            
            # 【P1修复】物理文件删除成功后，删除数据库记录
            file.delete(hard=True)
            logger.info(f'[Celery][Cleanup] 已删除数据库记录：id={file.id}')
                
        except (OSError, IOError, DatabaseError) as e:
            stats['private']['errors'] += 1
            stats['private']['failed_file_ids'].append(file.id)
            logger.error(f'[Celery][Cleanup] 清理私有文件失败：{file.file_path}, error={e}')
    
    # 清理公共文件（使用 iterator 分页，避免 OOM）
    public_files = DocumentFilePublic.all_objects.filter(
        is_deleted=True,
        deleted_at__lte=cutoff_time
    ).iterator(chunk_size=1000)

    for file in public_files:
        stats['public']['checked'] += 1
        
        if dry_run:
            logger.info(f'[Celery][Cleanup][DryRun] 将清理公共文件：{file.file_path}')
            continue
        
        try:
            if os.path.exists(file.file_path):
                os.remove(file.file_path)
                logger.info(f'[Celery][Cleanup] 已清理公共文件：{file.file_path}')
                stats['public']['deleted'] += 1
            else:
                logger.warning(f'[Celery][Cleanup] 公共文件不存在：{file.file_path}')
                stats['public']['not_found'] += 1
            
            # 【P1修复】物理文件删除成功后，删除数据库记录
            file.delete(hard=True)
            logger.info(f'[Celery][Cleanup] 已删除数据库记录：id={file.id}')
                
        except (OSError, IOError, DatabaseError) as e:
            stats['public']['errors'] += 1
            stats['public']['failed_file_ids'].append(file.id)
            logger.error(f'[Celery][Cleanup] 清理公共文件失败：{file.file_path}, error={e}')
    
    result = {
        'status': 'success',
        'stats': stats,
        'total_checked': stats['private']['checked'] + stats['public']['checked'],
        'total_deleted': stats['private']['deleted'] + stats['public']['deleted'],
        'total_errors': stats['private']['errors'] + stats['public']['errors'],
        'total_not_found': stats['private']['not_found'] + stats['public']['not_found'],
        'retention_days': retention_days,
        'cutoff_time': cutoff_time.isoformat(),
        'dry_run': dry_run
    }
    
    logger.info(f'[Celery][Cleanup] 软删除文件清理完成：{result}')
    return result


@shared_task(bind=True, soft_time_limit=3600, time_limit=7200, queue='document.cleanup')
def cleanup_soft_deleted_folders(self, retention_days=30, dry_run=False):
    """
    【V3新增】清理软删除超过保留期的文件夹
    先删文件，再删文件夹
    
    Args:
        retention_days: 保留天数，默认30天
        dry_run: 仅模拟运行，不实际删除
        
    Returns:
        dict: 清理统计
    """
    from apps.document.models import DocumentFolderPrivate, DocumentFolderPublic, DocumentFilePrivate, DocumentFilePublic
    from apps.document.tasks.cleanup.base import _delete_physical_folder_safe
    
    cutoff_time = timezone.now() - timedelta(days=retention_days)
    
    logger.info(f'[Celery][Cleanup] 开始清理软删除文件夹，保留天数：{retention_days}，截止时间：{cutoff_time}')
    
    stats = {
        'private': {'folders': 0, 'files': 0, 'errors': 0},
        'public': {'folders': 0, 'files': 0, 'errors': 0}
    }
    
    # 【P1-3修复】批量预查询：一次性获取所有过期文件夹及其文件，避免逐文件夹串行查询
    expired_private_folders = list(DocumentFolderPrivate.all_objects.filter(
        is_deleted=True,
        deleted_at__lte=cutoff_time
    ).order_by('deleted_at'))  # 先删最早的

    if expired_private_folders:
        private_folder_ids = [f.id for f in expired_private_folders]
        # 一次性批量查询所有私有文件夹内的文件
        all_private_files = DocumentFilePrivate.all_objects.filter(
            folder_id__in=private_folder_ids, is_deleted=True
        )
        # 按 folder_id 分组
        files_by_folder = {}
        for f in all_private_files:
            files_by_folder.setdefault(f.folder_id, []).append(f)

        for folder in expired_private_folders:
            try:
                if dry_run:
                    logger.info(f'[Celery][Cleanup][DryRun] 将清理私有文件夹：{folder.name} (id={folder.id})')
                    continue

                # 【修复】使用预查询的文件列表
                folder_files = files_by_folder.get(folder.id, [])
                for file in folder_files:
                    try:
                        file.delete(hard=True)
                        stats['private']['files'] += 1
                    except (OSError, IOError, DatabaseError) as e:
                        logger.error(f'[Celery][Cleanup] 清理文件夹内文件失败: file_id={file.id}, error={e}')
                        stats['private']['errors'] += 1

                _delete_physical_folder_safe(folder)
                folder.delete(hard=True)
                stats['private']['folders'] += 1
                logger.info(f'[Celery][Cleanup] 已清理私有文件夹：{folder.name} (id={folder.id})')

            except (OSError, IOError, DatabaseError) as e:
                logger.error(f'[Celery][Cleanup] 清理私有文件夹失败: folder_id={folder.id}, error={e}')
                stats['private']['errors'] += 1

    # 【P1-3修复】批量预查询：公共文件夹同样优化
    expired_public_folders = list(DocumentFolderPublic.all_objects.filter(
        is_deleted=True,
        deleted_at__lte=cutoff_time
    ).order_by('deleted_at'))

    if expired_public_folders:
        public_folder_ids = [f.id for f in expired_public_folders]
        all_public_files = DocumentFilePublic.all_objects.filter(
            folder_id__in=public_folder_ids, is_deleted=True
        )
        files_by_folder = {}
        for f in all_public_files:
            files_by_folder.setdefault(f.folder_id, []).append(f)

        for folder in expired_public_folders:
            try:
                if dry_run:
                    logger.info(f'[Celery][Cleanup][DryRun] 将清理公共文件夹：{folder.name} (id={folder.id})')
                    continue

                folder_files = files_by_folder.get(folder.id, [])
                for file in folder_files:
                    try:
                        file.delete(hard=True)
                        stats['public']['files'] += 1
                    except (OSError, IOError, DatabaseError) as e:
                        logger.error(f'[Celery][Cleanup] 清理文件夹内文件失败: file_id={file.id}, error={e}')
                        stats['public']['errors'] += 1

                _delete_physical_folder_safe(folder)
                folder.delete(hard=True)
                stats['public']['folders'] += 1
                logger.info(f'[Celery][Cleanup] 已清理公共文件夹：{folder.name} (id={folder.id})')

            except (OSError, IOError, DatabaseError) as e:
                logger.error(f'[Celery][Cleanup] 清理公共文件夹失败: folder_id={folder.id}, error={e}')
                stats['public']['errors'] += 1
    
    result = {
        'status': 'success',
        'stats': stats,
        'total_folders': stats['private']['folders'] + stats['public']['folders'],
        'total_files': stats['private']['files'] + stats['public']['files'],
        'total_errors': stats['private']['errors'] + stats['public']['errors'],
        'retention_days': retention_days,
        'cutoff_time': cutoff_time.isoformat(),
        'dry_run': dry_run
    }
    
    logger.info(f'[Celery][Cleanup] 软删除文件夹清理完成：{result}')
    return result
