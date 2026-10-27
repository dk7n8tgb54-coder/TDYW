# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""升级记录/升级方案挂接系统档案（equipment_lifecycle.LifecycleSystem）。

手写迁移（勿用 autodetector 重建）：
- UpgradeRecord 原 system 纯文本列重命名为 system_name（快照语义，保留历史文本），
  新增正式外键 system（PROTECT，历史未匹配记录允许为空）与编号/地点快照列；
- UpgradeTemplate 同样重命名 + 新增外键（方案为可编辑预设，名称快照仅兜底展示）；
- 数据回填：按租户内名称不分大小写匹配系统档案，匹配上写外键与快照，
  匹配不上保留纯文本快照、外键置空；
- 删除「升级系统」字典表 UpgradeSystem（候选系统改由系统档案提供）。
"""
import os

from django.db import migrations, models
import django.db.models.deletion


def _equipment_lifecycle_gated():
    """equipment_lifecycle 是否在 RELEASE_PENDING_APPS 门控清单中（与
    spug/settings.py 同一口径）。门控时 EL 迁移包整体不加载，本迁移对
    ('equipment_lifecycle', '0001_initial') 的依赖会成为悬空节点，令
    迁移图构建失败（NodeNotFoundError）；门控场景即"保留数据、隐藏
    模块"，本迁移早已应用、该依赖仅约束首次应用顺序，故门控下跳过。
    与 settings.SILENCED_SYSTEM_CHECKS 的条件静默配套。"""
    return 'equipment_lifecycle' in {
        a.strip()
        for a in os.environ.get('RELEASE_PENDING_APPS', '').split(',')
        if a.strip()
    }


def backfill_system_link(apps, schema_editor):
    """历史文本系统名按租户内名称（不分大小写）匹配系统档案，写外键与快照。"""
    UpgradeRecord = apps.get_model('upgrade', 'UpgradeRecord')
    UpgradeTemplate = apps.get_model('upgrade', 'UpgradeTemplate')
    LifecycleSystem = apps.get_model('equipment_lifecycle', 'LifecycleSystem')

    def _match(tenant_id, name):
        if not name or not str(name).strip():
            return None
        return (
            LifecycleSystem.objects
            .filter(tenant_id=tenant_id, name__iexact=str(name).strip())
            .order_by('id')
            .first()
        )

    for record in UpgradeRecord.objects.all().iterator():
        system = _match(record.tenant_id, record.system_name)
        if not system:
            continue
        record.system = system
        record.system_code = system.system_code
        record.system_location = system.install_location
        record.save(update_fields=['system', 'system_code', 'system_location'])

    for template in UpgradeTemplate.objects.all().iterator():
        system = _match(template.tenant_id, template.system_name)
        if not template.system_id and system:
            template.system = system
            template.system_name = system.name
            template.save(update_fields=['system', 'system_name'])


class Migration(migrations.Migration):

    dependencies = [
        ('upgrade', '0021_alter_upgraderecord_unique_together_and_more'),
        # 2026-10 el 迁移合并：0001-0054 已折叠为单个 0001_initial，
        # 本迁移的历史数据回填（LifecycleSystem 名称匹配）依赖其表结构
    ]
    if not _equipment_lifecycle_gated():
        dependencies.append(('equipment_lifecycle', '0001_initial'))

    operations = [
        # 1. 升级记录：文本列 → 名称快照列
        migrations.RenameField(
            model_name='upgraderecord',
            old_name='system',
            new_name='system_name',
        ),
        migrations.AlterField(
            model_name='upgraderecord',
            name='system_name',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='系统名称快照'),
        ),
        migrations.AddField(
            model_name='upgraderecord',
            name='system_code',
            field=models.CharField(blank=True, default='', max_length=50, verbose_name='系统编号快照'),
        ),
        migrations.AddField(
            model_name='upgraderecord',
            name='system_location',
            field=models.CharField(blank=True, default='', max_length=200, verbose_name='系统安装地点快照'),
        ),
        # 2. 升级记录：新增系统档案正式外键
        migrations.AddField(
            model_name='upgraderecord',
            name='system',
            field=models.ForeignKey(blank=True, help_text='升级系统（正式系统 ID；历史未匹配记录允许为空）', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='upgrade_records', to='equipment_lifecycle.lifecyclesystem'),
        ),
        # 3. 升级方案：同样重命名 + 新增外键
        migrations.RenameField(
            model_name='upgradetemplate',
            old_name='system',
            new_name='system_name',
        ),
        migrations.AlterField(
            model_name='upgradetemplate',
            name='system_name',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='系统名称快照'),
        ),
        migrations.AddField(
            model_name='upgradetemplate',
            name='system',
            field=models.ForeignKey(blank=True, help_text='升级系统（正式系统 ID；历史未匹配方案允许为空）', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='upgrade_templates', to='equipment_lifecycle.lifecyclesystem'),
        ),
        # 4. 数据回填（按名称匹配系统档案）
        migrations.RunPython(backfill_system_link, migrations.RunPython.noop),
        # 5. 按系统查询索引
        migrations.AddIndex(
            model_name='upgraderecord',
            index=models.Index(fields=['tenant_id', 'system'], name='upg_rec_system_idx'),
        ),
        # 6. 删除「升级系统」字典表
        migrations.DeleteModel(
            name='UpgradeSystem',
        ),
    ]
