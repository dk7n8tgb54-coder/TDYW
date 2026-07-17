# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
合并状态查询视图
查询文件合并状态（Celery版本）
"""

import logging
from django.views.generic import View

from libs import json_response
from apps.document.libs.document_auth import document_auth
from apps.document.services.merge_status_handlers import StatusHandlerFactory
from apps.document.services.task_resolver import TaskIdResolver

logger = logging.getLogger(__name__)


class FileMergeStatusView(View):
    """合并状态查询接口（Celery版本）"""

    @document_auth('view')
    def get(self, request):
        """查询文件合并状态"""
        logger.info(f'[Document] FileMergeStatusView called')

        # 解析任务ID
        resolver = TaskIdResolver()
        task_id, merge_task_id, task_data = resolver.resolve(request)

        # 如果没有task_id，尝试从任务文件返回状态
        if not task_id:
            response = resolver.build_response_from_task_data()
            if response:
                return json_response(response)
            return json_response(error='缺少task_id或merge_task_id参数')

        # 查询Celery任务状态
        try:
            from celery.result import AsyncResult
            result = AsyncResult(task_id)

            response = {
                'task_id': task_id,
                'status': result.state.lower(),
            }

            # 使用状态处理器处理不同状态
            handler = StatusHandlerFactory.get_handler(result.state)
            if handler:
                handler.handle(result, response)

            return json_response(response)

        except Exception as e:
            logger.error(f'[Document] Error querying merge task status: {e}', exc_info=True)
            # 【P1-3修复】返回通用错误消息，避免信息泄露
            return json_response(error='查询合并状态失败，请稍后重试')
