# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from django.utils import timezone
from django.http import HttpResponse
from django.db import transaction
from django.utils import timezone
from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import apply_tenant_filter, assign_tenant_id
from apps.interference.models import (
    Interference, INTERFERENCE_STATUS_CHOICES, INTERFERENCE_TRANSITIONS,
    INTERFERENCE_LOCKED_FIELDS,
)
from apps.evidence.services import record_evidence_event
from apps.evidence.models import EvidenceEvent, EvidenceAttachment
from apps.logs.models import AuditLog
import logging
from datetime import datetime, timedelta
import json
import hashlib
import zipfile
from io import BytesIO

logger = logging.getLogger(__name__)


def _parse_int(value, name, min_value=None, max_value=None):
    """通用整数参数解析与校验，返回 (result, error)。

    非法输入返回 (None, 'xxx 必须是整数')，通过校验返回 (int, None)。
    与 checksheet 模块保持一致，防止 page=abc / page=0 / page_size 过大触发 500。
    """
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None, f'{name} 必须是整数'
    if min_value is not None and result < min_value:
        return None, f'{name} 不能小于 {min_value}'
    if max_value is not None and result > max_value:
        return None, f'{name} 不能大于 {max_value}'
    return result, None


def _build_interference_snapshot(record):
    """构建干扰记录业务快照（用于证据事件 + 证据包）"""
    return {
        'record': {
            'id': record.id,
            'serial_number': record.serial_number,
            'frequency': record.frequency,
            'report_dept': record.report_dept,
            'datetime': record.datetime,
            'coordinates': record.coordinates,
            'interference_type': record.interference_type,
            'phenomenon': record.phenomenon,
            'flight_number': record.flight_number,
            'aircraft_type': record.aircraft_type,
            'is_reported': record.is_reported,
            'status': record.status,
            'submitted_by_id': record.submitted_by_id,
            'submitted_by_name': record.submitted_by_name,
            'submitted_at': record.submitted_at,
            'reviewed_by_id': record.reviewed_by_id,
            'reviewed_by_name': record.reviewed_by_name,
            'reviewed_at': record.reviewed_at,
            'review_comment': record.review_comment,
            'reported_at': record.reported_at,
            'reported_by_id': record.reported_by_id,
            'reported_by_name': record.reported_by_name,
            'report_channel': record.report_channel,
            'report_no': record.report_no,
            'handled_by_id': record.handled_by_id,
            'handled_by_name': record.handled_by_name,
            'handled_at': record.handled_at,
            'closed_by_id': record.closed_by_id,
            'closed_by_name': record.closed_by_name,
            'closed_at': record.closed_at,
            'close_summary': record.close_summary,
            'snapshot_hash': record.snapshot_hash,
            'created_at': record.created_at,
            'created_by_id': record.created_by_id,
            'updated_at': record.updated_at,
        },
    }


def _compute_interference_snapshot_hash(snapshot):
    """计算干扰记录快照哈希"""
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _get_interference_attachment_hashes(tenant_id, record_id):
    """获取干扰记录关联附件哈希清单"""
    atts = EvidenceAttachment.objects.filter(
        tenant_id=tenant_id, module='interference',
        object_type='interference', object_id=str(record_id),
        is_deleted=False,
    )
    return [
        {
            'file_name': a.file_name, 'file_path': a.file_path,
            'sha256': a.file_hash_sha256, 'size': a.file_size,
            'uploaded_by_id': a.uploaded_by_id,
            'uploaded_by_name': a.uploaded_by_name,
            'uploaded_at': a.uploaded_at,
        }
        for a in atts
    ]


def _record_interference_evidence(record, event_type, user, remark=''):
    """写入干扰记录证据事件"""
    tenant_id = getattr(user, 'tenant_id', 'default')
    snapshot = _build_interference_snapshot(record)
    att_hashes = _get_interference_attachment_hashes(tenant_id, record.id)
    actor_name = getattr(user, 'nickname', '') or getattr(user, 'username', '')
    from libs.utils import get_request_real_ip
    record_evidence_event(
        tenant_id=tenant_id,
        module='interference',
        object_type='interference',
        object_id=record.id,
        event_type=event_type,
        actor_user_id=getattr(user, 'id', None),
        actor_username=getattr(user, 'username', ''),
        actor_name=actor_name,
        object_snapshot=snapshot,
        attachment_hashes=att_hashes,
        event_title=f'干扰记录 #{record.serial_number} {event_type}',
        remark=remark,
    )


