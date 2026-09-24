# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""旧巡检台账（历史）受控清理命令（2026-09 旧巡检台账下线改造）。

彻底删除 OperationLedger / OperationLedgerItem / OperationLedgerTemplate /
OperationLedgerTemplateItem 中 ledger_type='inspection' 的历史业务数据，
周月维护/季维护共享模型与数据、新巡检独立链路（InspectionTemplate 等）一律不动。

删除前处理外部引用（不级联删除任何业务单据）：
- SystemFault / SystemWorkOrder 的 source_ledger_item 外键：先把旧巡检来源
  语义快照写入 source_ledger_legacy JSON 字段，再解除外键（来源类型仍为
  ledger_item，历史语义不丢失）；
- SystemEvent / AuditLog 为文本快照引用（无外键），原样保留；
- EvidenceAttachment 旧巡检附件：数据库行随事务硬删除，物理文件在事务提交
  后尽力删除（删除失败仅保留孤儿文件并告警，不影响数据库一致性）。

用法（默认 dry-run，只统计不删除）：
    python manage.py purge_legacy_inspection_ledgers
    python manage.py purge_legacy_inspection_ledgers --tenant admin
    python manage.py purge_legacy_inspection_ledgers --confirm

安全约束：
- 未提供 --confirm 时禁止删除；--confirm 与 --dry-run 同时出现时拒绝执行；
- 删除在单个事务内完成，任一步失败整体回滚；
- 生产部署顺序：先重建镜像 → 执行本命令 --confirm → 再执行 migrate
  （迁移 0028 的 CHECK 约束收窄带有历史数据前置防护，未清理会阻断并提示）。
