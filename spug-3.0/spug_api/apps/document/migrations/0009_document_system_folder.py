# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""Add DocumentSystemFolder for protected document business roots."""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('document', '0008_transfer_cleanup_index'),
    ]

    operations = [
        migrations.CreateModel(
            name='DocumentSystemFolder',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(db_index=True, help_text='系统目录编码，党建文档固定为 party_building_documents', max_length=64, unique=True, verbose_name='系统目录编码')),
                ('name', models.CharField(max_length=100, verbose_name='显示名称')),
                ('is_public', models.BooleanField(default=True, verbose_name='是否公共空间')),
                ('protected', models.BooleanField(default=True, verbose_name='是否保护根目录')),
                ('description', models.CharField(blank=True, default='', max_length=255, verbose_name='说明')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('folder', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='system_bindings',
                    to='document.documentfolderpublic',
                    help_text='绑定的 DocumentFolderPublic 根目录',
                    verbose_name='绑定的公共目录',
                )),
            ],
            options={
                'db_table': 'tdyw_document_system_folder',
                'verbose_name': '文档系统目录绑定',
                'verbose_name_plural': '文档系统目录绑定',
            },
        ),
    ]
