# Generated for evidence-closure stage 1: audit log hash chain fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('logs', '0002_add_audit_indexes'),
    ]

    operations = [
        # 新增哈希链相关字段，全部可空/默认，兼容已有数据
        migrations.AddField(
            model_name='auditlog',
            name='request_hash',
            field=models.CharField(
                db_index=True, default='', max_length=64,
                help_text='请求详情哈希(SHA256)，基于存库 detail 计算'),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='response_hash',
            field=models.CharField(
                default='', max_length=64,
                help_text='响应体哈希(SHA256)，无响应内容时留空'),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='prev_hash',
            field=models.CharField(
                default='', max_length=64,
                help_text='同租户上一条日志 log_hash，构成哈希链；链首为空串'),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='log_hash',
            field=models.CharField(
                db_index=True, default='', max_length=64,
                help_text='日志哈希(SHA256)，覆盖全部关键字段+prev_hash；旧数据为空'),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='request_id',
            field=models.CharField(
                blank=True, db_index=True, max_length=64, null=True,
                help_text='请求唯一标识(uuid4)，关联同请求多条记录'),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='user_agent',
            field=models.CharField(
                blank=True, max_length=500, null=True,
                help_text='客户端 User-Agent'),
        ),
        # 新增哈希链校验索引
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['request_hash'], name='audit_req_hash_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['log_hash'], name='audit_log_hash_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['request_id'], name='audit_req_id_idx'),
        ),
    ]
