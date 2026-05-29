"""
文件操作工具函数
提供文件和文件夹操作的公共功能
"""

import os
import shutil
import logging
from typing import Optional, List, Tuple, Callable
from functools import wraps
from django.db import transaction

logger = logging.getLogger(__name__)


def safe_delete_file(file_path: str, raise_on_error: bool = False) -> bool:
    """
    安全删除文件
    
    Args:
        file_path: 文件路径
        raise_on_error: 出错时是否抛出异常
        
    Returns:
        bool: 是否成功删除
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.debug(f'文件已删除: {file_path}')
            return True
        return False
    except Exception as e:
        logger.error(f'删除文件失败 {file_path}: {e}')
        if raise_on_error:
            raise
        return False


def safe_delete_folder(folder_path: str, raise_on_error: bool = False) -> bool:
    """
    安全删除文件夹（递归删除）
    
    Args:
        folder_path: 文件夹路径
        raise_on_error: 出错时是否抛出异常
        
    Returns:
        bool: 是否成功删除
    """
    try:
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path)
            logger.debug(f'文件夹已删除: {folder_path}')
            return True
        return False
    except Exception as e:
        logger.error(f'删除文件夹失败 {folder_path}: {e}')
        if raise_on_error:
            raise
        return False


def safe_copy_file(src: str, dst: str, raise_on_error: bool = False) -> bool:
    """
    安全复制文件
    
    Args:
        src: 源文件路径
        dst: 目标文件路径
        raise_on_error: 出错时是否抛出异常
        
    Returns:
        bool: 是否成功复制
    """
    try:
        # 确保目标目录存在
        dst_dir = os.path.dirname(dst)
        if dst_dir and not os.path.exists(dst_dir):
            os.makedirs(dst_dir, exist_ok=True)
        
        shutil.copy2(src, dst)
        logger.debug(f'文件已复制: {src} -> {dst}')
        return True
    except Exception as e:
        logger.error(f'复制文件失败 {src} -> {dst}: {e}')
        if raise_on_error:
            raise
        return False


def safe_copy_folder(src: str, dst: str, raise_on_error: bool = False) -> bool:
    """
    安全复制文件夹（递归复制）
    
    Args:
        src: 源文件夹路径
        dst: 目标文件夹路径
        raise_on_error: 出错时是否抛出异常
        
    Returns:
        bool: 是否成功复制
    """
    try:
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        logger.debug(f'文件夹已复制: {src} -> {dst}')
        return True
    except Exception as e:
        logger.error(f'复制文件夹失败 {src} -> {dst}: {e}')
        if raise_on_error:
            raise
        return False


def safe_move_file(src: str, dst: str, raise_on_error: bool = False) -> bool:
    """
    安全移动文件
    
    Args:
        src: 源文件路径
        dst: 目标文件路径
        raise_on_error: 出错时是否抛出异常
        
    Returns:
        bool: 是否成功移动
    """
    try:
        # 确保目标目录存在
        dst_dir = os.path.dirname(dst)
        if dst_dir and not os.path.exists(dst_dir):
            os.makedirs(dst_dir, exist_ok=True)
        
        shutil.move(src, dst)
        logger.debug(f'文件已移动: {src} -> {dst}')
        return True
    except Exception as e:
        logger.error(f'移动文件失败 {src} -> {dst}: {e}')
        if raise_on_error:
            raise
        return False


def ensure_dir_exists(path: str) -> bool:
    """
    确保目录存在，不存在则创建
    
    Args:
        path: 目录路径
        
    Returns:
        bool: 目录是否存在
    """
    try:
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            logger.debug(f'目录已创建: {path}')
        return True
    except Exception as e:
        logger.error(f'创建目录失败 {path}: {e}')
        return False


def get_folder_size(folder_path: str) -> int:
    """
    计算文件夹大小（字节）
    
    Args:
        folder_path: 文件夹路径
        
    Returns:
        int: 文件夹大小（字节）
    """
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(folder_path):
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                if os.path.exists(file_path):
                    total_size += os.path.getsize(file_path)
    except Exception as e:
        logger.error(f'计算文件夹大小失败 {folder_path}: {e}')
    return total_size


def get_file_size(file_path: str) -> int:
    """
    获取文件大小（字节）
    
    Args:
        file_path: 文件路径
        
    Returns:
        int: 文件大小（字节），失败返回0
    """
    try:
        return os.path.getsize(file_path) if os.path.exists(file_path) else 0
    except Exception as e:
        logger.error(f'获取文件大小失败 {file_path}: {e}')
        return 0


def format_file_size(size_bytes: int) -> str:
    """
    格式化文件大小显示
    
    Args:
        size_bytes: 文件大小（字节）
        
    Returns:
        str: 格式化后的大小字符串
    """
    if size_bytes is None or size_bytes == 0:
        return '0 B'
    
    if size_bytes < 0:
        return '-'
    
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    size = float(size_bytes)
    unit_index = 0
    
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    
    if unit_index == 0:
        return f'{int(size)} {units[unit_index]}'
    
    return f'{size:.2f} {units[unit_index]}'


def delete_folder_contents_iterative(
    folder,
    FolderModel,
    FileModel,
    user,
    delete_file_func: Optional[Callable] = None
) -> Tuple[int, int]:
    """
    迭代方式删除文件夹内容
    
    Args:
        folder: 要删除的文件夹对象
        FolderModel: 文件夹模型类
        FileModel: 文件模型类
        user: 操作用户
        delete_file_func: 删除单个文件的回调函数
        
    Returns:
        Tuple[int, int]: (删除的文件数, 删除的文件夹数)
    """
    deleted_files = 0
    deleted_folders = 0
    
    stack = [folder.id]
    folders_to_delete = []
    
    while stack:
        current_id = stack.pop()
        folders_to_delete.append(current_id)
        
        # 获取子文件夹
        child_folders = FolderModel.objects.filter(parent_id=current_id)
        for child in child_folders:
            stack.append(child.id)
    
    # 删除所有文件夹中的文件
    for folder_id in folders_to_delete:
        files = FileModel.objects.filter(parent_id=folder_id)
        for file_obj in files:
            try:
                if delete_file_func:
                    delete_file_func(file_obj, user)
                else:
                    file_obj.delete(hard=True)
                deleted_files += 1
            except Exception as e:
                logger.error(f'删除文件失败 {file_obj.id}: {e}')
    
    # 删除所有文件夹（逆序，从最深层开始）
    for folder_id in reversed(folders_to_delete):
        try:
            folder_obj = FolderModel.objects.filter(id=folder_id).first()
            if folder_obj:
                folder_obj.delete()
                deleted_folders += 1
        except Exception as e:
            logger.error(f'删除文件夹失败 {folder_id}: {e}')
    
    return deleted_files, deleted_folders


def transactional_operation(view_method):
    """
    事务操作装饰器
    确保批量操作在事务中执行
    """
    @wraps(view_method)
    def wrapper(self, request, *args, **kwargs):
        with transaction.atomic():
            return view_method(self, request, *args, **kwargs)
    return wrapper


def chunked_iterator(queryset, chunk_size=100):
    """
    分块迭代查询集
    用于处理大批量数据，避免内存溢出
    
    Args:
        queryset: Django QuerySet
        chunk_size: 每块大小
        
    Yields:
        查询集中的对象
    """
    start = 0
    while True:
        chunk = queryset[start:start + chunk_size]
        if not chunk:
            break
        for item in chunk:
            yield item
        start += chunk_size


def batch_process(items: List, batch_size: int, process_func: Callable) -> Tuple[int, int]:
    """
    批量处理函数
    
    Args:
        items: 待处理项目列表
        batch_size: 批次大小
        process_func: 处理函数，接收批次列表，返回(成功数, 失败数)
        
    Returns:
        Tuple[int, int]: (总成功数, 总失败数)
    """
    total_success = 0
    total_failed = 0
    
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        success, failed = process_func(batch)
        total_success += success
        total_failed += failed
    
    return total_success, total_failed
