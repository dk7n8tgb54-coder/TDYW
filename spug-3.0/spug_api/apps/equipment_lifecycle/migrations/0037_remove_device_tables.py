# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备管理模块下线：删除旧设备档案与设备事件两张表。

- apps.device 应用已整体移除（INSTALLED_APPS/URL/业务代码不再存在），
  已执行过 device 0001-0010 的环境中 tdyw_device_resume、tdyw_device_event
  两张表通过本迁移的 RunSQL 删除；全新环境中表从未创建，IF EXISTS 直接跳过；
- 删除前两表在 dev 与生产环境均为空表（0 行业务数据），不做数据迁移或备份；
- 历史 AuditLog / EvidenceEvent 中 target_type/module 为 device 的行属历史
  留痕，保持原样（哈希链不重写）；
- 回滚路径：反向为 no-op，表结构不可通过本迁移恢复；数据级回滚依赖
  镜像回滚 + 备份恢复流程。
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0036_systemworkorder_maintenance_subtype'),
    ]

    # MariaDB 不支持事务性 DDL，DROP TABLE 会隐式提交，禁用整体事务。
    atomic = False

    operations = [
        migrations.RunSQL(
            sql=(
                'DROP TABLE IF EXISTS `tdyw_device_event`;',
                'DROP TABLE IF EXISTS `tdyw_device_resume`;',
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
