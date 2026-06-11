# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
清理任务 - 软删除数据清理
"""
import logging
from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from django.db import DatabaseError
from apps.document.exceptions import DocumentPhysicalDeleteError

logger = logging.getLogger(__name__)


def _cleanup_space_files(FileModel, space_name, cutoff_time, dry_run):
    """
    清理单个空间的软删除文件

    Args:
        FileModel: 文件模型类
        space_name: 空间名称
        cutoff_time: 截止时间
        dry_run: 是否模拟运行

    Returns:
        dict: {'checked': N, 'deleted': N, 'errors': N, 'not_found': N, 'failed_file_ids': []}
    """
    space_stats = {'checked': 0, 'deleted': 0, 'errors': 0, 'not_found': 0, 'failed_file_ids': []}

    files = FileModel.all_objects.filter(
        is_deleted=True,
        deleted_at__lte=cutoff_time
    ).order_by().iterator(chunk_size=1000)

    for file in files:
        space_stats['checked'] += 1

        if dry_run:
            logger.info(f'[Celery][Cleanup][DryRun] 将清理{space_name}文件：{file.file_path}')
            continue

        try:
            # 统一走模型层 delete(hard=True)，内部调用 safe_delete_document_file
            # 失败时会自动标记 is_pending_clean / clean_retry_count / last_clean_attempt
            file.delete(hard=True)
            logger.info(f'[Celery][Cleanup] 已清理{space_name}文件：id={file.id}')
            space_stats['deleted'] += 1

        except DocumentPhysicalDeleteError as e:
            logger.warning(f'[Celery][Cleanup] {space_name}文件物理删除失败，已标记待清理: id={file.id}, path={e.file_path}')
        except (OSError, IOError, DatabaseError) as e:
            space_stats['errors'] += 1
            space_stats['failed_file_ids'].append(file.id)
            logger.error(f'[Celery][Cleanup] 清理{space_name}文件失败：id={file.id}, error={e}')

    return space_stats


def _cleanup_space_folders(FolderModel, FileModel, space_name, cutoff_time, dry_run):
    """
    清理单个空间的软删除文件夹（先删文件再删文件夹）

    Args:
        FolderModel: 文件夹模型类
        FileModel: 文件模型类
        space_name: 空间名称
        cutoff_time: 截止时间
        dry_run: 是否模拟运行

    Returns:
        dict: {'folders': N, 'files': N, 'errors': N}
    """
    from apps.document.tasks.cleanup.base import _delete_physical_folder_safe

    space_stats = {'folders': 0, 'files': 0, 'errors': 0}

    expired_folders = list(FolderModel.all_objects.filter(
        is_deleted=True,
        deleted_at__lte=cutoff_time
    ).order_by('deleted_at'))

    if not expired_folders:
        return space_stats

    # 批量预查询：一次性获取所有文件，按 folder_id 分组
    folder_ids = [f.id for f in expired_folders]
    all_files = FileModel.all_objects.filter(folder_id__in=folder_ids, is_deleted=True)
    files_by_folder = {}
    for f in all_files:
        files_by_folder.setdefault(f.folder_id, []).append(f)

    for folder in expired_folders:
        try:
            if dry_run:
                logger.info(f'[Celery][Cleanup][DryRun] 将清理{space_name}文件夹：{folder.name} (id={folder.id})')
                continue

            # 删除文件夹内的文件
            folder_files = files_by_folder.get(folder.id, [])
            for file in folder_files:
                try:
                    file.delete(hard=True)
                    space_stats['files'] += 1
                except DocumentPhysicalDeleteError:
                    logger.warning(f'[Celery][Cleanup] 文件夹内文件物理删除失败，已标记待清理: file_id={file.id}')
                except (OSError, IOError, DatabaseError) as e:
                    logger.error(f'[Celery][Cleanup] 清理文件夹内文件失败: file_id={file.id}, error={e}')
                    space_stats['errors'] += 1

            _delete_physical_folder_safe(folder)
            folder.delete(hard=True)
            space_stats['folders'] += 1
            logger.info(f'[Celery][Cleanup] 已清理{space_name}文件夹：{folder.name} (id={folder.id})')

        except DocumentPhysicalDeleteError:
            logger.warning(f'[Celery][Cleanup] {space_name}文件夹物理删除失败，已标记待清理: folder_id={folder.id}')
        except (OSError, IOError, DatabaseError) as e:
            logger.error(f'[Celery][Cleanup] 清理{space_name}文件夹失败: folder_id={folder.id}, error={e}')
            space_stats['errors'] += 1

    return space_stats


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

    private_stats = _cleanup_space_files(DocumentFilePrivate, '私有', cutoff_time, dry_run)
    public_stats = _cleanup_space_files(DocumentFilePublic, '公共', cutoff_time, dry_run)

    result = {
        'status': 'success',
        'stats': {'private': private_stats, 'public': public_stats},
        'total_checked': private_stats['checked'] + public_stats['checked'],
        'total_deleted': private_stats['deleted'] + public_stats['deleted'],
        'total_errors': private_stats['errors'] + public_stats['errors'],
        'total_not_found': private_stats['not_found'] + public_stats['not_found'],
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

    cutoff_time = timezone.now() - timedelta(days=retention_days)
    logger.info(f'[Celery][Cleanup] 开始清理软删除文件夹，保留天数：{retention_days}，截止时间：{cutoff_time}')

    private_stats = _cleanup_space_folders(
        DocumentFolderPrivate, DocumentFilePrivate, '私有', cutoff_time, dry_run)
    public_stats = _cleanup_space_folders(
        DocumentFolderPublic, DocumentFilePublic, '公共', cutoff_time, dry_run)

    result = {
        'status': 'success',
        'stats': {'private': private_stats, 'public': public_stats},
        'total_folders': private_stats['folders'] + public_stats['folders'],
        'total_files': private_stats['files'] + public_stats['files'],
        'total_errors': private_stats['errors'] + public_stats['errors'],
        'retention_days': retention_days,
        'cutoff_time': cutoff_time.isoformat(),
        'dry_run': dry_run
    }

    logger.info(f'[Celery][Cleanup] 软删除文件夹清理完成：{result}')
    return result
