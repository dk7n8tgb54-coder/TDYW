# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——Excel 上传版维护台账公共字段类型。

LongTextField 最早定义于 layout_models.py（在线设计器路线，2026-09-28）；
在线设计器路线已于 2026-09-29 下线，本模块成为 Excel 路线的字段定义处：
模板布局 meta、字段绑定与填写值 JSON 均可能超过 MariaDB TEXT 的 64KB
上限，必须落 LONGTEXT。

注意：migrations/0039_ledger_layout_templates.py 以序列化引用
``apps.equipment_lifecycle.layout_models.LongTextField`` 记录设计器历史表，
按「不修改已执行迁移」原则保持原位，layout_models 内的同名定义不可删除；
本定义与之为同形独立类（0040 起的 Excel 迁移序列化引用指向本模块），
二者行为一致：MySQL 系（MariaDB/MySQL）落 longtext，其余沿用 TextField。
"""
from django.db import models


class LongTextField(models.TextField):
    """LONGTEXT 文本域：布局/绑定/填写值 JSON 可超过 MariaDB TEXT 的 64KB 上限。"""

    def db_type(self, connection):
        if connection.vendor == 'mysql':
            return 'longtext'
        return super().db_type(connection)
