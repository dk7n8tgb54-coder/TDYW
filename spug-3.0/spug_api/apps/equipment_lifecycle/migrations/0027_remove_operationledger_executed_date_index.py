# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""清理 OperationLedger 上 executed_date 遗留索引（2026-10-20 状态收口）。

2026-10-19 迁移 0024 删除 executed_date 列时未同步移除 0002 建立的
(tenant_id, executed_date) 索引（tdyw_el_ope_tenant__ac2ea0_idx）：MariaDB
随列删除把该索引收窄为单列 tenant_id 索引继续存在，而 models.py 的 Meta
indexes 已不再声明它，导致 makemigrations --check 持续要求生成 RemoveIndex。
本迁移按模型现状真实删除该遗留索引（与列删除后冗余的单列 tenant_id 索引；
同前缀的租户查询已有 (tenant_id, ledger_type, status) 等复合索引承接）。
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0026_retire_native_ledger_route'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='operationledger',
            name='tdyw_el_ope_tenant__ac2ea0_idx',
        ),
    ]
