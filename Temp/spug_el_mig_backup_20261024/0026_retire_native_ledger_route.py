# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""原生维护台账路线整体下线（2026-10-20）：清数据 → 收窄来源约束 → 删三表。

业务决定：不保留原生模板、版本、填写记录或原生台账；继续保留 Excel 台账
模板、Excel 台账、手工补录及其全部数据和功能。历史迁移（0023_native_
ledger_templates 等）不删除、不改写，清理与删除全部发生在本迁移。

执行顺序（清数步骤带数量断言，防止误伤 Excel/手工台账）：
1. 防御性预检：原生台账不应有明细行（原生路线无 OperationLedgerItem），
   也不应有统一记录引用其明细；出现即说明存在未盘点的外键关联，
   fail-fast 拒绝执行；
2. 清数据：按 created_from='native_template' 精确圈定台账，先删关联更正
   （Correction.ledger PROTECT）、再删原生填写记录（NativeRecord.version
   PROTECT 引用版本，必须先于版本删除），然后删原生台账行；随后清空原生
   版本与模板（含无台账引用的孤儿记录，正常为 0）。清理后断言四类原生
   数据余量为 0、非原生台账数量不变；
3. 收窄 created_from：Remove + Add CHECK（Django 4.2 无 AlterConstraint），
   值域收回 manual / excel_template，并同步字段 help_text；
4. 删除三张原生业务表：填写记录 → 模板版本 → 模板（按外键方向）。

回滚方式：本迁移为破坏性数据迁移（业务数据物理删除），反向不可逆；
如需回滚请使用迁移前的数据库备份整体恢复，不做行级反推。

审计日志：audit_logs 为哈希链表，原生路线的历史审计行（模板创建/发布/
台账创建等，target_type=el_ledger_native_template 等）按规则保留，不做
删除或改写；历史审计中的原生业务标识为快照性记录，仅作历史追溯。

