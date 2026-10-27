# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——Excel 上传版维护台账公共字段类型。

LongTextField 最早定义于 layout_models.py（在线设计器路线，2026-09-28）；
在线设计器路线已于 2026-09-29 下线，本模块成为 Excel 路线的字段定义处：
模板布局 meta、字段绑定与填写值 JSON 均可能超过 MariaDB TEXT 的 64KB
上限，必须落 LONGTEXT。layout_models 随 2026-10-24 迁移基线重建
（0001 由当前模型重新生成，不再序列化引用该模块）整体删除。
"""
from django.db import models


class LongTextField(models.TextField):
    """LONGTEXT 文本域：布局/绑定/填写值 JSON 可超过 MariaDB TEXT 的 64KB 上限。"""

    def db_type(self, connection):
        if connection.vendor == 'mysql':
            return 'longtext'
        return super().db_type(connection)
