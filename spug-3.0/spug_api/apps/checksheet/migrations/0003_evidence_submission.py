# Generated for evidence-closure stage 3: checksheet identity + submission

from django.db import migrations, models

from libs.tenant_base_model import make_tenant_id
import libs.tenant_base_model
import libs.utils


class Migration(migrations.Migration):

    dependencies = [
        ('checksheet', '0002_auto_20260625_2355'),
    ]

    operations = [
        # ---- 新增 CheckSheetSubmission 提交批次表 ----
        migrations.CreateModel(
            name='CheckSheetSubmission',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_id', make_tenant_id()),
                ('project', models.CharField(max_length=100, verbose_name='项目名称')),
                ('year', models.CharField(max_length=4, verbose_name='年份')),
                ('month', models.CharField(max_length=2, verbose_name='月份')),
                ('status', models.CharField(choices=[('draft', '草稿'), ('submitted', '已提交'), ('reviewed', '已复核'), ('closed', '已归档'), ('voided', '已作废')], default='draft', max_length=20, verbose_name='状态')),
                ('submitted_by_id', models.IntegerField(blank=True, null=True, verbose_name='提交人ID')),
                ('submitted_by_name', models.CharField(default='', max_length=100, verbose_name='提交人姓名快照')),
                ('submitted_at', models.CharField(blank=True, max_length=20, null=True, verbose_name='提交时间')),
                ('reviewed_by_id', models.IntegerField(blank=True, null=True, verbose_name='复核人ID')),
                ('reviewed_by_name', models.CharField(default='', max_length=100, verbose_name='复核人姓名快照')),
                ('reviewed_at', models.CharField(blank=True, max_length=20, null=True, verbose_name='复核时间')),
                ('review_comment', models.TextField(blank=True, null=True, verbose_name='复核意见')),
                ('voided_by_id', models.IntegerField(blank=True, null=True, verbose_name='作废人ID')),
                ('voided_by_name', models.CharField(default='', max_length=100, verbose_name='作废人姓名快照')),
                ('voided_at', models.CharField(blank=True, max_length=20, null=True, verbose_name='作废时间')),
                ('void_reason', models.CharField(default='', max_length=500, verbose_name='作废原因')),
                ('snapshot_hash', models.CharField(default='', max_length=64, verbose_name='提交快照哈希')),
                ('created_at', models.CharField(default=libs.utils.human_datetime, max_length=20, verbose_name='创建时间')),
                ('updated_at', models.CharField(blank=True, max_length=20, null=True, verbose_name='更新时间')),
            ],
            options={
                'db_table': 'tdyw_checksheet_submission',
                'verbose_name': '检查单提交批次',
                'verbose_name_plural': '检查单提交批次',
                'ordering': ['-created_at', '-id'],
            },
            bases=(models.Model, libs.tenant_base_model.TenantModelMixin),
        ),
        migrations.AddIndex(
            model_name='checksheetsubmission',
            index=models.Index(fields=['tenant_id', 'project', 'year', 'month'], name='cs_sub_obj_idx'),
        ),
        migrations.AddIndex(
            model_name='checksheetsubmission',
            index=models.Index(fields=['tenant_id', 'status'], name='cs_sub_status_idx'),
        ),
        # ---- CheckSheetRecord 增加身份快照字段 ----
        migrations.AddField(
            model_name='checksheetrecord',
            name='operator_user_id',
            field=models.IntegerField(blank=True, null=True, verbose_name='操作人账号ID'),
        ),
        migrations.AddField(
            model_name='checksheetrecord',
            name='operator_name_snapshot',
            field=models.CharField(default='', max_length=100, verbose_name='操作人姓名快照'),
        ),
        migrations.AddField(
            model_name='checksheetrecord',
            name='operator_department_snapshot',
            field=models.CharField(default='', max_length=100, verbose_name='操作人部门快照'),
        ),
        migrations.AddField(
            model_name='checksheetrecord',
            name='submitted_at',
            field=models.CharField(blank=True, max_length=20, null=True, verbose_name='提交时间快照'),
        ),
        # ---- CheckSheetDailySummary 增加身份快照字段 ----
        migrations.AddField(
            model_name='checksheetdailysummary',
            name='operator_user_id',
            field=models.IntegerField(blank=True, null=True, verbose_name='值班人员账号ID'),
        ),
        migrations.AddField(
            model_name='checksheetdailysummary',
            name='operator_name_snapshot',
            field=models.CharField(default='', max_length=100, verbose_name='值班人员姓名快照'),
        ),
    ]
