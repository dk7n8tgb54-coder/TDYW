# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""授权模型改造（2026-10-31）：手册所有者 + 逐本账号授权，废弃 M2M 角色关联

结构变更：
- Manual.owner_type/owner_name -> org_type/org_name（归属类型/归属单位
  展示字段更名，语义不变）；CheckConstraint inst_manual_owner_type_valid
  先移除、更名后以新字段重建为 inst_manual_org_type_valid。
- Manual 新增 owner（所有者账号，账号删除 SET_NULL 不阻塞）。
- 新增 ManualAuthorization（逐本账号授权 can_view/can_edit/can_publish，
  (manual, account) 唯一；全 False 行由服务层落为删除不保留）。
- 移除 view_roles/edit_roles/publish_roles 三个 M2M（存量关联数据废弃）。

存量数据清理（RunPython，模块未上线、数据不可恢复）：
- ManualFile 全部负责人清空（owner_id=NULL, owner_name=''）并清除
  提交编制记录（submission_revision/submitted_at/submitted_by）——
  负责人独占编辑要求被指派账号持有 can_edit 授权，旧分工在新模型下
  无效，提交随旧模型废弃。
- ManualEditSession 全部失效并清空 current_doc_key（镜像 0003 先例：
  授权语义变更，新旧不复用；携带未落盘内容的在途编辑实例显式丢弃）。
- Manual.owner 保持 NULL、ManualAuthorization 空表：fail-closed——
  授权与所有者由管理员在新模型下重新指定，绝不从旧角色关联猜测迁移。

回滚路径：反向仅恢复结构（移除 owner/授权表、以空 M2M 恢复三个角色
字段、字段更名回来）；已清理的分工/提交/会话数据不可恢复（模块未
上线，可接受）。
"""
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q
from django.utils import timezone


def cleanup_legacy_authorization_data(apps, schema_editor):
    """清理随旧授权模型废弃的数据（见模块 docstring；单向，不可逆）"""
    ManualFile = apps.get_model('institution', 'ManualFile')
    ManualEditSession = apps.get_model('institution', 'ManualEditSession')
    now = timezone.now()
    # ① 文件分工与提交编制随旧模型废弃：负责人清空、提交记录清空
    ManualFile.objects.update(
        owner_id=None, owner_name='',
        submission_revision=None, submitted_at=None, submitted_by=None)
    # ② 编辑会话整体失效（镜像 0003：活跃会话撤销留痕，全部清空 doc key）
    ManualEditSession.objects.filter(
        revoked_at__isnull=True, expires_at__gt=now,
    ).update(
        revoked_at=now, revoked_reason='授权模型改造，编辑会话整体失效',
        current_doc_key='')
    ManualEditSession.objects.exclude(current_doc_key='').update(
        current_doc_key='')
    # ---- fail-closed 校验：任一断言失败即终止，旧数据未改动 ----
    leftovers = ManualFile.objects.filter(
        Q(owner_id__isnull=False) | ~Q(owner_name='') |
        Q(submission_revision__isnull=False) |
        Q(submitted_at__isnull=False) | Q(submitted_by_id__isnull=False))
    if leftovers.exists():
        raise RuntimeError('institution 授权模型改造清理失败: 仍有未清空的文件分工/提交记录')
    if ManualEditSession.objects.filter(
            revoked_at__isnull=True, expires_at__gt=now).exists():
        raise RuntimeError('institution 授权模型改造清理失败: 仍有活跃编辑会话')
    if ManualEditSession.objects.exclude(current_doc_key='').exists():
        raise RuntimeError('institution 授权模型改造清理失败: 仍有未清空的会话文档键')


class Migration(migrations.Migration):

    dependencies = [
        ('institution', '0007_manualeditsession_final_callback_allowed'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='manual', name='inst_manual_owner_type_valid',
        ),
        migrations.RenameField(
            model_name='manual', old_name='owner_type', new_name='org_type',
        ),
        migrations.RenameField(
            model_name='manual', old_name='owner_name', new_name='org_name',
        ),
        migrations.AddConstraint(
            model_name='manual',
            constraint=models.CheckConstraint(
                check=models.Q(org_type__in=['department', 'section']),
                name='inst_manual_org_type_valid',
            ),
        ),
        migrations.AddField(
            model_name='manual',
            name='owner',
            field=models.ForeignKey(blank=True, null=True,
                                    on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='institution_owned_manuals',
                                    to='account.user', verbose_name='所有者账号'),
        ),
        migrations.CreateModel(
            name='ManualAuthorization',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('tenant_id', models.CharField(default='', help_text='租户标识',
                                               max_length=50)),
                ('can_view', models.BooleanField(default=False, verbose_name='可查看')),
                ('can_edit', models.BooleanField(default=False, verbose_name='可编制')),
                ('can_publish', models.BooleanField(default=False, verbose_name='可发布')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='institution_manual_grants',
                                              to='account.user', verbose_name='授权账号')),
                ('manual', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                             related_name='account_grants',
                                             to='institution.manual',
                                             verbose_name='所属手册')),
                ('updated_by', models.ForeignKey(blank=True, null=True,
                                                 on_delete=django.db.models.deletion.SET_NULL,
                                                 related_name='+', to='account.user',
                                                 verbose_name='更新操作人')),
            ],
            options={
                'verbose_name': '手册账号授权',
                'verbose_name_plural': '手册账号授权',
                'db_table': 'tdyw_institution_authorization',
                'ordering': ['account_id'],
            },
        ),
        migrations.RemoveField(model_name='manual', name='view_roles'),
        migrations.RemoveField(model_name='manual', name='edit_roles'),
        migrations.RemoveField(model_name='manual', name='publish_roles'),
        migrations.AddConstraint(
            model_name='manualauthorization',
            constraint=models.UniqueConstraint(
                fields=('manual', 'account'), name='inst_auth_manual_account'),
        ),
        migrations.AddIndex(
            model_name='manualauthorization',
            index=models.Index(fields=['account'], name='inst_auth_account_idx'),
        ),
        migrations.RunPython(
            cleanup_legacy_authorization_data, migrations.RunPython.noop),
    ]