"""
import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.equipment_lifecycle.models import (
    LEGACY_LEDGER_TYPE_INSPECTION,
    OperationLedger,
    OperationLedgerCorrection,
    OperationLedgerItem,
    OperationLedgerTemplate,
    OperationLedgerTemplateItem,
    SystemEvent,
    SystemFault,
    SystemWorkOrder,
)
from apps.evidence.models import EvidenceAttachment
from apps.logs.models import AuditLog

EL_ATTACHMENT_MODULE = 'equipment_lifecycle'
LEDGER_ATTACHMENT_OBJECT_TYPE = 'el_operation_ledger'
LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE = 'el_operation_ledger_item'

# 删除后复核用的保留统计
KEEP_EVENT_SOURCE_TYPES = ['ledger_item']


def collect_scope(tenants):
    """收集待删除对象与全部外部引用（只读，不修改任何数据）。"""
    ledger_qs = OperationLedger.objects.filter(ledger_type=LEGACY_LEDGER_TYPE_INSPECTION)
    template_qs = OperationLedgerTemplate.objects.filter(ledger_type=LEGACY_LEDGER_TYPE_INSPECTION)
    if tenants:
        ledger_qs = ledger_qs.filter(tenant_id__in=tenants)
        template_qs = template_qs.filter(tenant_id__in=tenants)
    ledgers = list(ledger_qs.order_by('id'))
    ledger_ids = [l.id for l in ledgers]
    items = list(OperationLedgerItem.objects.filter(ledger_id__in=ledger_ids).order_by('id'))
    item_ids = [i.id for i in items]
    templates = list(template_qs.order_by('id'))
    template_ids = [t.id for t in templates]
    template_items = list(
        OperationLedgerTemplateItem.objects.filter(template_id__in=template_ids).order_by('id'))
    corrections = list(
        OperationLedgerCorrection.objects.filter(ledger_id__in=ledger_ids).order_by('id'))

    attachments = list(EvidenceAttachment.objects.filter(
        module=EL_ATTACHMENT_MODULE,
        object_type__in=[LEDGER_ATTACHMENT_OBJECT_TYPE, LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE],
        object_id__in=[str(i) for i in ledger_ids + item_ids],
    ).order_by('id'))

    fault_refs = list(SystemFault.objects.filter(
        source_ledger_item_id__in=item_ids).order_by('id')) if item_ids else []
    order_refs = list(SystemWorkOrder.objects.filter(
        source_ledger_item_id__in=item_ids).order_by('id')) if item_ids else []
    item_id_strs = [str(i) for i in item_ids]
    events = list(SystemEvent.objects.filter(
        source_type__in=KEEP_EVENT_SOURCE_TYPES,
        source_id__in=item_id_strs).order_by('id')) if item_id_strs else []
    audit_logs = list(AuditLog.objects.filter(
        target_type=LEDGER_ATTACHMENT_OBJECT_TYPE,
        target_id__in=[str(i) for i in ledger_ids]).order_by('id')) if ledger_ids else []
    # 只按编号快照粗查审计（历史 audit 行仅文本引用，不做删除）
    audit_logs_no = list(AuditLog.objects.filter(
        target_type=LEDGER_ATTACHMENT_OBJECT_TYPE,
        target_name__startswith='EL-INS').order_by('id')) if not tenants else []

    # 异常数据：旧巡检类型误填了维护周期（违反当时组合约束的历史脏数据）
    anomaly_cycles = [l for l in ledgers if l.maintenance_cycle]
    anomaly_templates = [t for t in templates if t.maintenance_cycle]
    # 租户完整性：明细/引用与台账不在同一租户（理论不可能，防御性盘点）
    ledger_tenant = {l.id: l.tenant_id for l in ledgers}
    cross_tenant_items = [i for i in items if i.tenant_id != ledger_tenant.get(i.ledger_id)]

    return {
        'ledgers': ledgers, 'items': items,
        'templates': templates, 'template_items': template_items,
        'corrections': corrections, 'attachments': attachments,
        'fault_refs': fault_refs, 'order_refs': order_refs,
        'events': events, 'audit_logs': audit_logs, 'audit_logs_no': audit_logs_no,
        'anomaly_cycles': anomaly_cycles, 'anomaly_templates': anomaly_templates,
        'cross_tenant_items': cross_tenant_items,
    }


def build_legacy_snapshot(fault_or_order, item, ledger):
    """把旧巡检来源语义固化为 JSON 快照（故障/工单详情展示用）。"""
    return json.dumps({
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
        'legacy_note': '旧巡检台账（历史）已删除，来源为已删除的旧巡检台账明细',
    }, ensure_ascii=False)


def migrate_external_references(scope):
    """迁移外部引用：写 legacy 快照 + 解除 source_ledger_item 外键。

    不删除、不修改故障与工单本身；返回迁移数量 (fault_count, order_count)。
    """
    item_map = {i.id: i for i in scope['items']}
    ledger_map = {l.id: l for l in scope['ledgers']}
    fault_count = 0
    for fault in scope['fault_refs']:
        item = item_map.get(fault.source_ledger_item_id)
        if item is None:
            raise CommandError(
                '故障 %s 引用的台账明细 %s 不在删除范围内，停止删除' % (fault.id, fault.source_ledger_item_id))
        ledger = ledger_map.get(item.ledger_id)
        snapshot = build_legacy_snapshot(fault, item, ledger)
        updated = SystemFault.objects.filter(pk=fault.id).update(
            source_ledger_legacy=snapshot, source_ledger_item=None)
        fault_count += updated
    order_count = 0
    for order in scope['order_refs']:
        item = item_map.get(order.source_ledger_item_id)
        if item is None:
            raise CommandError(
                '工单 %s 引用的台账明细 %s 不在删除范围内，停止删除' % (order.id, order.source_ledger_item_id))
        ledger = ledger_map.get(item.ledger_id)
        snapshot = build_legacy_snapshot(order, item, ledger)
        updated = SystemWorkOrder.objects.filter(pk=order.id).update(
            source_ledger_legacy=snapshot, source_ledger_item=None)
        order_count += updated
    return fault_count, order_count


def delete_attachment_rows(scope):
    """硬删除旧巡检附件数据库行，返回 [(id, file_path)] 供事务提交后清理物理文件。"""
    paths = [(att.id, att.file_path) for att in scope['attachments']]
    EvidenceAttachment.objects.filter(
        id__in=[att_id for att_id, _ in paths]).delete()
    return paths


def delete_legacy_data(scope):
    """删除旧巡检业务数据（须在事务内调用）：更正记录 → 明细 → 模板 → 表头。"""
    ledger_ids = [l.id for l in scope['ledgers']]
    item_ids = [i.id for i in scope['items']]
    template_ids = [t.id for t in scope['templates']]
    deleted_corrections = OperationLedgerCorrection.objects.filter(
        ledger_id__in=ledger_ids).delete()[0] if ledger_ids else 0
    deleted_items = OperationLedgerItem.objects.filter(
        id__in=item_ids).delete()[0] if item_ids else 0
    deleted_template_items = OperationLedgerTemplateItem.objects.filter(
        template_id__in=template_ids).delete()[0] if template_ids else 0
    deleted_templates = OperationLedgerTemplate.objects.filter(
        id__in=template_ids).delete()[0] if template_ids else 0
    deleted_ledgers = OperationLedger.objects.filter(
        id__in=ledger_ids).delete()[0] if ledger_ids else 0
    return {
        'corrections': deleted_corrections, 'items': deleted_items,
        'template_items': deleted_template_items, 'templates': deleted_templates,
        'ledgers': deleted_ledgers,
    }


def delete_attachment_files(paths):
    """事务提交后尽力删除附件物理文件（失败仅告警，保留孤儿文件）。"""
    removed, missing, failed = 0, 0, []
    for _, rel_path in paths:
        if not rel_path:
            continue
        abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)
        real = os.path.realpath(abs_path)
        if not real.startswith(os.path.realpath(settings.MEDIA_ROOT)):
            failed.append(rel_path)
            continue
        if not os.path.exists(real):
            missing += 1
            continue
        try:
            os.remove(real)
            removed += 1
        except OSError as e:
            failed.append('%s（%s）' % (rel_path, e))
    return removed, missing, failed


class Command(BaseCommand):
    help = '受控删除旧巡检台账（ledger_type=inspection）历史数据；默认 dry-run 只统计'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true', dest='dry_run',
            help='只统计与检查，不做任何删除（默认行为，可显式声明）')
        parser.add_argument(
            '--confirm', action='store_true', dest='confirm',
            help='明确确认后执行删除；未提供时一律 dry-run')
        parser.add_argument(
            '--tenant', action='append', dest='tenants', default=[],
            help='限定租户 tenant_id，可重复传入；缺省为全部租户')

    def _print_stats(self, scope):
        ledgers = scope['ledgers']
        self.stdout.write('== 待删除（旧巡检 inspection）==')
        self.stdout.write('台账表头: %d' % len(ledgers))
        by_type = {}
        for l in ledgers:
            key = (l.tenant_id, l.status)
            by_type[key] = by_type.get(key, 0) + 1
        for (tenant, status), n in sorted(by_type.items()):
            self.stdout.write('  租户 %s / 状态 %s: %d' % (tenant, status, n))
        self.stdout.write('台账明细: %d' % len(scope['items']))
        self.stdout.write('台账更正记录: %d' % len(scope['corrections']))
        self.stdout.write('台账模板: %d' % len(scope['templates']))
        self.stdout.write('台账模板项目: %d' % len(scope['template_items']))
        self.stdout.write('附件（表头+明细）: %d' % len(scope['attachments']))
        self.stdout.write('== 外部引用（故障/工单迁移，履历/审计保留）==')
        self.stdout.write('引用旧明细的故障（解除外键+写快照）: %d' % len(scope['fault_refs']))
        self.stdout.write('引用旧明细的工单（解除外键+写快照）: %d' % len(scope['order_refs']))
        self.stdout.write('引用旧明细的系统履历事件（保留）: %d' % len(scope['events']))
        self.stdout.write('引用旧台账的审计日志（保留）: %d' % (
            len(scope['audit_logs']) or len(scope['audit_logs_no'])))
        self.stdout.write('== 周月/季维护与新巡检（保留，不受影响）==')
        self.stdout.write('维护台账表头（week_month/seasonal）: %d' % OperationLedger.objects.exclude(
            ledger_type=LEGACY_LEDGER_TYPE_INSPECTION).count())
        self.stdout.write('维护台账模板: %d' % OperationLedgerTemplate.objects.exclude(
            ledger_type=LEGACY_LEDGER_TYPE_INSPECTION).count())
        anomalies = scope['anomaly_cycles'] + scope['anomaly_templates']
        self.stdout.write('== 异常数据检查 ==')
        self.stdout.write('旧巡检误填维护周期: %d' % len(anomalies))
        self.stdout.write('明细与台账租户不一致: %d' % len(scope['cross_tenant_items']))

    def handle(self, *args, **options):
        confirm = options['confirm']
        if confirm and options['dry_run']:
            raise CommandError('--confirm 与 --dry-run 不能同时使用')
        tenants = [t for t in options['tenants'] if t]
        scope = collect_scope(tenants)
        self.stdout.write('旧巡检台账（历史）受控清理%s' % (
            '（租户: %s）' % '、'.join(tenants) if tenants else '（全部租户）'))
        self._print_stats(scope)

        if scope['cross_tenant_items']:
            raise CommandError(
                '发现 %d 条明细与所属台账租户不一致，无法安全迁移，停止删除；'
                '请先人工核查' % len(scope['cross_tenant_items']))

        if not confirm:
            self.stdout.write(self.style.WARNING(
                'DRY-RUN：未删除任何数据。确认无误后追加 --confirm 执行删除。'))
            return

        self.stdout.write('开始受控删除（单事务，失败自动回滚）...')
        try:
            with transaction.atomic():
                fault_count, order_count = migrate_external_references(scope)
                attachment_paths = delete_attachment_rows(scope)
                deleted = delete_legacy_data(scope)
        except Exception as e:
            raise CommandError('删除失败，事务已回滚，未产生任何删除效果：%s' % e)

        removed, missing, failed = delete_attachment_files(attachment_paths)
        self.stdout.write('== 删除完成 ==')
        self.stdout.write('已迁移外部引用: 故障 %d、工单 %d（来源外键已解除，legacy 快照已写入）' % (
            fault_count, order_count))
        self.stdout.write('已删除: 台账 %d、明细 %d、更正 %d、模板 %d、模板项目 %d、附件行 %d' % (
            deleted['ledgers'], deleted['items'], deleted['corrections'],
            deleted['templates'], deleted['template_items'], len(attachment_paths)))
        self.stdout.write('附件物理文件: 已删 %d、本不存在 %d、失败 %d' % (removed, missing, len(failed)))
        for path in failed:
            self.stdout.write(self.style.WARNING('  孤儿文件: %s' % path))
        remaining_ledgers = OperationLedger.objects.filter(
            ledger_type=LEGACY_LEDGER_TYPE_INSPECTION).count()
        remaining_items = OperationLedgerItem.objects.filter(
            ledger__ledger_type=LEGACY_LEDGER_TYPE_INSPECTION).count()
        if tenants:
            remaining_ledgers = OperationLedger.objects.filter(
                ledger_type=LEGACY_LEDGER_TYPE_INSPECTION,
                tenant_id__in=tenants).count()
            remaining_items = OperationLedgerItem.objects.filter(
                ledger__ledger_type=LEGACY_LEDGER_TYPE_INSPECTION,
                tenant_id__in=tenants).count()
        self.stdout.write('== 删除后复核 ==')
        self.stdout.write('残留旧巡检台账: %d（指定租户范围内应为 0）' % remaining_ledgers)
        self.stdout.write('残留旧巡检明细: %d' % remaining_items)
        self.stdout.write('保留的维护台账: %d、维护模板: %d、系统履历事件: %d、审计日志: %d' % (
            OperationLedger.objects.exclude(
                ledger_type=LEGACY_LEDGER_TYPE_INSPECTION).count(),
            OperationLedgerTemplate.objects.exclude(
                ledger_type=LEGACY_LEDGER_TYPE_INSPECTION).count(),
            SystemEvent.objects.filter(source_type__in=KEEP_EVENT_SOURCE_TYPES).count(),
            AuditLog.objects.filter(
                target_type=LEDGER_ATTACHMENT_OBJECT_TYPE).count()))
        self.stdout.write(self.style.SUCCESS('旧巡检台账（历史）清理完成。'))
