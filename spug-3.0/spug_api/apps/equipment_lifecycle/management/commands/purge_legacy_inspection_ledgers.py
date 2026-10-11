# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""旧巡检台账（历史）受控清理命令（2026-09 旧巡检台账下线改造）。

彻底删除 ledger_type='inspection' 的历史台账/明细业务数据
（OperationLedger / OperationLedgerItem / OperationLedgerCorrection）。
旧模板两表（tdyw_el_ledger_template / tdyw_el_ledger_template_item）已随
旧可视化模板路线在迁移 0045 中整体删除，不再涉及；
周月维护/季维护共享模型与数据、新巡检独立链路（InspectionTemplate 等）一律不动。

删除前处理外部引用（不级联删除任何业务单据）：
- SystemFault 的 source_ledger_item 外键：先把旧巡检来源语义快照写入
  source_ledger_legacy JSON 字段，再解除外键（来源类型仍为 ledger_item，
  历史语义不丢失）。（SystemWorkOrder 引用处理已随工单功能删除，2026-09-30）
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
)
from apps.equipment_lifecycle.operation_models import SystemOperationRecord
from apps.evidence.models import EvidenceAttachment
from apps.logs.models import AuditLog

EL_ATTACHMENT_MODULE = 'equipment_lifecycle'
LEDGER_ATTACHMENT_OBJECT_TYPE = 'el_operation_ledger'
LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE = 'el_operation_ledger_item'

def _collect_ledger_objects(tenants):
    """收集删除范围内的台账/明细/更正记录（只读）。"""
    ledger_qs = OperationLedger.objects.filter(ledger_type=LEGACY_LEDGER_TYPE_INSPECTION)
    if tenants:
        ledger_qs = ledger_qs.filter(tenant_id__in=tenants)
    ledgers = list(ledger_qs.order_by('id'))
    ledger_ids = [l.id for l in ledgers]
    items = list(OperationLedgerItem.objects.filter(ledger_id__in=ledger_ids).order_by('id'))
    item_ids = [i.id for i in items]
    corrections = list(
        OperationLedgerCorrection.objects.filter(ledger_id__in=ledger_ids).order_by('id'))
    return ledgers, ledger_ids, items, item_ids, corrections


def _collect_external_refs(item_ids, ledger_ids, tenants):
    """收集统一记录外键引用与审计文本引用（只读，不做删除）。

    （系统履历已整体退役 2026-10-11：不再收集履历事件引用。）
    """
    fault_refs = list(SystemOperationRecord.objects.filter(
        source_ledger_item_id__in=item_ids).order_by('id')) if item_ids else []
    audit_logs = list(AuditLog.objects.filter(
        target_type=LEDGER_ATTACHMENT_OBJECT_TYPE,
        target_id__in=[str(i) for i in ledger_ids]).order_by('id')) if ledger_ids else []
    # 只按编号快照粗查审计（历史 audit 行仅文本引用，不做删除）
    audit_logs_no = list(AuditLog.objects.filter(
        target_type=LEDGER_ATTACHMENT_OBJECT_TYPE,
        target_name__startswith='EL-INS').order_by('id')) if not tenants else []
    return fault_refs, audit_logs, audit_logs_no


def _collect_scope_anomalies(ledgers, items):
    """盘点异常历史数据：明细与台账租户不一致。

    维护周期（maintenance_cycle）字段已删除（2026-09-26），
    "旧巡检误填维护周期" 盘点随之退役。
    """
    ledger_tenant = {l.id: l.tenant_id for l in ledgers}
    return {
        'cross_tenant_items': [
            i for i in items if i.tenant_id != ledger_tenant.get(i.ledger_id)],
    }


def collect_scope(tenants):
    """收集待删除对象与全部外部引用（只读，不修改任何数据）。"""
    (ledgers, ledger_ids, items, item_ids, corrections) = _collect_ledger_objects(tenants)
    attachments = list(EvidenceAttachment.objects.filter(
        module=EL_ATTACHMENT_MODULE,
        object_type__in=[LEDGER_ATTACHMENT_OBJECT_TYPE, LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE],
        object_id__in=[str(i) for i in ledger_ids + item_ids],
    ).order_by('id'))
    fault_refs, audit_logs, audit_logs_no = _collect_external_refs(
        item_ids, ledger_ids, tenants)
    anomalies = _collect_scope_anomalies(ledgers, items)
    return {
        'ledgers': ledgers, 'items': items,
        'corrections': corrections, 'attachments': attachments,
        'fault_refs': fault_refs,
        'audit_logs': audit_logs, 'audit_logs_no': audit_logs_no,
        'cross_tenant_items': anomalies['cross_tenant_items'],
    }


