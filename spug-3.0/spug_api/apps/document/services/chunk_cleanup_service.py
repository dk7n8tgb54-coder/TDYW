# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
分片清理服务
提供过期分片清理相关的服务类
"""
import os
import shutil
import time
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class AgeChecker:
    """过期检查器"""

    def __init__(self, max_age_seconds):
        self.max_age = max_age_seconds
        self.current_time = time.time()

    def is_expired(self, path):
        """
        检查路径是否已过期

        Args:
            path: 文件或目录路径

        Returns:
            是否已过期
        """
        try:
            item_age = self.current_time - os.path.getmtime(path)
            return item_age > self.max_age
        except OSError:
            return False


class DirectoryCleaner:
    """目录清理器"""

    def __init__(self, age_checker):
        self.age_checker = age_checker
        self.cleaned_count = 0
        self.errors = []

    def clean_directory(self, dir_path):
        """
        清理单个目录

        Args:
            dir_path: 目录路径

        Returns:
            是否成功清理
        """
        if not self.age_checker.is_expired(dir_path):
            return False

        try:
            shutil.rmtree(dir_path, ignore_errors=True)
            self.cleaned_count += 1
            return True
        except Exception as e:
            self.errors.append(f'Failed to cleanup {dir_path}: {str(e)}')
            return False

    def try_remove_empty_parent(self, parent_path):
        """
        尝试删除空的父目录

        Args:
            parent_path: 父目录路径
        """
        try:
            if os.path.exists(parent_path) and not os.listdir(parent_path):
                os.rmdir(parent_path)
        except OSError:
            pass  # 忽略删除失败


class FileCleaner:
    """文件清理器"""

    def __init__(self, age_checker, file_extension=None):
        self.age_checker = age_checker
        self.file_extension = file_extension
        self.cleaned_count = 0
        self.errors = []

    def should_clean_file(self, filename):
        """
        检查是否应该清理该文件

        Args:
            filename: 文件名

        Returns:
            是否应该清理
        """
        if self.file_extension is None:
            return True
        return filename.endswith(self.file_extension)

    def clean_file(self, file_path):
        """
        清理单个文件

        Args:
            file_path: 文件路径

        Returns:
            是否成功清理
        """
        if not self.age_checker.is_expired(file_path):
            return False

        try:
            os.remove(file_path)
            self.cleaned_count += 1
            return True
        except Exception as e:
            self.errors.append(f'Failed to delete file {file_path}: {str(e)}')
            return False


class ChunkDirectoryCleaner(DirectoryCleaner):
    """分片目录清理器"""

    def __init__(self, age_checker):
        super().__init__(age_checker)
        self.empty_dirs_cleaned = 0

    def clean_chunk_directory(self, base_dir):
        """
        清理分片目录

        Args:
            base_dir: 基础目录路径
        """
        if not os.path.exists(base_dir):
            return

        for tenant_dir_name in os.listdir(base_dir):
            tenant_dir_path = os.path.join(base_dir, tenant_dir_name)

            if not os.path.isdir(tenant_dir_path):
                continue

            self._clean_tenant_directory(tenant_dir_path)

    def _clean_tenant_directory(self, tenant_dir_path):
        """清理租户目录下的分片目录"""
        for md5_dir_name in os.listdir(tenant_dir_path):
            md5_dir_path = os.path.join(tenant_dir_path, md5_dir_name)

            if not os.path.isdir(md5_dir_path):
                continue

            # 清理过期目录
            if self.clean_directory(md5_dir_path):
                # 尝试删除空租户目录
                self.try_remove_empty_parent(tenant_dir_path)


class TaskFileCleaner(FileCleaner):
    """任务文件清理器"""

    def __init__(self, age_checker):
        super().__init__(age_checker, file_extension='.task')

    def clean_task_files(self, task_dir):
        """
        清理任务文件

        Args:
            task_dir: 任务文件目录
        """
        if not os.path.exists(task_dir):
            return

        for task_file in os.listdir(task_dir):
            if not self.should_clean_file(task_file):
                continue

            task_path = os.path.join(task_dir, task_file)
            self.clean_file(task_path)


class CleanupResult:
    """清理结果"""

    def __init__(self):
        self.cleaned_dirs = 0
        self.cleaned_tasks = 0
        self.errors = []

    def add_directory_cleaner_result(self, cleaner):
        """添加目录清理器结果"""
        self.cleaned_dirs += cleaner.cleaned_count
        self.errors.extend(cleaner.errors)

    def add_file_cleaner_result(self, cleaner):
        """添加文件清理器结果"""
        self.cleaned_tasks += cleaner.cleaned_count
        self.errors.extend(cleaner.errors)

    def to_dict(self):
        """转换为字典"""
        return {
            'status': 'success',
            'cleaned_dirs': self.cleaned_dirs,
            'cleaned_tasks': self.cleaned_tasks,
            'errors': self.errors
        }


class ChunkCleanupService:
    """分片清理服务 - 对外提供统一接口"""

    def __init__(self, days=7):
        self.max_age = days * 24 * 60 * 60  # 转换为秒
        self.age_checker = AgeChecker(self.max_age)
        self.result = CleanupResult()

    def cleanup(self):
        """
        执行清理

        Returns:
            清理结果字典
        """
        try:
            # 清理分片目录
            chunk_cleaner = ChunkDirectoryCleaner(self.age_checker)
            chunk_base_dir = os.path.join(settings.BASE_DIR, 'storage', 'document_chunks')
            chunk_cleaner.clean_chunk_directory(chunk_base_dir)
            self.result.add_directory_cleaner_result(chunk_cleaner)

            # 清理任务文件
            task_cleaner = TaskFileCleaner(self.age_checker)
            merge_task_dir = os.path.join(settings.BASE_DIR, 'storage', 'document_merge_tasks')
            task_cleaner.clean_task_files(merge_task_dir)
            self.result.add_file_cleaner_result(task_cleaner)

            result_dict = self.result.to_dict()
            logger.info(f'[Celery] Cleanup old chunks completed: {result_dict}')
            return result_dict

        except Exception as e:
            logger.error(f'[Celery] Cleanup old chunks failed: {e}')
            return {'status': 'error', 'message': str(e)}
