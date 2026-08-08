"""租户工厂 - 创建测试租户 A/B"""
import uuid

_uid = lambda: uuid.uuid4().hex[:12]


def make_tenant(tenant_id, name, created_by_user):
    """创建租户

    Args:
        tenant_id: 租户 ID (字符串)
        name: 租户名称
        created_by_user: 创建者 User 实例 (Tenant.created_by 是 FK)

    Returns:
        Tenant 实例
    """
    from apps.account.models import Tenant
    tenant = Tenant.objects.create(
        id=tenant_id,
        name=name,
        created_by=created_by_user,
    )
    return tenant


def make_tenant_pair(bootstrap_user):
    """创建一对测试租户 A/B

    Args:
        bootstrap_user: 用于 created_by 的已有用户

    Returns:
        dict: {'tid_a': str, 'tid_b': str, 'tenant_a': Tenant, 'tenant_b': Tenant}
    """
    tid_a = f'ti_a_{_uid()}'
    tid_b = f'ti_b_{_uid()}'
    return {
        'tid_a': tid_a,
        'tid_b': tid_b,
        'tenant_a': make_tenant(tid_a, f'测试租户A-{_uid()}', bootstrap_user),
        'tenant_b': make_tenant(tid_b, f'测试租户B-{_uid()}', bootstrap_user),
    }


def cleanup_tenants(tid_a, tid_b):
    """清理测试租户"""
    from apps.account.models import Tenant
    Tenant.objects.filter(id__in=[tid_a, tid_b]).delete()
