# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
为 Role 增加 perms_version 字段，用于权限缓存的新鲜度校验。

背景：User.page_perms 原先用 `if data:` 短路 + 空集合作失效信号，要求所有
修改 Role.page_perms 的路径都主动调用 clear_perms_cache。但存在多条漏失效
路径（document/migrations/0011 直接 role.save(update_fields=['page_perms'])
不清缓存、运维 SQL 直接 UPDATE、RoleView.patch 先清缓存后 save 的竞态等），
导致残缺权限集合被 if data: 当作权威滞留最多 TTL(300s)，表现为普通账号
"本来好好的突然权限拒绝"，TTL 过期后自愈。

修复：Role 增加 perms_version，save() 检测 page_perms 变化时自增；
User.page_perms 缓存值改为 (version, perms) tuple，读取时比对 max(角色
perms_version)，不一致即重算。从而根治任何漏失效路径。

本迁移将历史角色 perms_version 初始化为 1（0 保留给尚未 save 的新实例）。
用户侧旧格式缓存（set 实例）会在下次读取时被 isinstance 判定失效并重算，
无需在迁移中操作 Redis。
"""
from django.db import migrations, models


def init_perms_version(apps, schema_editor):
    Role = apps.get_model('account', 'Role')
    Role.objects.all().update(perms_version=1)


def reverse_init(apps, schema_editor):
    Role = apps.get_model('account', 'Role')
    Role.objects.all().update(perms_version=0)


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0006_role_tenant_system'),
    ]

    operations = [
        migrations.AddField(
            model_name='role',
            name='perms_version',
            field=models.PositiveIntegerField(db_index=True, default=0),
        ),
        migrations.RunPython(init_perms_version, reverse_init),
    ]
