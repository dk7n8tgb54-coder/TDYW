# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
任务ID解析器
处理task_id和merge_task_id的解析逻辑
"""
import os
import json
import logging
from django.conf import settings
from apps.document.libs.document_utils import get_merge_task_file_path

logger = logging.getLogger(__name__)


class TaskIdResolver:
    """任务ID解析器"""

    def __init__(self):
        self.task_id = None
        self.merge_task_id = None
        self.task_data = None
        self.system_folder = None

    def resolve(self, request) -> tuple:
        """
        从请求中解析任务ID

        【P2修复】增加任务归属校验：验证 task_id/merge_task_id 属于当前用户。

        Args:
            request: HTTP请求对象

        Returns:
            (task_id, merge_task_id, task_data) 元组
            task_data 是从任务文件中读取的数据（如果有）
        """
        self.task_id = request.GET.get('task_id')
        self.merge_task_id = request.GET.get('merge_task_id')
        self.system_folder = request.GET.get('system_folder')
        self.request_user = getattr(request, 'user', None)

        # 如果提供了task_id，先校验归属再返回
        if self.task_id:
            # 【P2修复】校验 celery_task_id 归属
            if not self._validate_task_ownership(self.task_id):
                logger.warning(
                    f'[Document] Task ownership check failed: task_id={self.task_id}, '
                    f'user={getattr(self.request_user, "id", None)}'
                )
                return None, None, None
            return self.task_id, self.merge_task_id, None

        # 如果提供了merge_task_id，尝试从任务文件中读取task_id
        if self.merge_task_id:
            self.task_data = self._read_task_file(self.merge_task_id)
            if self.task_data:
                # 【P2修复】校验任务文件中的 user_id 是否匹配当前用户
                task_user_id = self.task_data.get('user_id')
                if task_user_id and self.request_user and task_user_id != self.request_user.id:
                    logger.warning(
                        f'[Document] Merge task file user mismatch: '
                        f'file_user={task_user_id}, request_user={self.request_user.id}'
                    )
                    return None, None, None

                self.task_id = self.task_data.get('task_id')
                if self.task_id:
                    return self.task_id, self.merge_task_id, self.task_data

        # 无法获取task_id，但可能有任务文件数据
        return None, self.merge_task_id, self.task_data

    def _validate_task_ownership(self, celery_task_id: str) -> bool:
        """【P2修复】验证 celery_task_id 归属当前用户

        通过查询 DocumentTransfer 表验证 task_id 对应的传输记录属于当前用户。
        超管跳过校验。
        """
        if not self.request_user:
            return False

        if getattr(self.request_user, 'is_supper', False):
            return True

        try:
            from apps.document.models import DocumentTransfer
            # 通过 celery_task_id 查询传输记录
            transfer = DocumentTransfer.objects.filter(
                celery_task_id=celery_task_id
            ).only('user_id', 'tenant_id').first()

            if not transfer:
                # 没有找到记录，可能是 Celery 原生任务（非文件合并任务）
                # 允许通过，下游 AsyncResult 查询不会泄露敏感信息
                return True

            # 校验用户归属
            if transfer.user_id != self.request_user.id:
                return False

            return True
        except Exception as e:
            logger.error(f'[Document] Task ownership validation error: {e}')
            # 校验出错时 fail-closed
            return False

    def _read_task_file(self, merge_task_id: str) -> dict:
        """
        读取任务文件

        Args:
            merge_task_id: 合并任务ID

        Returns:
            任务数据字典或None
        """
        merge_task_file = get_merge_task_file_path(
            merge_task_id,
            system_folder=self.system_folder,
        )

        if not os.path.exists(merge_task_file):
            return None

        try:
            with open(merge_task_file, 'r') as f:
                return json.loads(f.read())
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f'[Document] Failed to read task file: {e}')
            return None

    def build_response_from_task_data(self) -> dict:
        """
        从任务文件数据构建响应

        Returns:
            响应字典或None
        """
        if not self.task_data or not self.merge_task_id:
            return None

        return {
            'merge_task_id': self.merge_task_id,
            'status': self.task_data.get('status', 'unknown'),
            'message': '从本地文件获取状态',
            'file_name': self.task_data.get('file_name'),
            'progress': self.task_data.get('progress', 0)
        }
