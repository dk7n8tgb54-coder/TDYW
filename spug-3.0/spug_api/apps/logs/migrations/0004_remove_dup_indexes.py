# Remove duplicate single-column indexes that already exist via field-level db_index=True.
# request_hash / log_hash / request_id fields keep db_index=True (auto index),
# only the manually-named duplicates added in 0003 are removed to avoid write/disk overhead.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('logs', '0003_audit_hash_fields'),
    ]

    operations = [
        # 这三条索引与字段 db_index=True 自动生成的索引重复：
        #   audit_req_hash_idx  <-> audit_logs_request_hash_<hash>
        #   audit_log_hash_idx  <-> audit_logs_log_hash_<hash>
        #   audit_req_id_idx    <-> audit_logs_request_id_<hash>
        # 删除手写命名版本，保留字段级 db_index 自动索引，查询能力不变。
        migrations.RemoveIndex(
            model_name='auditlog',
            name='audit_req_hash_idx',
        ),
        migrations.RemoveIndex(
            model_name='auditlog',
            name='audit_log_hash_idx',
        ),
        migrations.RemoveIndex(
            model_name='auditlog',
            name='audit_req_id_idx',
        ),
    ]
