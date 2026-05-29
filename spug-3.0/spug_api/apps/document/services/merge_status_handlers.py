# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
合并状态处理器
使用状态模式处理不同的Celery任务状态
"""
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


class StatusHandler(ABC):
    """状态处理器基类"""

    @abstractmethod
    def handle(self, result, response):
        """
        处理状态

        Args:
            result: Celery AsyncResult对象
            response: 响应字典
        """
        pass


class PendingHandler(StatusHandler):
    """PENDING状态处理器"""

    def handle(self, result, response):
        response['message'] = '任务等待中'


class StartedHandler(StatusHandler):
    """STARTED状态处理器"""

    def handle(self, result, response):
        response['message'] = '任务开始执行'
        response['progress'] = 5


class ProgressHandler(StatusHandler):
    """PROGRESS状态处理器"""

    def handle(self, result, response):
        meta = result.info or {}
        response.update(meta)


class SuccessHandler(StatusHandler):
    """SUCCESS状态处理器"""

    def handle(self, result, response):
        result_data = result.result or {}
        response['status'] = result_data.get('status', 'completed').lower()
        response['file_id'] = result_data.get('file_id')
        response['file_name'] = result_data.get('file_name')


class FailureHandler(StatusHandler):
    """FAILURE状态处理器"""

    def handle(self, result, response):
        response['status'] = 'failed'
        response['error'] = str(result.result)


class StatusHandlerFactory:
    """状态处理器工厂"""

    _handlers = {
        'PENDING': PendingHandler,
        'STARTED': StartedHandler,
        'PROGRESS': ProgressHandler,
        'SUCCESS': SuccessHandler,
        'FAILURE': FailureHandler,
    }

    @classmethod
    def get_handler(cls, state: str) -> StatusHandler:
        """
        获取对应状态的处理

        Args:
            state: Celery任务状态

        Returns:
            StatusHandler实例或None
        """
        handler_class = cls._handlers.get(state)
        if handler_class:
            return handler_class()
        logger.warning(f'[Document] Unknown task state: {state}')
        return None

    @classmethod
    def register_handler(cls, state: str, handler_class: type):
        """
        注册新的状态处理器（用于扩展）

        Args:
            state: 状态名称
            handler_class: 处理器类
        """
        cls._handlers[state] = handler_class
