# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
批量操作 Celery 任务

【兼容性说明】
此文件保留为兼容层，实际实现已迁移到 batch/ 模块。
请使用新导入路径：from apps.document.tasks.batch import batch_delete_transfers
"""
# 从新的模块结构导出，保持向后兼容
from .batch.tasks import batch_delete_transfers, batch_cancel_transfers

__all__ = ['batch_delete_transfers', 'batch_cancel_transfers']
