# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
文件合并任务的辅助函数
【修复】从 merge.py 拆分出来，降低函数复杂度
"""
import os
import json
import shutil
import logging
import time
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def update_task_file(merge_task_file, file_name, file_hash, username, is_public,
                     start_time, job_id, status, progress=0, message='', result=None):
    """更新任务文件状态"""
    try:
        task_data = {
            'status': status.lower(),
            'file_name': file_name,
            'file_hash': file_hash,
            'user': username,
            'is_public': is_public,
            'start_time': start_time,
            'task_id': job_id,
            'progress': progress,
            'message': message,
            'updated_at': time.time()
        }
        if result:
            task_data['result'] = result
        with open(merge_task_file, 'w') as f:
            f.write(json.dumps(task_data))
    except Exception as e:
        logger.warning(f'[Celery] Failed to update task file: {e}')


def verify_chunk_integrity(chunk_dir, total_chunks):
    """验证分片完整性"""
    missing_chunks = []
    for i in range(total_chunks):
        chunk_path = os.path.join(chunk_dir, f"{i}.part")
        if not os.path.exists(chunk_path):
            missing_chunks.append(i)
            logger.warning(f'[Celery] Missing chunk: {i}')
    return missing_chunks


def merge_chunks_to_file(file_path, chunk_dir, total_chunks, progress_callback=None):
    """合并分片到目标文件"""
    with open(file_path, 'wb+') as merged_file:
        logger.info(f'[Celery] Created target file: {file_path}')
        for i in range(total_chunks):
            chunk_path = os.path.join(chunk_dir, f"{i}.part")
            
            try:
                with open(chunk_path, 'rb') as chunk_file:
                    shutil.copyfileobj(chunk_file, merged_file, 1024*1024)
            except (IOError, OSError) as e:
                raise RuntimeError(f'读取分片{i}失败: {str(e)}') from e
            
            # 每10个分片更新进度
            if (i + 1) % 10 == 0 or i == total_chunks - 1:
                if progress_callback:
                    progress = 30 + int((i + 1) / total_chunks * 30)
                    progress_callback(progress, f'已合并 {i+1}/{total_chunks} 分片')


def verify_file_integrity(file_path, expected_size, expected_hash, calculate_file_md5):
    """验证文件完整性（大小和MD5）"""
    # 验证文件大小
    actual_size = os.path.getsize(file_path)
    if actual_size != expected_size:
        return False, f'文件大小不匹配: 期望 {expected_size}, 实际 {actual_size}'
    
    # 验证MD5（如果是全量MD5）
    if expected_hash.startswith('sv1_'):
        logger.info(f'[Celery] Using sampling MD5, skipping full MD5 verification: {expected_hash}')
        return True, None
    
    merged_file_md5 = calculate_file_md5(file_path)
    if merged_file_md5 != expected_hash:
        return False, f'文件MD5校验失败，文件内容可能已被篡改'
    
    return True, None


def create_file_record(FileModel, FolderModel, file_data, folder, user, 
                       get_mime_type, create_model_instance):
    """创建文件记录"""
    new_file = create_model_instance(
        FileModel,
        name=file_data['logical_name'],
        display_name=file_data['display_name'],
        physical_name=file_data['physical_name'],
        folder=folder,
        file_path=file_data['file_path'],
        file_size=file_data['file_size'],
        file_type=get_mime_type(file_data['file_name']),
        created_by=user
    )
    return new_file


def cleanup_on_error(file_path, chunk_dir):
    """出错时清理文件"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f'[Celery] Cleaned up file on error: {file_path}')
    except Exception as e:
        logger.warning(f'[Celery] Failed to cleanup file: {e}')


def cleanup_chunks(chunk_dir):
    """清理分片目录"""
    if os.path.exists(chunk_dir):
        shutil.rmtree(chunk_dir, ignore_errors=True)


def update_transfer_status(transfer_id, status, **kwargs):
    """更新传输记录状态"""
    if not transfer_id:
        return
    
    try:
        from apps.document.models import DocumentTransfer
        transfer = DocumentTransfer.objects.filter(id=transfer_id).first()
        if transfer:
            transfer.status = status.value if hasattr(status, 'value') else status
            for key, value in kwargs.items():
                setattr(transfer, key, value)
            transfer.save()
    except Exception as e:
        logger.error(f'[Celery] Failed to update transfer status: {e}')


def cleanup_and_fail_transfer(transfer_id, error_message, TransferStatus):
    """清理并标记传输失败"""
    if transfer_id:
        update_transfer_status(transfer_id, TransferStatus.FAILED, error_message=error_message)


def prepare_file_data(job_data, upload_dir):
    """准备文件数据"""
    return {
        'file_name': job_data['file_name'],
        'file_hash': job_data['file_hash'],
        'file_path': job_data['file_path'],
        'physical_name': job_data.get('physical_name', os.path.basename(job_data['file_path'])),
        'logical_name': job_data.get('logical_name', os.path.basename(job_data['file_path'])),
        'display_name': job_data.get('display_name', job_data['file_name']),
        'chunk_dir': job_data['chunk_dir'],
        'file_size': job_data['file_size'],
        'total_chunks': job_data['total_chunks'],
        'folder_id': job_data.get('folder_id'),
        'is_public': job_data.get('is_public', False),
        'user_id': job_data['user_id'],
        'username': job_data.get('username', 'unknown'),
        'tenant_id': job_data.get('tenant_id', ''),
        'transfer_id': job_data.get('transfer_id'),
    }
