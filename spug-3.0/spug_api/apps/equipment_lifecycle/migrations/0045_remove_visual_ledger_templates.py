# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""旧可视化台账模板路线破坏性下线迁移（2026-10）。

正式维护台账统一使用 Excel/WPS 模板路线（OperationLedgerExcelTemplate 体系，
created_from='excel_template'），本迁移一次性完成：

1. 业务数据清理（RunPython，单事务，失败整体回滚）：
   - created_from='template' 的历史可视化台账及其明细、行实例、更正记录；
   - 全部旧模板记录（tdyw_el_ledger_template / tdyw_el_ledger_template_item /
     tdyw_el_ledger_row_template_node / tdyw_el_ledger_row_instance）；
   - 仅属于被删台账/明细的 evidence 附件数据库行；物理文件在数据库删除
     完成后尽力删除（失败保留孤儿文件并 stderr 告警，与
     purge_legacy_inspection_ledgers 命令同一策略）；
   - 引用被删明细的 SystemFault：先把来源语义快照写入 source_ledger_legacy，
     再解除 source_ledger_item 外键（故障本身不删除、来源类型不变）；
   - SystemEvent / AuditLog 为文本快照引用（哈希链不可破坏），原样保留；
   - created_from='manual' / 'excel_template' 台账、Excel 模板/版本/填写记录
     一律不动。
2. 表结构收缩：
   - OperationLedger：删除 template 外键与 row_headers_snapshot 列；
     created_from 默认值改 manual 并收窄 CHECK 值域（template 移出）；
   - OperationLedgerItem：删除 template_item / row_instance 外键与矩阵
     单元格快照列（row_path/row_level/row_code/column_name/column_code/
     cell_code/operation_guide）；
   - DeleteModel 四张旧模板表。

