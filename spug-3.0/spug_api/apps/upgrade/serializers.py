# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
系统升级模块序列化器

当前模型使用 CharField 存储日期时间、IntegerField 存储关联ID。
迁移 0004 执行后需同步更新。
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
            'upgrade_no': record.upgrade_no,
            'system': record.system,
            'upgrade_type': record.upgrade_type,
            'version': record.version,
            'upgrade_time': upgrade_time,
            'status': record.status,
            'owner': record.owner,
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


class UpgradeChecklistSerializer:
    """升级步骤清单序列化器"""

    @staticmethod
    def to_list_view(checklist, step_count=0):
        """清单列表序列化"""
        return {
            'id': checklist.id,
            'name': checklist.name,
            'description': checklist.description,
            'is_default': checklist.is_default,
            'step_count': step_count,
            'created_at': checklist.created_at or '',
            'updated_at': checklist.updated_at or '',
        }

    @staticmethod
    def to_detail_view(checklist, steps=None):
        """清单详情序列化（含步骤）"""
        data = UpgradeChecklistSerializer.to_list_view(checklist, len(steps or []))
        data['steps'] = [
            UpgradeChecklistStepSerializer.to_view(s) for s in (steps or [])
        ]
        return data


class UpgradeChecklistStepSerializer:
    """清单步骤序列化器"""

    @staticmethod
    def to_view(step):
        """步骤序列化"""
        return {
            'id': step.id,
            'checklist_id': step.checklist_id,
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
