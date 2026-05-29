# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
升级模板服务 - CRUD
"""
import logging
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter

logger = logging.getLogger(__name__)


class TemplateService:
    """升级模板服务"""

    @staticmethod
    def get_list(user):
        """获取模板列表

        Args:
            user: 当前请求用户

        Returns:
            list: 模板序列化列表
        """
        from ..models_template import UpgradeTemplate

        queryset = apply_tenant_filter(UpgradeTemplate.objects.all(), user)
        queryset = queryset.order_by('-is_default', 'name', '-id')

        return [
            {
                'id': t.id,
                'name': t.name,
                'system': t.system,
                'upgrade_type': t.upgrade_type,
                'version': t.version,
                'owner': t.owner,
                'status': t.status,
                'detail_content': t.detail_content,
                'is_default': t.is_default,
                'created_at': t.created_at,
            }
            for t in queryset
        ]

    @staticmethod
    def create_template(user, data):
        """创建模板

        Args:
            user: 当前请求用户
            data: 模板数据对象

        Returns:
            tuple: (template, error)
        """
        from ..models_template import UpgradeTemplate

        name = getattr(data, 'name', None)
        if not name:
            return None, '请输入模板名称'

        # 同租户内模板名称唯一
        if UpgradeTemplate.objects.filter(
            tenant_id=user.tenant_id,
            name=name
        ).exists():
            return None, f'模板名称 [{name}] 已存在'

        try:
            now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            template = UpgradeTemplate.objects.create(
                tenant_id=user.tenant_id,
                name=name,
                system=getattr(data, 'system', '') or '',
                upgrade_type=getattr(data, 'upgrade_type', '') or '',
                version=getattr(data, 'version', '') or '',
                owner=getattr(data, 'owner', '') or '',
                status=getattr(data, 'status', '处理中') or '处理中',
                detail_content=getattr(data, 'detail_content', '') or '',
                is_default=getattr(data, 'is_default', False) or False,
                created_at=now_str,
                created_by=user,
            )
            return template, None
        except Exception as e:
            logger.error(f'[Upgrade] 创建模板失败: {e}', exc_info=True)
            return None, f'创建模板失败: {str(e)}'

    @staticmethod
    def update_template(template_id, user, data):
        """更新模板

        Args:
            template_id: 模板ID
            user: 当前请求用户
            data: 更新数据对象

        Returns:
            tuple: (template, error)
        """
        from ..models_template import UpgradeTemplate

        template = apply_tenant_filter(
            UpgradeTemplate.objects.filter(pk=template_id), user
        ).first()
        if not template:
            return None, '模板不存在或无权限'

        editable_fields = ['name', 'system', 'upgrade_type', 'version',
                           'owner', 'status', 'detail_content', 'is_default']
        for field in editable_fields:
            value = getattr(data, field, None)
            if value is not None:
                setattr(template, field, value)

        template.updated_at = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        template.save()

        return template, None

    @staticmethod
    def delete_template(template_id, user):
        """删除模板

        Args:
            template_id: 模板ID
            user: 当前请求用户

        Returns:
            str: 错误消息，None 表示成功
        """
        from ..models_template import UpgradeTemplate

        template = apply_tenant_filter(
            UpgradeTemplate.objects.filter(pk=template_id), user
        ).first()
        if not template:
            return '模板不存在或无权限'

        try:
            template.delete()
            return None
        except Exception as e:
            logger.error(f'[Upgrade] 删除模板失败: {e}', exc_info=True)
            return f'删除模板失败: {str(e)}'
