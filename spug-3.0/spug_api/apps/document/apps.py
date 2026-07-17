# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

"""
Document应用配置
"""
import logging
from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)


class DocumentConfig(AppConfig):
    """Document应用配置类"""
    default_auto_field = 'django.db.models.AutoField'
    name = 'apps.document'
    verbose_name = '文档管理'

    def ready(self):
        """
        Django应用启动时的初始化逻辑
        【最佳工程实践】在ready()中安全导入celery配置
        此时所有App已注册完成，不会触发AppRegistryNotReady错误
        """
        # 注册系统目录绑定完整性检查
        from . import checks  # noqa: F401

        logger.info('[DocumentConfig] Document app ready')
        
        # 【最佳工程实践】延迟导入Celery Beat配置
        # 避免Django启动时过早导入document模块导致模型加载问题
        try:
            from .celery_config import CELERY_BEAT_SCHEDULE
            # 合并到Django settings
            if CELERY_BEAT_SCHEDULE:
                settings.CELERY_BEAT_SCHEDULE.update(CELERY_BEAT_SCHEDULE)
                logger.info(f'[DocumentConfig] Registered {len(CELERY_BEAT_SCHEDULE)} Celery Beat tasks')
        except Exception as e:
            logger.warning(f'[DocumentConfig] Failed to load Celery Beat config: {e}')
