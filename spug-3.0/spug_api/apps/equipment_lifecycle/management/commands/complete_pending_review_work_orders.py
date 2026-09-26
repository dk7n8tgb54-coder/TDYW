# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""历史"待复核"工单人工迁移命令（单账号协同流程改造配套，2026-09）。

背景：单账号协同流程下线了提交复核/复核通过/复核退回环节。历史
pending_review 工单不做自动完成（不得根据猜测伪造完成事实），由管理员
通过本命令显式确认后逐单迁移为"已完成"。

用法：
- 查看待处理工单（dry-run，不做任何修改）：
    python manage.py complete_pending_review_work_orders
- 确认迁移（必须显式指定完成操作账号的用户名，且该账号必须存在）：
    python manage.py complete_pending_review_work_orders --confirm --username <登录名>

规则：
- 只有已填写处理结果（process_result 非空）的待复核工单才会被迁移
  （历史提交复核接口强制要求处理结果，正常数据均满足）；缺失者跳过并报告；
- 迁移动作：status → completed，completed_by/completed_at 记录执行命令的
  账号与当前时间（不写 reviewer/reviewed_at，不把历史复核人伪装成完成
  操作人），actual_end 优先取历史 reviewed_at（无则取当前时间）；
- 同事务写入工单完成履历（SystemEvent 'complete'）并重算系统健康状态；
- 命令幂等：只处理 pending_review 状态，重复执行无副作用；
- 不删除、不修改任何来源故障/巡检记录/台账/既有履历。
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.account.models import User
from apps.equipment_lifecycle import event_services, fault_services
from apps.equipment_lifecycle.models import SystemWorkOrder


class Command(BaseCommand):
    help = '把历史 pending_review 工单人工迁移为已完成（须显式 --confirm --username）'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm', action='store_true',
            help='确认执行迁移；缺省仅列出待处理工单（dry-run）')
        parser.add_argument(
            '--username', type=str, default='',
            help='完成操作账号的用户名（--confirm 时必填，须为有效账号）')

    def handle(self, *args, **options):
        confirm = options['confirm']
        username = (options['username'] or '').strip()
        pending_qs = SystemWorkOrder.objects.filter(
            status=SystemWorkOrder.STATUS_PENDING_REVIEW).order_by('id')
        pending = list(pending_qs)
        if not pending:
            self.stdout.write('没有 pending_review 状态的工单，无需迁移。')
            return

        self.stdout.write(f'待复核工单共 {len(pending)} 张：')
        for order in pending:
            has_result = bool((order.process_result or '').strip())
            self.stdout.write(
                f'  id={order.id} {order.work_no} {order.title} '
                f'处理结果={"已填写" if has_result else "缺失（将跳过）"} '
                f'创建人={order.created_by.username if order.created_by_id else "-"}')

        if not confirm:
            self.stdout.write('dry-run 结束：未做任何修改。确认迁移请追加 --confirm --username <登录名>')
            return

        if not username:
            raise CommandError('--confirm 时必须通过 --username 指定完成操作账号')
        operator = User.objects.filter(
            username=username, is_active=True, deleted_at__isnull=True).first()
        if not operator:
            raise CommandError(f'完成操作账号不存在或已停用：{username}')

        migrated, skipped = 0, 0
        now = timezone.now()
        for order in pending:
            if not (order.process_result or '').strip():
                skipped += 1
                self.stdout.write(self.style.WARNING(
                    f'  跳过 id={order.id} {order.work_no}：处理结果缺失，需人工补录后再执行'))
                continue
            with fault_services.health_recalc_lock():
                with transaction.atomic():
                    order.status = SystemWorkOrder.STATUS_COMPLETED
                    order.completed_by = operator
                    order.completed_at = now
                    order.actual_end = order.reviewed_at or now
                    order.updated_at = now
                    order.updated_by = operator
                    order.save(update_fields=[
                        'status', 'completed_by', 'completed_at', 'actual_end',
                        'updated_at', 'updated_by'])
                    event_services.record_work_order_lifecycle_events(
                        order, 'complete', occurred_at=order.actual_end,
                        created_by=operator)
                    fault_services.recompute_systems_health(
                        order.tenant_id, [order.system_id],
                        audit_reason='历史待复核工单迁移 ' + order.work_no)
            migrated += 1
            self.stdout.write(f'  已完成迁移 id={order.id} {order.work_no} → 已完成')

        self.stdout.write(self.style.SUCCESS(
            f'迁移完成：成功 {migrated} 张，跳过 {skipped} 张'
            f'（完成操作账号：{operator.username}）。'))
