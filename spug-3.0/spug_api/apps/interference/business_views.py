# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""干扰管理双业务类型视图：地面无线电通信异常/干扰、空中干扰。

职责边界：
- 旧 Interference 接口（/api/interference/ 根路径系列，views.py）原样保留，
  服务于历史数据，不做任何改动；
- 本文件只提供两类新业务模型的增量接口（CRUD/附件/导出配套）与统一汇总统计。

设计约定：
- 两类业务使用独立模型/数据表，附件通过不同 object_type 隔离，防止跨业务串联；
- 沿用 interference.interference.view/add/edit/del 权限与
  interference.statistics.view 统计权限，前后端编码一致；
- 列表/详情/编辑/删除/附件查询全部经过 apply_tenant_filter 租户隔离；
- 纯记录型台账，无状态流转：创建必填日期时间/航班号/现象，
  处置方式与原因分析为普通选填字段，可随时编辑补充；
- 告警高度与持续时间保存原始录入数值并在接口中返回带单位文本，不做数值换算。
"""
import logging
import json
from datetime import datetime

from django.db import transaction
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.views.generic import View

from libs import json_response, JsonParser, Argument, auth
from libs.idempotency import check_recent_duplicate
from libs.pagination import paginate
from libs.tenant_utils import apply_tenant_filter

from apps.evidence.attachment_service import (
    AttachmentService, PREVIEWABLE_EXTENSIONS,
)
from apps.evidence.models import EvidenceAttachment
from apps.logs.audit import record_audit_event

from apps.interference.models import (
    BridgeInterferenceRecord, AirInterferenceRecord, Interference,
    ALTITUDE_UNIT_CHOICES, DURATION_UNIT_CHOICES,
)
from apps.interference.views import InterferenceAttachmentConfig

logger = logging.getLogger(__name__)

# 两类业务共用一套附件约束（与旧干扰模块一致），通过 object_type 区分归属
ATTACHMENT_MODULE = 'interference'
BRIDGE_OBJECT_TYPE = 'bridge_interference'
AIR_OBJECT_TYPE = 'air_interference'


# 公共 JsonParser 参数：两类业务共同字段
COMMON_FORM_ARGS = (
    Argument('id', type=int, required=False),
    Argument('datetime', required=False),
    Argument('flight_number', required=False),
    Argument('aircraft_type', required=False),
    Argument('phenomenon', required=False),
    Argument('attachment_temp_id', required=False),
)


def _validate_datetime_str(value):
    """校验日期时间格式（到分钟即可，兼容到秒），非法返回错误信息。"""
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            datetime.strptime(value, fmt)
            return None
        except (ValueError, TypeError):
            continue
    return '日期时间格式必须为 YYYY-MM-DD HH:MM（如需可精确到秒）'


def _validate_positive_number(values, field, label):
    """数值字段（若提供）必须为正数，返回错误信息或 None。"""
    value = values.get(field)
    if value is None:
        return None
    try:
        if float(value) <= 0:
            return f'{label}必须大于0'
    except (TypeError, ValueError):
        return f'{label}必须为数字'
    return None


class _BusinessInterferenceView(View):
    """地面/空中两类业务记录 CRUD 公共实现，子类声明业务差异。"""

    model = None
    business_label = ''
    object_type = ''
    required_fields = {}       # 创建必填：field -> 中文名
    form_args = ()             # 业务差异字段的 JsonParser 参数
    clearable_fields = ()      # 请求体中显式携带空值时表示清除（置 NULL）的字段

    def _provided_keys(self, request):
        """解析请求体中显式出现的键，用于区分「未提供」与「显式清除」。"""
        try:
            raw = json.loads(request.body)
        except (ValueError, TypeError):
            return set()
        return set(raw.keys()) if isinstance(raw, dict) else set()

    def _base_qs(self, request):
        return apply_tenant_filter(
            self.model.objects.filter(is_deleted=False), request.user)

    def _duplicate_filters(self, values):
        return {
            'datetime': values.get('datetime'),
            'flight_number': values.get('flight_number'),
        }

    def _target_name(self, record):
        return f'{self.business_label}-{record.flight_number or record.id}'

    def _validate_business(self, values):
        """业务差异校验（子类覆盖），返回错误信息或 None。"""
        return None

    def _attachment_counts(self, request, record_ids):
        """批量统计附件数量，避免列表页 N+1 查询。"""
        if not record_ids:
            return {}
        qs = apply_tenant_filter(
            EvidenceAttachment.objects.filter(
                module=ATTACHMENT_MODULE,
                object_type=self.object_type,
                object_id__in=[str(i) for i in record_ids],
                is_deleted=False,
            ),
            request.user,
        )
        rows = qs.values('object_id').annotate(count=Count('id'))
        return {row['object_id']: row['count'] for row in rows}

    # ---------------- 列表 ----------------

    @auth('interference.interference.view')
    def get(self, request):
        qs = self._base_qs(request)
        flight_number = request.GET.get('flight_number')
        if flight_number:
            qs = qs.filter(flight_number__icontains=flight_number)
        start_date = request.GET.get('start_date')
        if start_date:
            qs = qs.filter(datetime__gte=start_date)
        end_date = request.GET.get('end_date')
        if end_date:
            qs = qs.filter(datetime__lte=end_date + ' 23:59:59')

        page, page_size = paginate(request, default_page_size=100)
        total = qs.count()
        offset = (page - 1) * page_size
        records = list(qs[offset:offset + page_size])
        att_counts = self._attachment_counts(request, [r.id for r in records])
        items = []
        for r in records:
            view = r.to_view()
            view['attachment_count'] = att_counts.get(str(r.id), 0)
            items.append(view)
        return json_response({
            'records': items,
            'total': total,
            'page': page,
            'page_size': page_size,
        })

    # ---------------- 创建 / 编辑 ----------------

    @auth('interference.interference.add|interference.interference.edit')
    def post(self, request):
        form, error = JsonParser(*(COMMON_FORM_ARGS + self.form_args)).parse(request.body)
        if error is not None:
            return json_response(error=error)

        record_id = form.pop('id', None)
        attachment_temp_id = form.pop('attachment_temp_id', None)

        if record_id:
            return self._handle_edit(request, form, record_id)
        return self._handle_create(request, form, attachment_temp_id)

    def _handle_create(self, request, form, attachment_temp_id):
        if not request.user.has_perms({'interference.interference.add'}):
            return json_response(error='权限拒绝')
        provided = self._provided_keys(request)
        values = {k: v for k, v in form.items() if v is not None}
        # 可清除字段：请求体显式携带空串时按清除处理（置 NULL）
        for key in self.clearable_fields:
            if key in provided and values.get(key) == '':
                values[key] = None
        for field, label in self.required_fields.items():
            if not values.get(field):
                return json_response(error=f'请输入{label}')
        if values.get('datetime'):
            error = _validate_datetime_str(values['datetime'])
            if error:
                return json_response(error=error)
        error = self._validate_business(values)
        if error:
            return json_response(error=error)
        values['created_by'] = request.user
        with transaction.atomic():
            if check_recent_duplicate(self.model, self._duplicate_filters(values)):
                return json_response(error='检测到重复提交，请勿重复操作')
            record = self.model.objects.create(**values)

        # 新建阶段上传的临时附件关联到新记录
        if attachment_temp_id:
            EvidenceAttachment.objects.filter(
                tenant_id=getattr(request.user, 'tenant_id', 'default'),
                module=ATTACHMENT_MODULE,
                object_type=self.object_type,
                object_id=str(attachment_temp_id),
                is_deleted=False,
            ).update(object_id=str(record.id))

        record_audit_event(
            request, 'create', 'interference',
            target_id=str(record.id),
            target_name=self._target_name(record),
            detail={'record_type': self.object_type, 'id': record.id},
        )
        return json_response()

    def _handle_edit(self, request, form, record_id):
        if not request.user.has_perms({'interference.interference.edit'}):
            return json_response(error='权限拒绝')
        provided = self._provided_keys(request)
        with transaction.atomic():
            record = self._base_qs(request).select_for_update().filter(pk=record_id).first()
            if not record:
                return json_response(error='编辑失败：记录不存在或无权限编辑')
            update_data = {k: v for k, v in form.items() if v is not None}
            # 可清除字段：仅当请求体显式携带该键且值为空时才清除，避免局部编辑误清空
            for key in self.clearable_fields:
                if key in provided and form.get(key) in (None, ''):
                    update_data[key] = None
            if update_data.get('datetime'):
                error = _validate_datetime_str(update_data['datetime'])
                if error:
                    return json_response(error=error)
            for key, value in update_data.items():
                setattr(record, key, value)
            record.updated_at = timezone.now()
            record.updated_by = request.user
            error = self._validate_business(update_data)
            if error:
                return json_response(error=error)
            record.save(update_fields=list(update_data.keys()) + ['updated_at', 'updated_by'])
        record_audit_event(
            request, 'edit', 'interference',
            target_id=str(record.id),
            target_name=self._target_name(record),
            detail={'record_type': self.object_type, 'fields': list(update_data.keys())},
        )
        return json_response()

    # ---------------- 删除 ----------------

    @auth('interference.interference.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is not None:
            return json_response(error=error)
        with transaction.atomic():
            record = self._base_qs(request).select_for_update().filter(pk=form.id).first()
            if not record:
                return json_response(error='删除失败：记录不存在或无权限删除')
            record.is_deleted = True
            record.deleted_at = timezone.now()
            record.save(update_fields=['is_deleted', 'deleted_at'])
            record_audit_event(
                request, 'delete', 'interference',
                target_id=str(record.id),
                target_name=self._target_name(record),
                detail={'record_type': self.object_type, 'id': record.id},
            )
        return json_response()


class _BusinessAttachmentView(View):
    """地面/空中两类业务附件列表/上传公共实现。

    支持两种 pk 模式：
    - 数字 ID：已保存的业务记录，校验记录存在性（含租户隔离）；
    - 临时 UUID：新建阶段尚未保存的记录，跳过记录校验。
    """

    business_model = None
    object_type = ''

    def _check_record(self, request, pk):
        if pk.isdigit():
            qs = apply_tenant_filter(
                self.business_model.objects.filter(is_deleted=False), request.user)
            return qs.filter(pk=pk).exists()
        return True

    @auth('interference.interference.view')
    def get(self, request, pk):
        if not self._check_record(request, pk):
            return json_response(error=f'{self.business_model._meta.verbose_name}不存在或无权限访问')
        data = AttachmentService.list(request.user, ATTACHMENT_MODULE, self.object_type, pk)
        return json_response(data)

    @auth('interference.interference.add|interference.interference.edit')
    def post(self, request, pk):
        if not self._check_record(request, pk):
            return json_response(error=f'{self.business_model._meta.verbose_name}不存在或无权限访问')
        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的文件')
        att, error = AttachmentService.upload(
            file=file,
            user=request.user,
            module=ATTACHMENT_MODULE,
            object_type=self.object_type,
            object_id=pk,
            config=InterferenceAttachmentConfig,
        )
        if error:
            return json_response(error=error)
        result = att.to_view()
        result['uploaded_by_name'] = request.user.nickname
        result['created_at'] = att.uploaded_at
        result['previewable'] = att.file_ext in PREVIEWABLE_EXTENSIONS
        return json_response(result)


class BridgeInterferenceView(_BusinessInterferenceView):
    """地面无线电通信异常/干扰记录接口。"""

    model = BridgeInterferenceRecord
    business_label = '地面干扰记录'
    object_type = BRIDGE_OBJECT_TYPE
    required_fields = {
        'datetime': '日期时间',
        'phenomenon': '现象',
    }
    form_args = (
        Argument('aircraft_no', required=False),
        Argument('location', required=False),
        Argument('frequency', required=False),
        Argument('remark', required=False),
    )


class AirInterferenceView(_BusinessInterferenceView):
    """空中干扰记录接口。"""

    model = AirInterferenceRecord
    business_label = '空中干扰记录'
    object_type = AIR_OBJECT_TYPE
    clearable_fields = ('alert_altitude', 'duration')
    required_fields = {
        'datetime': '日期时间',
        'phenomenon': '现象',
    }
    form_args = (
        Argument('route', required=False),
        Argument('runway', required=False),
        Argument('approach_procedure', required=False),
        Argument('alert_form', required=False),
        Argument('alert_altitude', required=False),
        Argument('alert_altitude_unit', required=False),
        Argument('alert_segment', required=False),
        Argument('duration', required=False),
        Argument('duration_unit', required=False),
        Argument('handling_method', required=False),
        Argument('cause_analysis', required=False),
    )

    def _validate_business(self, values):
        altitude = values.get('alert_altitude')
        if altitude is not None:
            error = _validate_positive_number(values, 'alert_altitude', '告警高度')
            if error:
                return error
            unit = values.get('alert_altitude_unit', 'm')
            if unit not in dict(ALTITUDE_UNIT_CHOICES):
                return '告警高度单位不合法'
        duration = values.get('duration')
        if duration is not None:
            error = _validate_positive_number(values, 'duration', '持续时间')
            if error:
                return error
            unit = values.get('duration_unit', 'min')
            if unit not in dict(DURATION_UNIT_CHOICES):
                return '持续时间单位不合法'
        return None


class BridgeAttachmentView(_BusinessAttachmentView):
    business_model = BridgeInterferenceRecord
    object_type = BRIDGE_OBJECT_TYPE


class AirAttachmentView(_BusinessAttachmentView):
    business_model = AirInterferenceRecord
    object_type = AIR_OBJECT_TYPE


class InterferenceSummaryView(View):
    """干扰管理统一汇总统计。

    只统计两类记录的共同摘要（记录类型/日期），不混合任何业务明细字段：
    - bridge_count / air_count / total_count：分别统计并给出总量；
    - monthly_trend：按记录类型分列的按日趋势；
    - legacy_count：未分类历史干扰记录数（仅供参考，不参与两类合计）。
    """

    @auth('interference.statistics.view')
    def get(self, request):
        try:
            start_date = request.GET.get('start_date')
            end_date = request.GET.get('end_date')
            if start_date and end_date:
                start_dt = start_date
                end_dt = end_date + ' 23:59:59'
            else:
                now = timezone.now()
                start_dt = now.strftime('%Y-01-01')
                end_dt = now.strftime('%Y-12-31 23:59:59')

            total_count = 0
            summary = {}
            monthly_trend = []
            business_specs = (
                ('bridge', '地面无线电通信异常/干扰', BridgeInterferenceRecord),
                ('air', '空中干扰', AirInterferenceRecord),
            )
            for key, label, model in business_specs:
                qs = apply_tenant_filter(
                    model.objects.filter(is_deleted=False), request.user,
                ).filter(datetime__gte=start_dt, datetime__lte=end_dt)
                count = qs.count()
                total_count += count
                summary[key] = {'label': label, 'count': count}

                annotated = qs.annotate(date=TruncDate('datetime'))
                for row in annotated.values('date').annotate(
                        count=Count('id')).order_by('date'):
                    monthly_trend.append({
                        'date': str(row['date'] or ''),
                        'record_type': key,
                        'record_type_text': label,
                        'count': row['count'],
                    })

            # 历史未分类记录数（旧表，仅供参考）
            legacy_qs = apply_tenant_filter(
                Interference.objects.filter(is_deleted=False), request.user,
            ).filter(datetime__gte=start_dt, datetime__lte=end_dt)

            return json_response({
                'bridge_count': summary['bridge']['count'],
                'air_count': summary['air']['count'],
                'total_count': total_count,
                'legacy_count': legacy_qs.count(),
                'summary': summary,
                'monthly_trend': monthly_trend,
            })
        except Exception:
            logger.exception('[InterferenceSummary] 统计失败')
            return json_response(error='获取统计数据失败，请稍后重试')
