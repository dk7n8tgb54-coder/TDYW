# Generated for evidence-closure stage 2: unified evidence base

from django.db import migrations, models

import libs.tenant_base_model
import libs.utils
from libs.tenant_base_model import make_tenant_id


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='EvidenceEvent',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_id', make_tenant_id()),
                ('module', models.CharField(help_text='业务模块：runlog/checksheet/radio_license/device/interference', max_length=50)),
                ('object_type', models.CharField(help_text='对象类型（业务自定义，如 runlog/checksheet_submission）', max_length=50)),
                ('object_id', models.CharField(help_text='对象 ID', max_length=50)),
                ('event_type', models.CharField(choices=[('submit', '提交'), ('approve', '审批通过'), ('reject', '驳回'), ('close', '关闭/归档'), ('correct', '更正'), ('delete', '删除'), ('export', '导出'), ('void', '作废'), ('other', '其他')], help_text='事件类型', max_length=20)),
                ('event_title', models.CharField(default='', help_text='事件标题/描述', max_length=200)),
                ('actor_user_id', models.IntegerField(blank=True, help_text='操作人账号 ID', null=True)),
                ('actor_username', models.CharField(default='', help_text='登录账号快照', max_length=100)),
                ('actor_name', models.CharField(default='', help_text='姓名快照', max_length=100)),
                ('actor_department', models.CharField(default='', help_text='部门快照', max_length=100)),
                ('actor_ip', models.CharField(default='', help_text='操作 IP', max_length=50)),
                ('actor_device', models.CharField(blank=True, default='', help_text='设备信息，可为空', max_length=255, null=True)),
                ('object_snapshot', models.TextField(blank=True, help_text='业务对象快照 JSON', null=True)),
                ('before_snapshot', models.TextField(blank=True, help_text='修改前快照 JSON，可为空', null=True)),
                ('after_snapshot', models.TextField(blank=True, help_text='修改后快照 JSON，可为空', null=True)),
                ('attachment_hashes', models.TextField(blank=True, help_text='附件哈希清单 JSON', null=True)),
                ('remark', models.CharField(default='', help_text='说明', max_length=500)),
                ('prev_hash', models.CharField(default='', help_text='同一业务对象链上一条 event_hash；链首为空串', max_length=64)),
                ('event_hash', models.CharField(db_index=True, default='', help_text='本条证据事件哈希(SHA256)', max_length=64)),
                ('audit_log_id', models.IntegerField(blank=True, help_text='对应全局审计日志 ID，可为空', null=True)),
                ('external_ts_provider', models.CharField(default='', help_text='外部时间戳服务商标识，内网环境留空', max_length=50)),
                ('external_ts_token', models.CharField(default='', help_text='外部时间戳凭证，内网环境留空', max_length=255)),
                ('created_at', models.CharField(default=libs.utils.human_datetime, help_text='服务器时间', max_length=20)),
            ],
            options={
                'db_table': 'tdyw_evidence_events',
                'verbose_name': '证据事件',
                'verbose_name_plural': '证据事件',
                'ordering': ('-created_at', '-id'),
            },
            bases=(models.Model, libs.tenant_base_model.TenantModelMixin),
        ),
        migrations.CreateModel(
            name='EvidenceAttachment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_id', make_tenant_id()),
                ('module', models.CharField(help_text='业务模块', max_length=50)),
                ('object_type', models.CharField(help_text='对象类型', max_length=50)),
                ('object_id', models.CharField(help_text='对象 ID', max_length=50)),
                ('file_name', models.CharField(help_text='原始文件名（用户上传时的名字）', max_length=255)),
                ('file_path', models.CharField(help_text='磁盘存储路径（含重命名后的文件名）', max_length=500)),
                ('file_size', models.BigIntegerField(default=0, help_text='文件大小(字节)')),
                ('file_ext', models.CharField(default='', help_text='文件扩展名', max_length=20)),
                ('file_hash_sha256', models.CharField(db_index=True, default='', help_text='文件 SHA256', max_length=64)),
                ('file_hash_md5', models.CharField(default='', help_text='文件 MD5（兼容旧系统）', max_length=32)),
                ('uploaded_by_id', models.IntegerField(blank=True, help_text='上传人账号 ID', null=True)),
                ('uploaded_by_name', models.CharField(default='', help_text='上传人姓名快照', max_length=100)),
                ('is_deleted', models.BooleanField(default=False, help_text='是否已删除（软删除）')),
                ('deleted_by_id', models.IntegerField(blank=True, help_text='删除人账号 ID', null=True)),
                ('deleted_by_name', models.CharField(default='', help_text='删除人姓名快照', max_length=100)),
                ('deleted_at', models.CharField(blank=True, help_text='删除时间', max_length=20, null=True)),
                ('delete_reason', models.CharField(default='', help_text='删除原因', max_length=500)),
                ('uploaded_at', models.CharField(default=libs.utils.human_datetime, help_text='上传时间', max_length=20)),
            ],
            options={
                'db_table': 'tdyw_evidence_attachments',
                'verbose_name': '附件证据',
                'verbose_name_plural': '附件证据',
                'ordering': ('-uploaded_at', '-id'),
            },
            bases=(models.Model, libs.tenant_base_model.TenantModelMixin),
        ),
        migrations.AddIndex(
            model_name='evidenceevent',
            index=models.Index(fields=['tenant_id', 'module', 'object_type', 'object_id', '-id'], name='ev_obj_chain_idx'),
        ),
        migrations.AddIndex(
            model_name='evidenceevent',
            index=models.Index(fields=['tenant_id', 'actor_user_id'], name='ev_obj_actor_idx'),
        ),
        migrations.AddIndex(
            model_name='evidenceevent',
            index=models.Index(fields=['tenant_id', 'event_type'], name='ev_obj_type_idx'),
        ),
        migrations.AddIndex(
            model_name='evidenceevent',
            index=models.Index(fields=['event_hash'], name='ev_event_hash_idx'),
        ),
        migrations.AddIndex(
            model_name='evidenceattachment',
            index=models.Index(fields=['tenant_id', 'module', 'object_type', 'object_id'], name='ev_att_obj_idx'),
        ),
        migrations.AddIndex(
            model_name='evidenceattachment',
            index=models.Index(fields=['file_hash_sha256'], name='ev_att_sha256_idx'),
        ),
        migrations.AddIndex(
            model_name='evidenceattachment',
            index=models.Index(fields=['tenant_id', 'is_deleted'], name='ev_att_del_idx'),
        ),
    ]