注意：运行环境必须先满足 Excel 路线所需（无额外前置）；
迁移不修改任何已执行历史迁移，回滚不可恢复已删数据（删表操作反向为空）。
"""
import json
import os
import sys

from django.conf import settings
from django.db import migrations, models

# 与 ledger_views.py 保持一致的附件归属标识
EL_ATTACHMENT_MODULE = 'equipment_lifecycle'
LEDGER_ATTACHMENT_OBJECT_TYPE = 'el_operation_ledger'
LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE = 'el_operation_ledger_item'

LEDGER_FROM_TEMPLATE = 'template'


def purge_visual_template_data(apps, schema_editor):
    """清理 created_from='template' 台账及其关联数据 + 旧模板全表数据。

    删除顺序：故障外键解除 → 附件行 → 更正记录 → 明细 → 行实例 →
    台账表头 → 行模板节点 → 模板项目 → 模板；物理文件最后尽力删除。
    """
    OperationLedger = apps.get_model('equipment_lifecycle', 'OperationLedger')
    OperationLedgerItem = apps.get_model('equipment_lifecycle', 'OperationLedgerItem')
    OperationLedgerCorrection = apps.get_model('equipment_lifecycle', 'OperationLedgerCorrection')
    OperationLedgerRowInstance = apps.get_model('equipment_lifecycle', 'OperationLedgerRowInstance')
    OperationLedgerRowTemplateNode = apps.get_model('equipment_lifecycle', 'OperationLedgerRowTemplateNode')
    OperationLedgerTemplate = apps.get_model('equipment_lifecycle', 'OperationLedgerTemplate')
    OperationLedgerTemplateItem = apps.get_model('equipment_lifecycle', 'OperationLedgerTemplateItem')
    SystemFault = apps.get_model('equipment_lifecycle', 'SystemFault')
    EvidenceAttachment = apps.get_model('evidence', 'EvidenceAttachment')

    ledgers = list(OperationLedger.objects.filter(created_from=LEDGER_FROM_TEMPLATE))
    ledger_ids = [l.id for l in ledgers]
    ledger_map = {l.id: l for l in ledgers}
    items = list(OperationLedgerItem.objects.filter(ledger_id__in=ledger_ids))
    item_ids = [i.id for i in items]
    item_map = {i.id: i for i in items}

    # 1) 解除故障来源外键（PROTECT），写 legacy 快照保留历史语义
    for fault in SystemFault.objects.filter(source_ledger_item_id__in=item_ids):
        item = item_map[fault.source_ledger_item_id]
        ledger = ledger_map[item.ledger_id]
        snapshot = json.dumps({
            'ledger_id': ledger.id,
            'ledger_no': ledger.ledger_no,
            'ledger_type': ledger.ledger_type,
            'ledger_executed_date': str(ledger.executed_date),
            'ledger_item_id': item.id,
            'item_name': item.item_name_snapshot,
            'result': item.result,
            'abnormal_desc': item.abnormal_desc,
            'system_code': item.system_code_snapshot,
            'system_name': item.system_name_snapshot,
            'system_location': item.system_location_snapshot,
            'legacy_note': '旧可视化模板台账已删除，来源为已删除的可视化模板台账明细',
        }, ensure_ascii=False)
        SystemFault.objects.filter(pk=fault.id).update(
            source_ledger_legacy=snapshot, source_ledger_item=None)

    # 2) 附件数据库行硬删除，物理文件在删除完成后尽力清理
    attachment_paths = list(EvidenceAttachment.objects.filter(
        module=EL_ATTACHMENT_MODULE,
        object_type__in=[LEDGER_ATTACHMENT_OBJECT_TYPE, LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE],
        object_id__in=[str(i) for i in ledger_ids + item_ids],
    ).values_list('file_path', flat=True))
    EvidenceAttachment.objects.filter(
        module=EL_ATTACHMENT_MODULE,
        object_type__in=[LEDGER_ATTACHMENT_OBJECT_TYPE, LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE],
        object_id__in=[str(i) for i in ledger_ids + item_ids],
    ).delete()

    # 3) 业务数据删除（更正 → 明细 → 行实例 → 台账）
    OperationLedgerCorrection.objects.filter(ledger_id__in=ledger_ids).delete()
    OperationLedgerItem.objects.filter(id__in=item_ids).delete()
    OperationLedgerRowInstance.objects.filter(ledger_id__in=ledger_ids).delete()
    OperationLedger.objects.filter(id__in=ledger_ids).delete()

    # 4) 旧模板全表数据删除（随后 DeleteModel 删表）
    OperationLedgerRowTemplateNode.objects.all().delete()
    OperationLedgerTemplateItem.objects.all().delete()
    OperationLedgerTemplate.objects.all().delete()

    # 5) 附件物理文件尽力删除（失败保留孤儿文件，不阻断迁移）
    media_root = os.path.realpath(getattr(settings, 'MEDIA_ROOT', '') or '')
    for rel_path in attachment_paths:
        if not rel_path or not media_root:
            continue
        abs_path = os.path.realpath(os.path.join(media_root, rel_path))
        if not abs_path.startswith(media_root):
            continue
        try:
            if os.path.exists(abs_path):
                os.remove(abs_path)
        except OSError as e:
            print('孤立文件（删除失败，请人工清理）: %s（%s）' % (rel_path, e), file=sys.stderr)


def noop_reverse(apps, schema_editor):
    """数据删除不可逆（破坏性迁移按任务要求不保留旧数据，无反向恢复）。"""


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0044_alter_inspectionrecord_round_no'),
    ]

    operations = [
        migrations.RunPython(purge_visual_template_data, noop_reverse),

        # 台账表头：删除来源模板外键与行层级表头快照列
        migrations.RemoveField(
            model_name='operationledger',
            name='template',
        ),
        migrations.RemoveField(
            model_name='operationledger',
            name='row_headers_snapshot',
        ),
        # 台账明细：删除模板项目/行实例外键与矩阵单元格快照列
        migrations.RemoveField(
            model_name='operationledgeritem',
            name='template_item',
        ),
        migrations.RemoveField(
            model_name='operationledgeritem',
            name='row_instance',
        ),
        migrations.RemoveField(
            model_name='operationledgeritem',
            name='row_path_snapshot',
        ),
        migrations.RemoveField(
            model_name='operationledgeritem',
            name='row_level_snapshot',
        ),
        migrations.RemoveField(
            model_name='operationledgeritem',
            name='row_code_snapshot',
        ),
        migrations.RemoveField(
            model_name='operationledgeritem',
            name='column_name_snapshot',
        ),
        migrations.RemoveField(
            model_name='operationledgeritem',
            name='column_code_snapshot',
        ),
        migrations.RemoveField(
            model_name='operationledgeritem',
            name='cell_code_snapshot',
        ),
        migrations.RemoveField(
            model_name='operationledgeritem',
            name='operation_guide_snapshot',
        ),
        # created_from 默认值与 CHECK 值域收窄（template 移出，Django 4.2 用 Remove+Add）
        migrations.AlterField(
            model_name='operationledger',
            name='created_from',
            field=models.CharField(default='manual', help_text='创建方式（manual 临时补录 / excel_template Excel模板）', max_length=20),
        ),
        migrations.RemoveConstraint(
            model_name='operationledger',
            name='el_operation_ledger_created_from_valid',
        ),
        migrations.AddConstraint(
            model_name='operationledger',
            constraint=models.CheckConstraint(
                check=models.Q(created_from__in=['manual', 'excel_template']),
                name='el_operation_ledger_created_from_valid',
            ),
        ),
        # 删除旧可视化模板四表
        migrations.DeleteModel(
            name='OperationLedgerRowInstance',
        ),
        migrations.DeleteModel(
            name='OperationLedgerRowTemplateNode',
        ),
        migrations.DeleteModel(
            name='OperationLedgerTemplateItem',
        ),
        migrations.DeleteModel(
            name='OperationLedgerTemplate',
        ),
    ]
