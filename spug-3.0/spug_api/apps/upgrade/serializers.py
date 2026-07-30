# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
系统升级模块序列化器

合并后包含：升级记录、升级方案（含预设步骤）、升级记录步骤。
当前服务层自行构造字典返回，序列化器作为统一输出规范保留。
"""
import logging

logger = logging.getLogger(__name__)


class UpgradeRecordSerializer:
    """升级表单序列化器"""

    @staticmethod
    def to_list_view(record):
        """列表页序列化

        Args:
            record: UpgradeRecord 实例
        """
        upgrade_time = record.upgrade_time or ''
        created_at = record.created_at or ''

        return {
            'id': record.id,
            'title': record.title or '',
            'system': record.system,
            'upgrade_type': record.upgrade_type,
            'upgrade_time': upgrade_time,
            'status': record.status,
            'owner': record.owner,
            'upgrade_content': record.upgrade_content or '',
            'impact_scope': record.impact_scope or '',
            'risk_desc': record.risk_desc or '',
            'rollback_plan': record.rollback_plan or '',
            'created_at': created_at,
            'created_by': record.created_by_id,
        }

    @staticmethod
    def to_detail_view(record):
        """详情页序列化

        Args:
            record: UpgradeRecord 实例
        """
        return UpgradeRecordSerializer.to_list_view(record)


class UpgradePlanSerializer:
    """升级方案序列化器（合并原模板+清单）"""

    @staticmethod
    def to_list_view(template, step_count=0):
        """方案列表序列化"""
        return {
            'id': template.id,
            'name': template.name,
            'description': template.description,
            'system': template.system,
            'upgrade_type': template.upgrade_type,
            'step_count': step_count,
            'created_at': template.created_at or '',
            'updated_at': template.updated_at or '',
        }

    @staticmethod
    def to_detail_view(template, steps=None):
        """方案详情序列化（含预设步骤）"""
        data = UpgradePlanSerializer.to_list_view(template, len(steps or []))
        data['steps'] = [
            UpgradePlanStepSerializer.to_view(s) for s in (steps or [])
        ]
        return data


class UpgradePlanStepSerializer:
    """方案预设步骤序列化器"""

    @staticmethod
    def to_view(step):
        """步骤序列化"""
        return {
            'id': step.id,
            'template_id': step.template_id,
            'phase': step.phase,
            'title': step.title,
            'description': step.description,
            'sequence': step.sequence,
            'is_required': step.is_required,
        }


class UpgradeRecordStepSerializer:
    """升级记录步骤序列化器"""

    @staticmethod
    def to_view(step):
        """步骤序列化"""
        return {
            'id': step.id,
            'upgrade_id': step.upgrade_id,
            'checklist_id': step.checklist_id,
            'title': step.title,
            'description': step.description,
            'sequence': step.sequence,
            'is_required': step.is_required,
            'status': step.status,
            'status_display': step.get_status_display(),
            'completed_by': step.completed_by,
            'completed_at': step.completed_at,
            'remark': step.remark,
            'created_at': step.created_at or '',
        }
