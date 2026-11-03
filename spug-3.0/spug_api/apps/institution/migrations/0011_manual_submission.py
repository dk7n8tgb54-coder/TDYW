# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""提交待发布核对固定快照（2026-11-03）：新增 tdyw_institution_submission

背景：2026-11-02 的发布交接只记录提交时草稿修订号，没有独立文件副本，
草稿再保存即失效；本次升级为「提交时复制当前草稿到 submissions/ 独立
存储 + 冻结内容写路径」，发布人预览/下载/最终发布均读取同一快照。
- 只新增 ManualSubmission 表（状态机 pending/withdrawn/returned/published，
  含提交人/时间/哈希/修订号、撤回/退回信息、发布消费信息、快照清理时间），
  **不修改** ManualFile 的旧 submission_revision/submitted_at/submitted_by
  列，不迁移数据、不生成任何快照：存量旧提交记录保持原样，只是不再被
  新流程视为有效提交（界面提示按新规则重新提交），可追溯信息保留。
- 快照物理文件位于 institution 存储根的新 submissions/ 子目录，由业务
  流程在撤回/退回/发布消费后清理（记录保留）；迁移本身不做物理文件
  删除，回滚只删除新表/快照行，旧列与旧流程数据不变。
- 回滚：DeleteModel（新快照记录删除，物理文件由部署侧按存储生命周期
  清理）；旧流程字段未动，回滚后可恢复旧行为。
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('institution', '0010_remove_manual_original'),
    ]

    operations = [
        migrations.CreateModel(
            name='ManualSubmission',
            fields=[
                ('id', models.AutoField(
                    auto_created=True, primary_key=True, serialize=False,
                    verbose_name='ID')),
                ('tenant_id', models.CharField(
                    default='', help_text='租户标识', max_length=50)),
                ('draft_revision', models.PositiveIntegerField(
                    verbose_name='提交时修订序号')),
                ('file_path', models.CharField(
                    max_length=500, verbose_name='快照相对存储路径')),
                ('original_name', models.CharField(
                    blank=True, default='', max_length=255,
                    verbose_name='快照显示文件名')),
                ('file_size', models.BigIntegerField(
                    default=0, verbose_name='快照大小')),
                ('file_hash', models.CharField(
                    blank=True, default='', max_length=64,
                    verbose_name='快照SHA256')),
                ('status', models.CharField(
                    choices=[('pending', '待发布人核对'),
                             ('withdrawn', '已撤回'),
                             ('returned', '已退回修改'),
                             ('published', '已随版本发布')],
                    default='pending', max_length=20, verbose_name='提交状态')),
                ('submitted_by_name', models.CharField(
                    blank=True, default='', max_length=100,
                    verbose_name='提交人账号名')),
                ('submitted_at', models.DateTimeField(verbose_name='提交时间')),
                ('withdrawn_at', models.DateTimeField(
                    blank=True, null=True, verbose_name='撤回时间')),
                ('withdrawn_by_name', models.CharField(
                    blank=True, default='', max_length=100,
                    verbose_name='撤回人账号名')),
                ('returned_at', models.DateTimeField(
                    blank=True, null=True, verbose_name='退回时间')),
                ('returned_by_name', models.CharField(
                    blank=True, default='', max_length=100,
                    verbose_name='退回人账号名')),
                ('return_reason', models.CharField(
                    blank=True, default='', max_length=500,
                    verbose_name='退回原因')),
                ('consumed_at', models.DateTimeField(
                    blank=True, null=True, verbose_name='随发布消费时间')),
                ('cleaned_at', models.DateTimeField(
                    blank=True, null=True,
                    verbose_name='快照物理文件清理时间')),
                ('created_at', models.DateTimeField(
                    auto_now_add=True, verbose_name='创建时间')),
                ('file', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='submissions',
                    to='institution.manualfile',
                    verbose_name='所属制度文件')),
                ('manual', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='submissions', to='institution.manual',
                    verbose_name='所属手册')),
                ('published_version', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+', to='institution.manualversion',
                    verbose_name='随发布版本')),
                ('returned_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+', to='account.user',
                    verbose_name='退回人账号')),
                ('submitted_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+', to='account.user',
                    verbose_name='提交人账号')),
                ('withdrawn_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+', to='account.user',
                    verbose_name='撤回人账号')),
            ],
            options={
                'verbose_name': '提交待发布核对快照',
                'verbose_name_plural': '提交待发布核对快照',
                'db_table': 'tdyw_institution_submission',
                'ordering': ['-id'],
                'indexes': [
                    models.Index(
                        fields=['file', 'status'], name='inst_sub_file_idx'),
                    models.Index(
                        fields=['manual', 'status'], name='inst_sub_manual_idx'),
                ],
            },
        ),
    ]
