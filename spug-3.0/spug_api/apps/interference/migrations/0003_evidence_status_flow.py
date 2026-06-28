# Generated for evidence-closure stage 3: interference status flow + identity snapshot

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('interference', '0002_auto_20260627_0807'),
    ]

    operations = [
        # ---- 新增状态字段 ----
        migrations.AddField(
            model_name='interference',
            name='status',
            field=models.CharField(
                choices=[
                    ('draft', '草稿'), ('submitted', '已提交'),
                    ('reviewed', '已复核'), ('reported', '已上报'),
                    ('handled', '已处置'), ('closed', '已关闭'),
                    ('voided', '已作废'),
                ],
                default='draft',
                help_text='状态：draft/submitted/reviewed/reported/handled/closed/voided',
                max_length=20,
            ),
        ),
        # ---- 提交人身份快照 ----
        migrations.AddField(
            model_name='interference',
            name='submitted_by_id',
            field=models.IntegerField(blank=True, help_text='提交人账号ID', null=True),
        ),
        migrations.AddField(
            model_name='interference',
            name='submitted_by_name',
            field=models.CharField(default='', help_text='提交人姓名快照', max_length=100),
        ),
        migrations.AddField(
            model_name='interference',
            name='submitted_at',
            field=models.CharField(blank=True, help_text='提交时间', max_length=20, null=True),
        ),
        # ---- 复核 ----
        migrations.AddField(
            model_name='interference',
            name='reviewed_by_id',
            field=models.IntegerField(blank=True, help_text='复核人账号ID', null=True),
        ),
        migrations.AddField(
            model_name='interference',
            name='reviewed_by_name',
            field=models.CharField(default='', help_text='复核人姓名快照', max_length=100),
        ),
        migrations.AddField(
            model_name='interference',
            name='reviewed_at',
            field=models.CharField(blank=True, help_text='复核时间', max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='interference',
            name='review_comment',
            field=models.TextField(blank=True, help_text='复核意见', null=True),
        ),
        # ---- 上报 ----
        migrations.AddField(
            model_name='interference',
            name='reported_at',
            field=models.CharField(blank=True, help_text='上报时间', max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='interference',
            name='reported_by_id',
            field=models.IntegerField(blank=True, help_text='上报人账号ID', null=True),
        ),
        migrations.AddField(
            model_name='interference',
            name='reported_by_name',
            field=models.CharField(default='', help_text='上报人姓名快照', max_length=100),
        ),
        migrations.AddField(
            model_name='interference',
            name='report_channel',
            field=models.CharField(blank=True, default='', help_text='上报渠道', max_length=100),
        ),
        migrations.AddField(
            model_name='interference',
            name='report_no',
            field=models.CharField(blank=True, default='', help_text='上报编号', max_length=100),
        ),
        # ---- 处置 ----
        migrations.AddField(
            model_name='interference',
            name='handled_by_id',
            field=models.IntegerField(blank=True, help_text='处置人账号ID', null=True),
        ),
        migrations.AddField(
            model_name='interference',
            name='handled_by_name',
            field=models.CharField(default='', help_text='处置人姓名快照', max_length=100),
        ),
        migrations.AddField(
            model_name='interference',
            name='handled_at',
            field=models.CharField(blank=True, help_text='处置时间', max_length=20, null=True),
        ),
        # ---- 关闭 ----
        migrations.AddField(
            model_name='interference',
            name='closed_by_id',
            field=models.IntegerField(blank=True, help_text='关闭人账号ID', null=True),
        ),
        migrations.AddField(
            model_name='interference',
            name='closed_by_name',
            field=models.CharField(default='', help_text='关闭人姓名快照', max_length=100),
        ),
        migrations.AddField(
            model_name='interference',
            name='closed_at',
            field=models.CharField(blank=True, help_text='关闭时间', max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='interference',
            name='close_summary',
            field=models.TextField(blank=True, help_text='关闭总结', null=True),
        ),
        # ---- 作废 ----
        migrations.AddField(
            model_name='interference',
            name='voided_by_id',
            field=models.IntegerField(blank=True, help_text='作废人账号ID', null=True),
        ),
        migrations.AddField(
            model_name='interference',
            name='voided_by_name',
            field=models.CharField(default='', help_text='作废人姓名快照', max_length=100),
        ),
        migrations.AddField(
            model_name='interference',
            name='voided_at',
            field=models.CharField(blank=True, help_text='作废时间', max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='interference',
            name='void_reason',
            field=models.CharField(blank=True, default='', help_text='作废原因', max_length=500),
        ),
        # ---- 快照哈希 ----
        migrations.AddField(
            model_name='interference',
            name='snapshot_hash',
            field=models.CharField(default='', help_text='提交快照哈希(SHA256)', max_length=64),
        ),
        # ---- 索引 ----
        migrations.AddIndex(
            model_name='interference',
            index=models.Index(fields=['tenant_id', 'status'], name='inter_status_idx'),
        ),
        migrations.AddIndex(
            model_name='interference',
            index=models.Index(fields=['tenant_id', '-datetime', '-id'], name='inter_time_idx'),
        ),
    ]
