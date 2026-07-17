# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

from django.db import migrations, models
import django.db.models.deletion
import libs.utils


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('account', '0006_role_tenant_system'),
    ]

    operations = [
        migrations.CreateModel(
            name='Regulation',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255, verbose_name='规章名称')),
                ('rule_no', models.CharField(db_index=True, max_length=100, verbose_name='规章编号')),
                ('issuing_authority', models.CharField(blank=True, db_index=True, default='', max_length=200, verbose_name='发文单位')),
                ('biz_type', models.CharField(blank=True, db_index=True, default='', max_length=50, verbose_name='业务类型')),
                ('publish_date', models.DateField(blank=True, null=True, verbose_name='发布日期')),
                ('effective_date', models.DateField(blank=True, db_index=True, null=True, verbose_name='生效日期')),
                ('status', models.CharField(choices=[('active', '现行'), ('retired', '已废止')], db_index=True, default='active', max_length=20, verbose_name='状态')),
                ('updated_at', models.CharField(blank=True, max_length=20, null=True, verbose_name='更新时间')),
            ],
            options={
                'verbose_name': '规章',
                'verbose_name_plural': '规章',
                'db_table': 'tdyw_regulation',
                'ordering': ['-effective_date', '-id'],
            },
        ),
        migrations.CreateModel(
            name='RegulationCategory',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, verbose_name='分类名称')),
                ('sort_order', models.IntegerField(default=0, verbose_name='排序')),
                ('code', models.CharField(blank=True, default='', max_length=50, verbose_name='分类编码')),
                ('is_leaf', models.BooleanField(default=True, verbose_name='是否叶子节点')),
                ('created_at', models.CharField(default=libs.utils.human_datetime, max_length=20, verbose_name='创建时间')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='account.user', verbose_name='创建人')),
                ('parent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='children', to='regulation.regulationcategory', verbose_name='父分类')),
            ],
            options={
                'verbose_name': '规章分类',
                'verbose_name_plural': '规章分类',
                'db_table': 'tdyw_regulation_category',
                'ordering': ['sort_order', 'id'],
            },
        ),
        migrations.CreateModel(
            name='RegulationAttachment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('original_name', models.CharField(max_length=255, verbose_name='原始文件名')),
                ('stored_name', models.CharField(max_length=255, verbose_name='存储文件名')),
                ('file_path', models.CharField(max_length=500, verbose_name='文件相对路径')),
                ('file_size', models.BigIntegerField(default=0, verbose_name='文件大小')),
                ('file_type', models.CharField(blank=True, default='', max_length=100, verbose_name='文件类型')),
                ('file_hash', models.CharField(blank=True, db_index=True, default='', max_length=64, verbose_name='文件哈希')),
                ('sort_order', models.IntegerField(default=0, verbose_name='排序')),
                ('uploaded_at', models.CharField(default=libs.utils.human_datetime, max_length=20, verbose_name='上传时间')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='是否删除')),
                ('deleted_at', models.CharField(blank=True, max_length=20, null=True, verbose_name='删除时间')),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='account.user', verbose_name='删除人')),
                ('regulation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='regulation.regulation', verbose_name='所属规章')),
                ('uploaded_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='account.user', verbose_name='上传人')),
            ],
            options={
                'verbose_name': '规章附件',
                'verbose_name_plural': '规章附件',
                'db_table': 'tdyw_regulation_attachment',
                'ordering': ['sort_order', '-id'],
            },
        ),
        migrations.AddField(
            model_name='regulation',
            name='category',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='regulations', to='regulation.regulationcategory', verbose_name='所属分类'),
        ),
        migrations.AddField(
            model_name='regulation',
            name='updated_by',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='account.user', verbose_name='更新人'),
        ),
        migrations.AddIndex(
            model_name='regulationcategory',
            index=models.Index(fields=['parent', 'sort_order'], name='reg_cat_parent_sort_idx'),
        ),
        migrations.AddIndex(
            model_name='regulationattachment',
            index=models.Index(fields=['regulation', 'is_deleted', 'sort_order'], name='reg_att_list_idx'),
        ),
        migrations.AddIndex(
            model_name='regulation',
            index=models.Index(fields=['rule_no'], name='reg_rule_no_idx'),
        ),
        migrations.AddIndex(
            model_name='regulation',
            index=models.Index(fields=['issuing_authority'], name='reg_issue_auth_idx'),
        ),
        migrations.AddIndex(
            model_name='regulation',
            index=models.Index(fields=['biz_type'], name='reg_biz_type_idx'),
        ),
        migrations.AddIndex(
            model_name='regulation',
            index=models.Index(fields=['status'], name='reg_status_idx'),
        ),
    ]
