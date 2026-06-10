# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
添加 MERGING 到 DocumentTransfer.TRANSFER_STATUS_CHOICES

数据库中已存在 status='MERGING' 的记录（由 tasks/merge.py 等写入），
但模型 choices 中未声明该选项。本次迁移补齐声明以保持一致性。

注意：此迁移不修改数据库 schema，仅更新模型元数据。
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('document', '0002_add_thumbnail_path'),
    ]

    operations = [
        migrations.AlterField(
            model_name='documenttransfer',
            name='status',
            field=models.CharField(
                choices=[
                    ('PENDING', '等待中'),
                    ('UPLOADING', '上传中'),
                    ('DOWNLOADING', '下载中'),
                    ('PAUSED', '已暂停'),
                    ('MERGING', '合并中'),
                    ('COMPLETED', '已完成'),
                    ('FAILED', '失败'),
                    ('CANCELED', '已取消'),
                ],
                db_index=True,
                default='PENDING',
                max_length=20,
                verbose_name='状态',
            ),
        ),
    ]