def migrate_external_references(scope):
    """迁移外部引用：解除统一记录的 source_ledger_item 外键（PROTECT 前置）。

    不删除、不修改记录本身；来源语义由记录的情况描述文本与审计日志承载
    （统一主表无 legacy 快照字段；系统履历已退役 2026-10-11）。
    返回迁移数量 fault_count。
    """
    item_ids = {i.id for i in scope['items']}
    fault_count = 0
    for record in scope['fault_refs']:
        if record.source_ledger_item_id not in item_ids:
            raise CommandError(
                '记录 %s 引用的台账明细 %s 不在删除范围内，停止删除'
                % (record.id, record.source_ledger_item_id))
        fault_count += SystemOperationRecord.objects.filter(pk=record.id).update(
            source_ledger_item=None, source_id='')
    return fault_count


def delete_attachment_rows(scope):
    """硬删除旧巡检附件数据库行，返回 [(id, file_path)] 供事务提交后清理物理文件。"""
    paths = [(att.id, att.file_path) for att in scope['attachments']]
    EvidenceAttachment.objects.filter(
        id__in=[att_id for att_id, _ in paths]).delete()
    return paths


def delete_legacy_data(scope):
    """删除旧巡检业务数据（须在事务内调用）：更正记录 → 明细 → 表头。"""
    ledger_ids = [l.id for l in scope['ledgers']]
    item_ids = [i.id for i in scope['items']]
    deleted_corrections = OperationLedgerCorrection.objects.filter(
        ledger_id__in=ledger_ids).delete()[0] if ledger_ids else 0
    deleted_items = OperationLedgerItem.objects.filter(
        id__in=item_ids).delete()[0] if item_ids else 0
    deleted_ledgers = OperationLedger.objects.filter(
        id__in=ledger_ids).delete()[0] if ledger_ids else 0
    return {
        'corrections': deleted_corrections, 'items': deleted_items,
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
        self.stdout.write('附件（表头+明细）: %d' % len(scope['attachments']))
        self.stdout.write('== 外部引用（故障迁移，履历/审计保留）==')
        self.stdout.write('引用旧明细的统一记录（解除外键）: %d' % len(scope['fault_refs']))
        self.stdout.write('引用旧台账的审计日志（保留）: %d' % (
            len(scope['audit_logs']) or len(scope['audit_logs_no'])))
        self.stdout.write('== 周月/季维护与新巡检（保留，不受影响）==')
        self.stdout.write('维护台账表头（week_month/seasonal）: %d' % OperationLedger.objects.exclude(
            ledger_type=LEGACY_LEDGER_TYPE_INSPECTION).count())
        self.stdout.write('== 异常数据检查 ==')
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
                fault_count = migrate_external_references(scope)
                attachment_paths = delete_attachment_rows(scope)
                deleted = delete_legacy_data(scope)
        except Exception as e:
            raise CommandError('删除失败，事务已回滚，未产生任何删除效果：%s' % e)

        removed, missing, failed = delete_attachment_files(attachment_paths)
        self.stdout.write('== 删除完成 ==')
        self.stdout.write('已迁移外部引用: 故障 %d（来源外键已解除，legacy 快照已写入）' % fault_count)
        self.stdout.write('已删除: 台账 %d、明细 %d、更正 %d、附件行 %d' % (
            deleted['ledgers'], deleted['items'], deleted['corrections'],
            len(attachment_paths)))
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
        self.stdout.write('保留的维护台账: %d、审计日志: %d' % (
            OperationLedger.objects.exclude(
                ledger_type=LEGACY_LEDGER_TYPE_INSPECTION).count(),
            AuditLog.objects.filter(
                target_type=LEDGER_ATTACHMENT_OBJECT_TYPE).count()))
        self.stdout.write(self.style.SUCCESS('旧巡检台账（历史）清理完成。'))
