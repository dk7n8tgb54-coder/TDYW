# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——旧设计器路线遗留字段类型（仅存 LongTextField）。

在线设计器路线（/el/ledger-designer + layout-templates API + layout_services）
已于 2026-09-29 整体下线；两个休眠模型（OperationLedgerLayoutTemplate/
OperationLedgerLayoutVersion，历史表 tdyw_el_ledger_layout_template/
tdyw_el_ledger_layout_version）已于 2026-10-14 随迁移 0017 的 DeleteModel
退役（模型类删除、历史表随 migrate 删除）。本模块仅保留 LongTextField
定义，原因：

- 历史迁移 0001_initial.py 序列化引用
  ``apps.equipment_lifecycle.layout_models.LongTextField``，按「不修改
  已执行迁移」原则该可导入路径不可删除，全新数据库从头重放迁移必须可解析；
- Excel 路线使用 excel_field_types.LongTextField（同名独立定义），与本类互不影响。
"""
from django.db import models


class LongTextField(models.TextField):
    """LONGTEXT 文本域：仅供历史迁移 0001 序列化引用解析（Excel 用 excel_field_types.LongTextField）。"""

    def db_type(self, connection):
        if connection.vendor == 'mysql':
            return 'longtext'
        return super().db_type(connection)
