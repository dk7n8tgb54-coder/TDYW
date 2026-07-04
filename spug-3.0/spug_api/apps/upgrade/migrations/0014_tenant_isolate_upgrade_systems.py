# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""将升级系统候选项字典从全局共享（tenant_id=''）迁移为按租户隔离。

迁移策略（复制 + 保留）：
1. 收集所有非空租户 ID（来源：User.tenant_id + UpgradeRecord.tenant_id）
2. 将 tenant_id='' 的 active 系统候选项复制到每个非空租户
   - 同租户内已存在同名（精确匹配）则跳过，尊重 unique_together
3. 保留 tenant_id='' 的原始记录不删除、不停用
   - 这些记录属于默认/管理员租户（tenant_id=''），该租户用户继续使用
   - 非空租户通过视图层 tenant_id 过滤，不会看到 tenant_id='' 的记录

迁移后效果：
- 每个非空租户拥有独立的系统候选项副本，可自行新增/停用/删除
- 不同租户互不可见
- 历史升级记录的 system 字段不受影响
"""
from django.db import migrations


def forward_copy_to_tenants(apps, schema_editor):
    """将全局系统候选项复制到各非空租户"""
    UpgradeSystem = apps.get_model('upgrade', 'UpgradeSystem')
    UpgradeRecord = apps.get_model('upgrade', 'UpgradeRecord')
    User = apps.get_model('account', 'User')
    db_alias = schema_editor.connection.alias

    # 1. 收集非空租户 ID（从 User 和 UpgradeRecord 两处获取，取并集）
    tenant_ids = set()
    try:
        for tid in User.objects.using(db_alias) \
                .exclude(tenant_id='').exclude(tenant_id__isnull=True) \
                .values_list('tenant_id', flat=True).distinct():
            if tid:
                tenant_ids.add(tid)
    except Exception:
        pass
    try:
        for tid in UpgradeRecord.objects.using(db_alias) \
                .exclude(tenant_id='').exclude(tenant_id__isnull=True) \
                .values_list('tenant_id', flat=True).distinct():
            if tid:
                tenant_ids.add(tid)
    except Exception:
        pass

    if not tenant_ids:
        return

    # 2. 获取全局 active 系统候选项（tenant_id=''）
    globals_qs = list(
        UpgradeSystem.objects.using(db_alias).filter(tenant_id='', is_active=True)
    )
    if not globals_qs:
        return

    # 3. 复制到每个非空租户（同租户已存在同名则跳过）
    #    created_by 不复制：副本是迁移生成的，避免 PROTECT 约束问题
    for tid in tenant_ids:
        for g in globals_qs:
            try:
                UpgradeSystem.objects.using(db_alias).get_or_create(
                    tenant_id=tid,
                    name=g.name,
                    defaults={
                        'is_active': True,
                        'sort_order': g.sort_order,
                        'created_at': g.created_at,
                    },
                )
            except Exception:
                # 跳过约束冲突（如大小写变体在 case-insensitive collation 下的碰撞）
                continue


def reverse_remove_tenant_copies(apps, schema_editor):
    """回滚：删除所有非空租户的系统候选项副本（保留全局 tenant_id='' 记录）

    注意：此回滚会删除用户在迁移后手动新增的非空租户候选项，
    仅用于紧急回滚场景。
    """
    UpgradeSystem = apps.get_model('upgrade', 'UpgradeSystem')
    db_alias = schema_editor.connection.alias
    UpgradeSystem.objects.using(db_alias).exclude(tenant_id='').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('upgrade', '0013_upgradeplanstep_upg_plan_tenant_seq_idx_and_more'),
    ]

    operations = [
        migrations.RunPython(forward_copy_to_tenants, reverse_remove_tenant_copies),
    ]
