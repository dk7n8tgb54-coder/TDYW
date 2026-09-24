from django.apps import AppConfig
from django.db.models.signals import post_save


class LogsConfig(AppConfig):
    name = 'apps.logs'
    verbose_name = '审计日志'

    def ready(self):
        # 租户创建时预建审计序列行：消除并发业务首写的唯一键竞态死锁
        from apps.logs.audit import init_audit_sequence_for_tenant

        def _on_tenant_saved(sender, instance, **kwargs):
            init_audit_sequence_for_tenant(instance.pk)

        from apps.account.models import Tenant
        post_save.connect(
            _on_tenant_saved, sender=Tenant,
            weak=False, dispatch_uid='logs_init_audit_sequence_on_tenant')
