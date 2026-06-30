# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
升级方案合并迁移

将原「升级步骤清单」数据合并到「升级模板」：
- 每个 UpgradeChecklist 转换为一个 UpgradeTemplate（name 沿用，重名则加后缀），description 字段承载原清单描述。
- UpgradeChecklistStep 迁移到新表 UpgradePlanStep（外键 template_id 指向新方案）。
- 删除旧表 tdyw_upgrade_checklists / tdyw_upgrade_checklist_steps。

注意：UpgradeRecordStep.checklist_id 历史数据保留不变（可能指向已删除的旧 checklist），
合并后新数据语义为来源方案ID（template_id）。

本数据迁移为不可逆迁移（reverse 为空操作）。
"""
from django.db import migrations, models
import libs.mixins


def merge_checklist_into_template(apps, schema_editor):
    """将清单合并到方案模板，并迁移步骤"""
    UpgradeTemplate = apps.get_model('upgrade', 'UpgradeTemplate')
    UpgradePlanStep = apps.get_model('upgrade', 'UpgradePlanStep')
    UpgradeChecklist = apps.get_model('upgrade', 'UpgradeChecklist')
    UpgradeChecklistStep = apps.get_model('upgrade', 'UpgradeChecklistStep')

    # 记录每个租户已占用的方案名，用于重名处理
    used_names = set(
        UpgradeTemplate.objects.values_list('tenant_id', 'name')
    )
    # checklist_id -> 新 template_id 映射
    id_map = {}

    for cl in UpgradeChecklist.objects.all():
        name = cl.name or f'未命名清单{cl.id}'
        if (cl.tenant_id, name) in used_names:
            base = f'{name}(清单{cl.id})'
            name = base
            n = 2
            while (cl.tenant_id, name) in used_names:
                name = f'{base}{n}'
                n += 1
        used_names.add((cl.tenant_id, name))

        t = UpgradeTemplate.objects.create(
            tenant_id=cl.tenant_id,
            name=name,
            description=cl.description or '',
            system='',
            upgrade_type='',
            version='',
            owner='',
            status='处理中',
            detail_content='',
            is_default=cl.is_default or False,
            created_at=cl.created_at or '',
            created_by_id=cl.created_by_id,
            updated_at=cl.updated_at,
        )
        id_map[cl.id] = t.id

    # 迁移步骤
    for step in UpgradeChecklistStep.objects.all().order_by('checklist_id', 'sequence', 'id'):
        new_template_id = id_map.get(step.checklist_id)
        if not new_template_id:
            continue
        UpgradePlanStep.objects.create(
            tenant_id=step.tenant_id,
            template_id=new_template_id,
            title=step.title or '',
            description=step.description or '',
            sequence=step.sequence,
            is_required=step.is_required,
            created_at=step.created_at or '',
        )


def reverse_merge(apps, schema_editor):
    """数据迁移不可逆，reverse 为空操作

    旧表已删除，无法还原清单数据。如需回滚请从备份恢复。
    """
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('upgrade', '0003_upgrade_attachment'),
    ]

    operations = [
        # 1. 为 UpgradeTemplate 添加 description 字段（承载原清单描述/方案用途）
        migrations.AddField(
            model_name='upgradetemplate',
            name='description',
            field=models.TextField(blank=True, default='', verbose_name='方案描述'),
        ),
        # 2. 创建方案预设步骤表
        migrations.CreateModel(
            name='UpgradePlanStep',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_id', models.CharField(db_index=True, default='', help_text='租户标识', max_length=50)),
                ('template_id', models.IntegerField(verbose_name='关联方案ID')),
                ('title', models.CharField(max_length=200, verbose_name='步骤标题')),
                ('description', models.TextField(blank=True, default='', verbose_name='步骤描述')),
                ('sequence', models.IntegerField(default=0, verbose_name='排序序号')),
                ('is_required', models.BooleanField(default=True, verbose_name='是否必执行')),
                ('created_at', models.CharField(max_length=20, verbose_name='创建时间')),
            ],
            options={
                'db_table': 'tdyw_upgrade_plan_steps',
                'verbose_name': '方案预设步骤',
                'verbose_name_plural': '方案预设步骤',
                'ordering': ('template_id', 'sequence', 'id'),
            },
            bases=(models.Model, libs.mixins.ModelMixin),
        ),
        migrations.AddIndex(
            model_name='upgradeplanstep',
            index=models.Index(fields=['template_id'], name='tdyw_upgrad_templat_3f7a1a_idx'),
        ),
        migrations.AddIndex(
            model_name='upgradeplanstep',
            index=models.Index(fields=['tenant_id', 'template_id'], name='tdyw_upgrad_tenant__4a96ad_idx'),
        ),
        # 3. 数据迁移：清单 -> 方案模板，清单步骤 -> 方案预设步骤
        migrations.RunPython(merge_checklist_into_template, reverse_merge),
        # 4. 同步模型元信息变更（verbose_name 等，无数据库结构变更）
        migrations.AlterModelOptions(
            name='upgradetemplate',
            options={'db_table': 'tdyw_upgrade_templates', 'verbose_name': '升级方案', 'verbose_name_plural': '升级方案', 'ordering': ('-is_default', 'name', '-id')},
        ),
        migrations.AlterField(
            model_name='upgradetemplate',
            name='name',
            field=models.CharField(max_length=100, verbose_name='方案名称'),
        ),
        migrations.AlterField(
            model_name='upgradetemplate',
            name='is_default',
            field=models.BooleanField(default=False, verbose_name='是否为默认方案'),
        ),
        migrations.AlterField(
            model_name='upgraderecordstep',
            name='checklist_id',
            field=models.IntegerField(default=0, verbose_name='来源方案ID（0为手动添加）'),
        ),
        # 5. 删除旧表
        migrations.DeleteModel(
            name='UpgradeChecklist',
        ),
        migrations.DeleteModel(
            name='UpgradeChecklistStep',
        ),
    ]