class InterferenceView(View):
    @auth('interference.interference.view')
    def get(self, request):
        # 基础 QuerySet（租户隔离）
        base_qs = apply_tenant_filter(Interference.objects.all(), request.user)

        # 下拉选项基于租户全部数据，避免筛选后选项变少
        interference_types = list(base_qs.order_by('interference_type')
                                  .values_list('interference_type', flat=True)
                                  .distinct())
        report_depts = list(base_qs.order_by('report_dept')
                               .values_list('report_dept', flat=True)
                               .distinct())

        # 应用筛选条件
        records = base_qs
        frequency = request.GET.get('frequency')
        if frequency:
            records = records.filter(frequency__icontains=frequency)
        report_dept = request.GET.get('report_dept')
        if report_dept:
            records = records.filter(report_dept__icontains=report_dept)
        interference_type = request.GET.get('interference_type')
        if interference_type:
            records = records.filter(interference_type__icontains=interference_type)
        # 证据闭环第三阶段：新增 status 筛选
        status = request.GET.get('status')
        if status:
            records = records.filter(status=status)
        # datetime 为 CharField 存 "YYYY-MM-DD HH:MM:SS"，end_date 补 23:59:59 包含整天
        start_date = request.GET.get('start_date')
        if start_date:
            records = records.filter(datetime__gte=start_date)
        end_date = request.GET.get('end_date')
        if end_date:
            records = records.filter(datetime__lte=end_date + ' 23:59:59')

        # 先统计过滤后总数，再分页
        # P1 修复：分页参数类型与范围校验，非法输入返回友好错误而非 500
        page, error = _parse_int(request.GET.get('page', 1), 'page', min_value=1)
        if error:
            return json_response(error=error)
        page_size, error = _parse_int(request.GET.get('page_size', 100), 'page_size', min_value=1, max_value=200)
        if error:
            return json_response(error=error)
        total_count = records.count()
        records = records.select_related('created_by', 'updated_by')
        offset = (page - 1) * page_size
        records = records[offset:offset + page_size]

        return json_response({
            'interference_types': interference_types,
            'report_depts': report_depts,
            'status_options': [{'value': k, 'label': v} for k, v in INTERFERENCE_STATUS_CHOICES],
            'records': [x.to_view() for x in records],
            'total': total_count,
            'page': page,
            'page_size': page_size
        })

    @auth('interference.interference.add|interference.interference.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('frequency', required=False),
            Argument('report_dept', required=False),
            Argument('datetime', required=False),
            Argument('coordinates', required=False),
            Argument('interference_type', required=False),
            Argument('phenomenon', required=False),
            Argument('flight_number', required=False),
            Argument('aircraft_type', required=False),
            Argument('is_reported', required=False)
        ).parse(request.body)
        if error is None:
            # datetime 格式校验（创建和编辑共用）
            if form.datetime:
                try:
                    datetime.strptime(form.datetime, '%Y-%m-%d %H:%M:%S')
                except (ValueError, TypeError):
                    return json_response(error='日期时间格式必须为 YYYY-MM-DD HH:MM:SS')
            if form.id:
                # 编辑：只更新传入的非 None 字段（允许部分字段更新）
                if not request.user.has_perms({'interference.interference.edit'}):
                    return json_response(error='权限拒绝')
                form.updated_at = timezone.now()
                form.updated_by = request.user
                record_id = form.pop('id')
                update_data = {k: v for k, v in form.items() if v is not None}
                qs = apply_tenant_filter(Interference.objects.all(), request.user)
                updated_count = qs.filter(pk=record_id).update(**update_data)
                if updated_count == 0:
                    error = '编辑失败：记录不存在或无权限编辑'
            else:
                # 创建：校验必填字段
                if not request.user.has_perms({'interference.interference.add'}):
                    return json_response(error='权限拒绝')
                required = {
                    'frequency': '频率', 'report_dept': '汇报科室',
                    'datetime': '日期时间', 'coordinates': '坐标',
                    'interference_type': '干扰类型', 'phenomenon': '现象',
                    'is_reported': '是否上报'
                }
                for field, label in required.items():
                    if not form.get(field):
                        return json_response(error=f'请输入{label}')
                form.pop('id', None)
                form.created_by = request.user
                assign_tenant_id(form, request.user)
                create_data = {k: v for k, v in form.items() if v is not None}
                Interference.objects.create(**create_data)
        return json_response(error=error)

    @auth('interference.interference.del')
    def delete(self, request):
        """删除干扰记录（证据闭环第三阶段：仅 draft/voided 可删除；其他状态需先作废）"""
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            # 使用 apply_tenant_filter 防止跨租户删除，超管可删除所有租户记录
            qs = apply_tenant_filter(Interference.objects.all(), request.user)
            record = qs.filter(pk=form.id).first()
            if not record:
                return json_response(error='删除失败：记录不存在或无权限删除')
            # 状态流转功能已暂停：删除不再受 status 限制
            # 保留删除留痕（证据事件后台写入，不影响业务）
            try:
                _record_interference_evidence(record, 'delete', request.user, remark='删除干扰记录')
            except Exception as e:
                logger.error(f'干扰记录删除证据事件写入失败: {e}')
            deleted_count, _ = record.delete()
            if deleted_count == 0:
                error = '删除失败：记录不存在或无权限删除'
        return json_response(error=error)


