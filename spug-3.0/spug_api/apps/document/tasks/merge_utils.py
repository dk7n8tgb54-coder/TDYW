# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
文件合并任务工具函数
【修复】从 merge.py 拆分出来的辅助函数
"""
import os
import shutil
import json
import time
import logging
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


def validate_chunks(chunk_dir, total_chunks):
    """
    验证分片完整性
    
    Returns:
        tuple: (is_valid, missing_chunks)
    """
    missing_chunks = []
    for i in range(total_chunks):
        chunk_path = os.path.join(chunk_dir, f"{i}.part")
        if not os.path.exists(chunk_path):
            missing_chunks.append(i)
            logger.warning(f'[Celery] Missing chunk: {i}')
    
    return len(missing_chunks) == 0, missing_chunks


def merge_chunks_to_file(chunk_dir, file_path, total_chunks, progress_callback=None):
    """
    合并分片到目标文件
    
    Args:
        chunk_dir: 分片目录
        file_path: 目标文件路径
        total_chunks: 总分片数
        progress_callback: 进度回调函数(percent, message)
    
    Returns:
        tuple: (success, error_message)
    """
    try:
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
                    progress = 30 + int((i + 1) / total_chunks * 30)
                    if progress_callback:
                        progress_callback(progress, f'已合并 {i+1}/{total_chunks} 分片')
        
        return True, None
    except (IOError, OSError) as e:
        error_msg = f'文件合并IO错误: {str(e)}'
        logger.error(f'[Celery] {error_msg}')
        return False, error_msg


def verify_file_size(file_path, expected_size):
    """
    验证文件大小
    
    Returns:
        tuple: (is_valid, actual_size, error_message)
    """
    actual_size = os.path.getsize(file_path)
    if actual_size != expected_size:
        error_msg = f'文件大小不匹配: 期望 {expected_size}, 实际 {actual_size}'
        logger.error(f'[Celery] {error_msg}')
        return False, actual_size, error_msg
    return True, actual_size, None


def verify_file_md5(file_path, file_hash, calculate_md5_func):
    """
    验证文件MD5
    【任务3.3】支持抽样MD5：对于sv1_前缀的抽样MD5，跳过全量MD5校验
    
    Args:
        file_path: 文件路径
        file_hash: 期望的MD5值
        calculate_md5_func: 计算MD5的函数
    
    Returns:
        tuple: (is_valid, error_message)
    """
    try:
        if file_hash.startswith('sv1_'):
            # 抽样MD5只用于标识文件，不进行完整性校验
            logger.info(f'[Celery] Using sampling MD5, skipping full MD5 verification: {file_hash}')
            return True, None
        else:
            # 全量MD5校验
            merged_file_md5 = calculate_md5_func(file_path)
            if merged_file_md5 != file_hash:
                error_msg = '文件MD5校验失败，文件内容可能已被篡改'
                logger.error(f'[Celery] MD5 mismatch: expected={file_hash}, got={merged_file_md5}')
                return False, error_msg
            return True, None
    except Exception as e:
        raise  # MD5计算异常可重试


def create_file_record(file_name, file_path, file_size, folder, user, is_public,
                       physical_name, logical_name, display_name, get_models_func,
                       create_instance_func, get_mime_type_func):
    """
    创建文件记录
    
    Returns:
        tuple: (file_instance, error_message)
    """
    try:
        FileModel = get_models_func('file')
        logger.info(f'[Celery] Creating file instance: physical_name={physical_name}, '
                   f'logical_name={logical_name}, display_name={display_name}')
        
        new_file = create_instance_func(
            FileModel,
            name=logical_name,
            display_name=display_name,
            physical_name=physical_name,
            folder=folder,
            file_path=file_path,
            file_size=file_size,
            file_type=get_mime_type_func(file_name),
            created_by=user
        )
        logger.info(f'[Celery] File instance created: id={new_file.id if new_file else None}')
        return new_file, None
    except Exception as e:
        error_msg = f'创建文件记录失败: {str(e)}'
        logger.error(f'[Celery] {error_msg}')
        raise  # 数据库异常可重试


def update_transfer_status(transfer_id, status, **kwargs):
    """更新传输记录状态"""
    if not transfer_id:
        return
    
    try:
        from apps.document.models import DocumentTransfer
        transfer = DocumentTransfer.objects.filter(id=transfer_id).order_by().first()
        if transfer:
            transfer.status = status.value if hasattr(status, 'value') else status
            for key, value in kwargs.items():
                setattr(transfer, key, value)
            transfer.save()
    except Exception as e:
        logger.error(f'[Celery] Failed to update transfer status: {e}')


def cleanup_and_fail_transfer(transfer_id, error_message):
    """清理并标记传输失败"""
    if transfer_id:
        from apps.document.constants import TransferStatus
        update_transfer_status(transfer_id, TransferStatus.FAILED, error_message=error_message)


def cleanup_on_error(file_path, chunk_dir):
    """出错时清理文件"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f'[Celery] Cleaned up file on error: {file_path}')
    except Exception as e:
        logger.warning(f'[Celery] Failed to cleanup file: {e}')


def get_folder_and_user(folder_id, is_public, tenant_id, user_id):
    """
    获取文件夹和用户对象
    
    Returns:
        tuple: (folder, user, error_message)
    """
    from apps.document.libs.document_utils import get_folder_model, get_file_model
    from apps.account.models import User
    
    try:
        FolderModel = get_folder_model(is_public=is_public)
    except Exception as model_error:
        logger.error(f'[Celery] Failed to load FolderModel: {model_error}')
        raise  # 模型加载异常可重试
    
    folder = None
    if folder_id:
        folder_query = FolderModel.objects.filter(pk=folder_id).order_by()
        if not is_public and tenant_id:
            folder_query = folder_query.filter(tenant_id=tenant_id)
        folder = folder_query.first()
    
    user = User.objects.filter(id=user_id).first()
    logger.info(f'[Celery] Lookup results: folder={folder}, user={user}')
    
    if not user:
        error_msg = f'用户不存在: user_id={user_id}'
        logger.error(f'[Celery] {error_msg}')
        return folder, user, error_msg
    
    return folder, user, None
