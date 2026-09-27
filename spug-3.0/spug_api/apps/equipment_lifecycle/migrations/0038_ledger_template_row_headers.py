# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""台账模板可视化设计（第一阶段）：行层级表头名称。

- OperationLedgerTemplate 新增 row_headers：行层级表头名称 JSON 字符串数组
  （如 ["信道","电台"]），按层级顺序派生第 1/2/…级行层级列的列头名称，
  空串表示未配置（展示端回退默认"第N级"）；
- OperationLedger 新增 row_headers_snapshot：矩阵台账创建时取模板
  row_headers 原样快照，模板后续修改层级表头不影响已生成台账的详情与导出；
- 两列均可空默认（历史模板/历史台账无值，行为不变），无数据回填；
- 回滚路径：反向删除两列，历史数据（未提交前）随列删除，无独立回滚数据。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0037_remove_device_tables'),
    ]

    operations = [
        migrations.AddField(
            model_name='operationledgertemplate',
            name='row_headers',
            field=models.TextField(blank=True, default='', help_text='行层级表头名称 JSON 字符串数组（如 ["信道","电台"]，空为默认"第N级"）'),
        ),
        migrations.AddField(
            model_name='operationledger',
            name='row_headers_snapshot',
            field=models.TextField(blank=True, default='', help_text='行层级表头名称快照 JSON 字符串数组（生成时模板的层级表头）'),
        ),
    ]