# ==================== 证据闭环第三阶段：状态流转接口 ====================

# action → 新状态映射（供 InterferenceStateView.post 使用）
_INTERFERENCE_ACTION_STATUS = {
    'submit': 'submitted',
    'review': 'reviewed',
    'reject': 'submitted',  # 复核驳回回到 submitted（再驳回到 draft 由 edit 触发）
    'report': 'reported',
    'handle': 'handled',
    'close': 'closed',
    'void': 'voided',
}
# action → 证据事件类型映射
_INTERFERENCE_EVENT_TYPE = {
    'submit': 'submit', 'review': 'approve', 'reject': 'reject',
    'report': 'other', 'handle': 'other',
    'close': 'close', 'void': 'void',
}


def _set_audit_fields(record, user, now, id_field, name_field, at_field):
    """统一填充「操作人 + 时间」三元组字段"""
    actor_name = getattr(user, 'nickname', '') or getattr(user, 'username', '')
    setattr(record, id_field, getattr(user, 'id', None))
    setattr(record, name_field, actor_name)
    setattr(record, at_field, now)


def _interference_submit(record, user, form, now):
    _set_audit_fields(record, user, now, 'submitted_by_id', 'submitted_by_name', 'submitted_at')


def _interference_review(record, user, form, now):
    _set_audit_fields(record, user, now, 'reviewed_by_id', 'reviewed_by_name', 'reviewed_at')
    record.review_comment = form.review_comment or ''


def _interference_reject(record, user, form, now):
    record.review_comment = form.review_comment or ''


def _interference_report(record, user, form, now):
    _set_audit_fields(record, user, now, 'reported_by_id', 'reported_by_name', 'reported_at')
    record.report_channel = form.report_channel or ''
    record.report_no = form.report_no or ''
    # 兼容旧字段 is_reported
    record.is_reported = '是'


def _interference_handle(record, user, form, now):
    _set_audit_fields(record, user, now, 'handled_by_id', 'handled_by_name', 'handled_at')


def _interference_close(record, user, form, now):
    _set_audit_fields(record, user, now, 'closed_by_id', 'closed_by_name', 'closed_at')
    record.close_summary = form.close_summary or ''


def _interference_void(record, user, form, now):
    _set_audit_fields(record, user, now, 'voided_by_id', 'voided_by_name', 'voided_at')
    record.void_reason = form.void_reason or ''


# action → 专属字段更新处理器（submit 单独处理快照）
_INTERFERENCE_ACTION_APPLIER = {
    'submit': _interference_submit,
    'review': _interference_review,
    'reject': _interference_reject,
    'report': _interference_report,
    'handle': _interference_handle,
    'close': _interference_close,
    'void': _interference_void,
}


def _apply_interference_action(record, action, new_status, user, form, now):
    """根据 action 更新干扰记录的专属字段并完成状态流转

    从 InterferenceStateView.post 抽取，降低主函数圈复杂度。
    submit 动作需在状态流转后重新构建快照以与落库值一致。
    """
    applier = _INTERFERENCE_ACTION_APPLIER.get(action)
    if applier is not None:
        applier(record, user, form, now)

    # submit 需先设置 status 再算快照，保证快照与落库一致
    if action == 'submit':
        record.status = new_status
        snapshot = _build_interference_snapshot(record)
        record.snapshot_hash = _compute_interference_snapshot_hash(snapshot)
    else:
        record.status = new_status

    record.updated_at = now
    record.updated_by = user
    record.save()


