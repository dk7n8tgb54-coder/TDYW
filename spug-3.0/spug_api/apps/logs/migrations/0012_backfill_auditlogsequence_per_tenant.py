# -*- coding: utf-8 -*-
"""为存量租户补建 AuditLogSequence 行。

背景：序列行此前按业务首写惰性创建，并发首写存在唯一键竞态死锁窗口
（MariaDB 1213，且 save_audit_log 会吞掉该异常导致业务事务被毒化、
数据无声丢失）。改为租户创建时预建（post_save 信号）后，
本迁移为存量租户补建缺失的序列行，使业务并发只走串行化路径。
"""
from django.db import migrations


def backfill(apps, schema_editor):
    Tenant = apps.get_model('account', 'Tenant')
    AuditLog = apps.get_model('logs', 'AuditLog')
    AuditLogSequence = apps.get_model('logs', 'AuditLogSequence')
    for tenant in Tenant.objects.all().iterator():
        tenant_id = tenant.pk
        if not tenant_id or AuditLogSequence.objects.filter(tenant_id=tenant_id).exists():
            continue
        tail = (AuditLog.objects.filter(tenant_id=tenant_id)
                .order_by('-id').first())
        AuditLogSequence.objects.create(
            tenant_id=tenant_id,
            last_log_id=tail.id if tail else 0,
            last_log_hash=tail.log_hash if tail else '',
        )


def reverse_noop(apps, schema_editor):
    # 不反向删除：序列行删除会重开并发首写死锁窗口
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('logs', '0011_auditlogsequence'),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_noop),
    ]
