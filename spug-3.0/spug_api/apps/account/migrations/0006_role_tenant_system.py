# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
为 Role 模型增加 tenant_id 和 is_system 字段，并按保守策略回填历史数据。

历史数据迁移策略（保守，避免把高权限角色错误开放给普通管理员）：
1. created_by.is_supper=True 的角色：tenant_id=null, is_system=True（平台级系统角色）
2. created_by.is_supper=False 的角色：tenant_id=created_by.tenant_id, is_system=False
3. is_global_admin=True 的角色：强制 tenant_id=null, is_system=True
4. 没有 created_by 或历史脏数据：默认 tenant_id=null, is_system=True（保守）
"""
from django.db import migrations, models


def backfill_role_tenant_system(apps, schema_editor):
    """按保守策略回填 Role.tenant_id 和 Role.is_system"""
    Role = apps.get_model('account', 'Role')
    User = apps.get_model('account', 'User')

    for role in Role.objects.all():
        # 规则3：全局管理员角色强制作为平台级系统角色
        if role.is_global_admin:
            role.tenant_id = ''
            role.is_system = True
            role.save(update_fields=['tenant_id', 'is_system'])
            continue

        created_by_id = getattr(role, 'created_by_id', None)
        creator = User.objects.filter(pk=created_by_id).first() if created_by_id else None

        if creator is None:
            # 规则4：没有 created_by 或历史脏数据，保守按平台级系统角色处理
            role.tenant_id = ''
            role.is_system = True
        elif creator.is_supper:
            # 规则1：超管创建的角色设为平台级系统角色
            role.tenant_id = ''
            role.is_system = True
        else:
            # 规则2：普通用户创建的角色归属其 tenant_id
            role.tenant_id = creator.tenant_id
            role.is_system = False

        role.save(update_fields=['tenant_id', 'is_system'])


def reverse_backfill(apps, schema_editor):
    """反向迁移：将 tenant_id 和 is_system 恢复为字段默认值"""
    Role = apps.get_model('account', 'Role')
    Role.objects.all().update(tenant_id='', is_system=False)


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0005_populate_tenants'),
    ]

    operations = [
        migrations.AddField(
            model_name='role',
            name='tenant_id',
            field=models.CharField(blank=True, db_index=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='role',
            name='is_system',
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.RunPython(backfill_role_tenant_system, reverse_backfill),
    ]