def _validate_interference_action(form):
    new_status = _INTERFERENCE_ACTION_STATUS.get(form.action)
    if not new_status:
        return None, f'非法操作类型: {form.action}'
    if form.action == 'close' and not (form.close_summary or '').strip():
        return None, '关闭记录时必须填写关闭总结'
    if form.action == 'void' and not (form.void_reason or '').strip():
        return None, '作废记录时必须填写作废原因'
    return new_status, None


class InterferenceStateView(View):
    """干扰记录状态流转 - 提交/复核/上报/处置/关闭/作废"""

    @auth('interference.interference.view')
    def get(self, request):
        """查询状态流转可选动作"""
        record_id = request.GET.get('id')
        if not record_id:
            return json_response(error='缺少 id 参数')
        record = apply_tenant_filter(
            Interference.objects.all(), request.user
        ).filter(pk=record_id).first()
        if not record:
            return json_response(error='记录不存在或无权限')
        allowed = INTERFERENCE_TRANSITIONS.get(record.status, set())
        status_map = dict(INTERFERENCE_STATUS_CHOICES)
        return json_response({
            'id': record.id,
            'status': record.status,
            'status_text': status_map.get(record.status, record.status),
            'can_edit': record.can_edit(),
            'next_statuses': [
                {'value': s, 'label': status_map.get(s, s)}
                for s in sorted(allowed)
            ],
        })

    @auth('interference.interference.edit')
    def post(self, request):
        """执行状态流转（通过 action 参数区分）

        action: submit/review/reject/report/handle/close/void
        """
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象'),
            Argument('action', help='请输入操作类型'),
            Argument('review_comment', required=False),
            Argument('report_channel', required=False),
            Argument('report_no', required=False),
            Argument('close_summary', required=False),
            Argument('void_reason', required=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        new_status, error = _validate_interference_action(form)
        if error:
            return json_response(error=error)

        user = request.user
        now = timezone.now()

        try:
            with transaction.atomic():
                record = apply_tenant_filter(
                    Interference.objects.all(), request.user
                ).select_for_update().filter(pk=form.id).first()
                if not record:
                    return json_response(error='记录不存在或无权限')

                if not record.can_transition_to(new_status):
                    status_map = dict(INTERFERENCE_STATUS_CHOICES)
                    return json_response(
                        error=f'当前状态[{status_map.get(record.status, record.status)}]'
                              f'不能转为[{status_map.get(new_status, new_status)}]')

                # 执行 action 专属字段更新 + 状态流转
                _apply_interference_action(record, form.action, new_status, user, form, now)

                # 写入证据事件
                remark = (form.review_comment or form.close_summary
                         or form.void_reason or form.report_no or '')
                _record_interference_evidence(
                    record, _INTERFERENCE_EVENT_TYPE[form.action], user, remark=remark)

            return json_response({'id': record.id, 'status': record.status})

        except Exception as e:
            logger.error(f'干扰记录状态流转失败: {e}', exc_info=True)
            return json_response(error=str(e))


# ==================== 证据闭环第三阶段：证据包导出 ====================

class InterferenceEvidencePackageView(View):
    """干扰记录证据包导出 - 包含业务快照/证据事件/审计日志/附件哈希清单"""

    @auth('interference.interference.view')
    def get(self, request):
        record_id = request.GET.get('id')
        if not record_id:
            return json_response(error='缺少 id 参数')

        record = apply_tenant_filter(
            Interference.objects.all(), request.user
        ).filter(pk=record_id).first()
        if not record:
            return json_response(error='记录不存在或无权限')

        tenant_id = getattr(request.user, 'tenant_id', 'default')
        snapshot = _build_interference_snapshot(record)

        events = list(EvidenceEvent.objects.filter(
            tenant_id=tenant_id, module='interference',
            object_type='interference', object_id=str(record.id),
        ).order_by('id'))
        events_data = [e.to_dict() for e in events]

        audit_logs = list(AuditLog.objects.filter(
            tenant_id=tenant_id, target_type='interference',
            target_id=str(record.id),
        ).order_by('id'))
        if not audit_logs:
            audit_logs = list(AuditLog.objects.filter(
                tenant_id=tenant_id, target_type='interference',
            ).order_by('id'))
        audit_data = [l.to_dict() for l in audit_logs]

        att_hashes = _get_interference_attachment_hashes(tenant_id, record.id)

        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('object_snapshot.json', json.dumps(snapshot, ensure_ascii=False, indent=2))
            zf.writestr('evidence_events.json', json.dumps(events_data, ensure_ascii=False, indent=2))
            zf.writestr('audit_logs.json', json.dumps(audit_data, ensure_ascii=False, indent=2))
            zf.writestr('hashes.json', json.dumps({
                'module': 'interference', 'object_id': record.id,
                'serial_number': record.serial_number,
                'status': record.status,
                'snapshot_hash': record.snapshot_hash,
                'attachments': att_hashes,
                'events_count': len(events_data),
                'generated_at': timezone.now(),
            }, ensure_ascii=False, indent=2))
            zf.writestr('verify.txt',
                        '本证据包包含干扰记录业务快照JSON、证据事件JSON、审计日志JSON、附件哈希清单。\n'
                        '校验方式：重新计算 object_snapshot.json 的 SHA256，与 hashes.json 中 snapshot_hash 比对。\n'
                        '证据事件哈希链可通过 evidence_events.json 中的 prev_hash/event_hash 校验连续性。\n')

        buf.seek(0)
        resp = HttpResponse(buf.getvalue(), content_type='application/zip')
        resp['Content-Disposition'] = f'attachment; filename="evidence_interference_{record.id}.zip"'
        return resp


class InterferenceStatisticsView(View):
    @auth('interference.statistics.view')
    def get(self, request):
        logger.info('[InterferenceStatistics] 开始获取统计数据')
        try:
            records = apply_tenant_filter(Interference.objects.all(), request.user)

            # 获取时间范围参数
            start_date_str = request.GET.get('start_date')
            end_date_str = request.GET.get('end_date')

            if start_date_str and end_date_str:
                start_date = start_date_str
                end_date = end_date_str + ' 23:59:59'
                filtered_records = records.filter(datetime__gte=start_date, datetime__lte=end_date)
            else:
                now = timezone.now()
                year_start = now.strftime('%Y-01-01')
                year_end = now.strftime('%Y-12-31 23:59:59')
                filtered_records = records.filter(datetime__gte=year_start, datetime__lte=year_end)

            logger.info(f'[InterferenceStatistics] 过滤后记录数: {filtered_records.count()}')

            # 按日期前缀聚合：datetime 为 CharField 存 "YYYY-MM-DD HH:MM:SS"，
            # 用 Substr 截取前 10 位作为日期，避免同一天不同时间产生重复日期行
            from django.db.models import Count
            from django.db.models.functions import Substr

            annotated = filtered_records.annotate(date=Substr('datetime', 1, 10))

            # 按日期、频率统计
            freq_stats = annotated.values('date', 'frequency').annotate(
                count=Count('id')
            ).order_by('date', 'frequency')

            # 按日期、类型统计
            type_stats = annotated.values('date', 'interference_type').annotate(
                count=Count('id')
            ).order_by('date', 'interference_type')

            total_count = filtered_records.count()

            freq_trend = []
            type_trend = []
            seen_freq = set()
            seen_type = set()

            for stat in freq_stats:
                date_str = stat['date'] or ''
                freq_trend.append({
                    'date': date_str,
                    'frequency': stat['frequency'],
                    'count': stat['count']
                })
                seen_freq.add(stat['frequency'])

            for stat in type_stats:
                date_str = stat['date'] or ''
                type_trend.append({
                    'date': date_str,
                    'type': stat['interference_type'],
                    'count': stat['count']
                })
                seen_type.add(stat['interference_type'])

            logger.info(f'[InterferenceStatistics] 频率趋势: {len(freq_trend)} 条, 类型趋势: {len(type_trend)} 条, 总计: {total_count}')
            return json_response({
                'frequency_stats': freq_trend,
                'type_stats': type_trend,
                'total_count': total_count,
                'month_count': total_count
            })
        except Exception as e:
            logger.error(f'[InterferenceStatistics] 错误: {e}')
            import traceback
            logger.error(traceback.format_exc())
            return json_response(error=str(e))
