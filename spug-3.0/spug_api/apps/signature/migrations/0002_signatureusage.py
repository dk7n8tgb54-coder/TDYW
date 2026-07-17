# Generated for signature stage 2: immutable SignatureUsage snapshot

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('signature', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SignatureUsage',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_id', models.CharField(db_index=True, default='', help_text='签署业务所属租户', max_length=50)),
                ('module', models.CharField(help_text='已批准接入的调用模块标识', max_length=50)),
                ('object_type', models.CharField(help_text='已批准模块中的业务对象类型', max_length=50)),
                ('object_id', models.CharField(help_text='业务对象 ID', max_length=50)),
                ('scene_code', models.CharField(help_text='签署位置，如 operator/reviewer/approver', max_length=50)),
                ('signer_user_id', models.BigIntegerField(help_text='签署账号 ID')),
                ('signer_username', models.CharField(default='', help_text='登录名快照', max_length=100)),
                ('signer_name', models.CharField(default='', help_text='显示姓名快照', max_length=100)),
                ('signature_attachment_id', models.BigIntegerField(help_text='签署时使用的 EvidenceAttachment.id')),
                ('signature_version', models.PositiveIntegerField(help_text='签署时账号签名版本号')),
                ('signature_sha256', models.CharField(default='', help_text='签名文件 SHA256 快照', max_length=64)),
                ('business_snapshot', models.TextField(blank=True, help_text='业务快照 JSON 字符串（最小必要摘要）', null=True)),
                ('business_snapshot_hash', models.CharField(default='', help_text='业务快照规范化 SHA256', max_length=64)),
                ('signed_at', models.CharField(help_text='服务器签署时间', max_length=20)),
                ('signer_ip', models.CharField(default='', help_text='请求来源 IP', max_length=50)),
                ('request_id', models.CharField(help_text='请求追踪 ID / 幂等键', max_length=64)),
                ('request_fingerprint', models.CharField(default='', help_text='请求指纹 SHA256，覆盖 tenant/signer/module/object/scene/snapshot_hash', max_length=64)),
                ('evidence_event_id', models.BigIntegerField(blank=True, help_text='对应 EvidenceEvent.id', null=True)),
            ],
            options={
                'db_table': 'tdyw_signature_usages',
                'verbose_name': '签名使用记录',
                'verbose_name_plural': '签名使用记录',
                'ordering': ('-id',),
            },
        ),
        migrations.AddIndex(
            model_name='signatureusage',
            index=models.Index(fields=['tenant_id', 'module', 'object_type', 'object_id'], name='sig_usage_obj_idx'),
        ),
        migrations.AddIndex(
            model_name='signatureusage',
            index=models.Index(fields=['tenant_id', 'signer_user_id', 'signed_at'], name='sig_usage_signer_idx'),
        ),
        migrations.AddIndex(
            model_name='signatureusage',
            index=models.Index(fields=['signature_attachment_id'], name='sig_usage_att_idx'),
        ),
        migrations.AddConstraint(
            model_name='signatureusage',
            constraint=models.UniqueConstraint(fields=('tenant_id', 'request_id'), name='sig_usage_tenant_request_uniq'),
        ),
    ]