角色权限：前端角色权限树已删除 lab.native_ledger 项；本迁移顺带清理
Role.page_perms 中可能残留的 lab.native_ledger.view 权限串（实测多数环境
无角色持有该权限，本步骤为幂等空操作），清理后 perms_version 自增使
用户权限缓存按版本失效。
"""
import json

from django.db import migrations, models


def retire_native_ledger_data(apps, schema_editor):
    """按 created_from='native_template' 精确清理原生路线业务数据。"""
    Ledger = apps.get_model('equipment_lifecycle', 'OperationLedger')
    LedgerItem = apps.get_model('equipment_lifecycle', 'OperationLedgerItem')
    Correction = apps.get_model('equipment_lifecycle', 'OperationLedgerCorrection')
    UnifiedRecord = apps.get_model('equipment_lifecycle', 'SystemOperationRecord')
    NativeRecord = apps.get_model('equipment_lifecycle', 'OperationLedgerNativeRecord')
    NativeVersion = apps.get_model(
        'equipment_lifecycle', 'OperationLedgerNativeTemplateVersion')
    NativeTemplate = apps.get_model(
        'equipment_lifecycle', 'OperationLedgerNativeTemplate')

    native_qs = Ledger.objects.filter(created_from='native_template')
    native_ids = list(native_qs.values_list('id', flat=True))
    kept_before = Ledger.objects.exclude(created_from='native_template').count()
    if native_ids:
        if LedgerItem.objects.filter(ledger_id__in=native_ids).exists():
            raise RuntimeError(
                '[0026] 原生台账存在明细行，存在未盘点外键关联，迁移终止')
        if UnifiedRecord.objects.filter(
                source_ledger_item__ledger_id__in=native_ids).exists():
            raise RuntimeError(
                '[0026] 统一记录引用原生台账明细，存在未盘点外键关联，迁移终止')

    corrections_deleted = Correction.objects.filter(
        ledger_id__in=native_ids).count()
    Correction.objects.filter(ledger_id__in=native_ids).delete()
    records_deleted = NativeRecord.objects.filter(
        ledger_id__in=native_ids).count()
    NativeRecord.objects.filter(ledger_id__in=native_ids).delete()
    # 孤儿填写记录（关联台账的 created_from 非原生，正常为 0）：表即将删除，
    # 一并清理并单独计数核对
    orphans_deleted = NativeRecord.objects.exclude(
        ledger_id__in=native_ids).count()
    NativeRecord.objects.exclude(ledger_id__in=native_ids).delete()
    ledgers_deleted = native_qs.count()
    native_qs.delete()
    versions_deleted = NativeVersion.objects.count()
    NativeVersion.objects.all().delete()
    templates_deleted = NativeTemplate.objects.count()
    NativeTemplate.objects.all().delete()

    # 数量断言：原生数据清零，Excel/手工台账数量不受影响
    assert Ledger.objects.filter(created_from='native_template').count() == 0
    assert NativeRecord.objects.count() == 0
    assert NativeVersion.objects.count() == 0
    assert NativeTemplate.objects.count() == 0
    kept_after = Ledger.objects.exclude(created_from='native_template').count()
    assert kept_after == kept_before, (
        '[0026] 非原生台账数量变化：%s -> %s' % (kept_before, kept_after))
    print('[0026] native retire: corrections=%s records=%s orphan_records=%s '
          'ledgers=%s versions=%s templates=%s'
          % (corrections_deleted, records_deleted, orphans_deleted,
             ledgers_deleted, versions_deleted, templates_deleted))


def cleanup_lab_native_ledger_perms(apps, schema_editor):
    """清理角色权限中残留的 lab.native_ledger 权限串（幂等）。

    perms_version 无需手动自增：Role.save 检测到 page_perms 变化时自动
    bump 并把 perms_version 补进 update_fields（含迁移 RunPython 路径）。
    """
    Role = apps.get_model('account', 'Role')
    for role in Role.objects.filter(page_perms__contains='native_ledger'):
        try:
            perms = json.loads(role.page_perms)
        except (ValueError, TypeError):
            continue
        if not isinstance(perms, dict):
            continue
        lab = perms.get('lab')
        if not isinstance(lab, dict) or 'native_ledger' not in lab:
            continue
        lab.pop('native_ledger', None)
        if lab:
            perms['lab'] = lab
        else:
            perms.pop('lab', None)
        role.page_perms = json.dumps(perms, ensure_ascii=False)
        role.save(update_fields=['page_perms'])


# 收窄后的 created_from 值域约束（模块级常量：AddConstraint 与下线契约测试
# 的播种/恢复共用同一对象）
NARROWED_CREATED_FROM_CHECK = models.CheckConstraint(
    check=models.Q(created_from__in=['manual', 'excel_template']),
    name='el_operation_ledger_created_from_valid',
)


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0014_remove_tenant_is_active'),
        ('equipment_lifecycle', '0025_config_category_and_baseline'),
    ]

    operations = [
        # 1+2. 数据清理（反向不可逆，回滚 = 备份恢复）
        migrations.RunPython(retire_native_ledger_data, migrations.RunPython.noop),
        migrations.RunPython(cleanup_lab_native_ledger_perms, migrations.RunPython.noop),
        # 3. 收窄 created_from 值域（先移除再加回，Django 4.2 无 AlterConstraint）
        migrations.RemoveConstraint(
            model_name='operationledger',
            name='el_operation_ledger_created_from_valid',
        ),
        migrations.AlterField(
            model_name='operationledger',
            name='created_from',
            field=models.CharField(default='manual', help_text='创建方式（manual 临时补录 / excel_template Excel模板）', max_length=20),
        ),
        migrations.AddConstraint(
            model_name='operationledger',
            constraint=NARROWED_CREATED_FROM_CHECK,
        ),
        # 4. 删除三张原生业务表（按外键方向：记录 → 版本 → 模板）
        migrations.DeleteModel(
            name='OperationLedgerNativeRecord',
        ),
        migrations.DeleteModel(
            name='OperationLedgerNativeTemplateVersion',
        ),
        migrations.DeleteModel(
            name='OperationLedgerNativeTemplate',
        ),
    ]
