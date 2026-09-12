"""干扰管理统一事件、规律调查、测量和附件接口。"""

import csv
import io
import json
from uuid import UUID
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from django.views.generic import View

from apps.evidence.attachment_service import (
    AttachmentConfig,
    AttachmentService,
    PREVIEWABLE_EXTENSIONS,
)
from apps.evidence.models import EvidenceAttachment
from apps.interference.models import (
    AirInterferenceDetail,
    ALTITUDE_UNIT_CHOICES,
    AFFECTED_SYSTEM_CODE_CHOICES,
    CLASSIFICATION_STATUS_CHOICES,
    DURATION_UNIT_CHOICES,
    GroundInterferenceDetail,
    INTERFERENCE_KIND_CODE_CHOICES,
    INVESTIGATION_STATUS_CHOICES,
    InvestigationEvent,
    InterferenceEvent,
    InterferenceInvestigation,
    SCENE_CODE_CHOICES,
    SOURCE_TYPE_CODE_CHOICES,
    SpectrumMeasurement,
)
from apps.logs.audit import record_audit_event
from libs import Argument, JsonParser, auth, json_response
from libs.idempotency import check_recent_duplicate
from libs.pagination import paginate
from libs.tenant_utils import apply_tenant_filter


EVENT_VIEW_PERMISSION = 'interference.interference.view'
EVENT_ADD_PERMISSION = 'interference.interference.add'
EVENT_EDIT_PERMISSION = 'interference.interference.edit'
EVENT_DELETE_PERMISSION = 'interference.interference.del'
INVESTIGATION_VIEW_PERMISSION = 'interference.investigation.view'
INVESTIGATION_ADD_PERMISSION = 'interference.investigation.add'
INVESTIGATION_EDIT_PERMISSION = 'interference.investigation.edit'
INVESTIGATION_DELETE_PERMISSION = 'interference.investigation.del'
MEASUREMENT_VIEW_PERMISSION = 'interference.measurement.view'
MEASUREMENT_ADD_PERMISSION = 'interference.measurement.add'
MEASUREMENT_EDIT_PERMISSION = 'interference.measurement.edit'
MEASUREMENT_DELETE_PERMISSION = 'interference.measurement.del'

ATTACHMENT_MODULE = 'interference'
EVENT_OBJECT_TYPE = 'interference_event'
INVESTIGATION_OBJECT_TYPE = 'interference_investigation'
MEASUREMENT_OBJECT_TYPE = 'interference_measurement'
ATTACHMENT_OBJECT_TYPES = (
    EVENT_OBJECT_TYPE,
    INVESTIGATION_OBJECT_TYPE,
    MEASUREMENT_OBJECT_TYPE,
)
ATTACHMENT_FORBIDDEN_ERROR = '附件不存在或无权限访问'

# Attachments inherit the permissions of their owning business object.  There
# are no separate attachment permissions in the interference role matrix, so
# upload/delete deliberately accept the corresponding object write permissions.
ATTACHMENT_PERMISSION_MAP = {
    EVENT_OBJECT_TYPE: {
        'view': (EVENT_VIEW_PERMISSION,),
        'upload': (EVENT_ADD_PERMISSION, EVENT_EDIT_PERMISSION),
        'delete': (EVENT_EDIT_PERMISSION, EVENT_DELETE_PERMISSION),
    },
    INVESTIGATION_OBJECT_TYPE: {
        'view': (INVESTIGATION_VIEW_PERMISSION,),
        'upload': (INVESTIGATION_ADD_PERMISSION, INVESTIGATION_EDIT_PERMISSION),
        'delete': (INVESTIGATION_EDIT_PERMISSION, INVESTIGATION_DELETE_PERMISSION),
    },
    MEASUREMENT_OBJECT_TYPE: {
        'view': (MEASUREMENT_VIEW_PERMISSION,),
        'upload': (MEASUREMENT_ADD_PERMISSION, MEASUREMENT_EDIT_PERMISSION),
        'delete': (MEASUREMENT_EDIT_PERMISSION, MEASUREMENT_DELETE_PERMISSION),
    },
}

InterferenceAttachmentConfig = AttachmentConfig(
    allowed_extensions=(
        '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
        '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.zip', '.rar', '.7z',
    ),
    max_size_mb=50,
)


def _body(request):
    """解析 JSON 请求体；空请求统一返回空对象。"""
    if not request.body:
        return {}
    try:
        value = json.loads(request.body.decode('utf-8'))
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _parse_datetime(value, field='datetime'):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace('T', ' ')
        parsed = None
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                raise ValueError(f'{field}格式必须为 YYYY-MM-DD HH:MM[:SS]')
    else:
        raise ValueError(f'请输入{field}')
    if settings.USE_TZ and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    elif not settings.USE_TZ and timezone.is_aware(parsed):
        parsed = timezone.make_naive(parsed, timezone.get_current_timezone())
    return parsed


def _parse_optional_datetime(value, field):
    if value in (None, ''):
        return None
    return _parse_datetime(value, field)


def _parse_decimal(value, field, positive=False):
    if value in (None, ''):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{field}必须为数字')
    if positive and result <= 0:
        raise ValueError(f'{field}必须大于0')
    return result


def _choice_error(value, choices, field):
    if value not in dict(choices):
        return f'{field}值无效'
    return None


def _event_queryset(user):
    return apply_tenant_filter(
        InterferenceEvent.objects.filter(is_deleted=False), user)


def _investigation_queryset(user):
    return apply_tenant_filter(
        InterferenceInvestigation.objects.filter(is_deleted=False), user)


def _measurement_queryset(user):
    return apply_tenant_filter(
        SpectrumMeasurement.objects.filter(
            is_deleted=False, investigation__is_deleted=False), user)


def _has_attachment_permission(user, object_type, action):
    permissions = ATTACHMENT_PERMISSION_MAP.get(object_type, {}).get(action, ())
    return bool(permissions) and user.has_perms(set(permissions))


def _is_temporary_object_id(object_id):
    """Recognise the temporary UUIDs used while a record is being created."""
    value = str(object_id or '').strip()
    if not value:
        return False
    if value.lower().startswith('temp-'):
        return True
    try:
        UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _filtered_event_queryset(request, user):
    """Apply the event list filters without applying pagination.

    Keeping this in one place makes list and CSV export use exactly the same
    tenant, detail, date and investigation filtering semantics.
    """
    qs = _event_queryset(user)
    for query_key in (
        'scene_code', 'classification_status', 'interference_kind_code',
        'affected_system_code', 'source_type_code',
    ):
        value = request.GET.get(query_key)
        if value:
            qs = qs.filter(**{query_key: value})
    for field in ('flight_number', 'aircraft_no'):
        value = request.GET.get(field)
        if value:
            qs = qs.filter(**{f'{field}__icontains': value})

    start = request.GET.get('datetime_start') or request.GET.get('start_date')
    end = request.GET.get('datetime_end') or request.GET.get('end_date')
    try:
        if start:
            qs = qs.filter(datetime__gte=_parse_datetime(start, '开始时间'))
        if end:
            end_value = _parse_datetime(end, '结束时间')
            if len(str(end)) == 10:
                end_value += timedelta(days=1)
            qs = qs.filter(datetime__lt=end_value)
    except ValueError as exc:
        return None, str(exc)

    frequency = request.GET.get('frequency')
    if frequency:
        qs = qs.filter(
            Q(ground_detail__frequency__icontains=frequency,
              ground_detail__is_deleted=False) |
            Q(air_detail__alert_frequency__icontains=frequency,
              air_detail__is_deleted=False)
        )
    location = request.GET.get('location')
    if location:
        # Air details have route/segment rather than a separate location field.
        qs = qs.filter(
            Q(ground_detail__location__icontains=location,
              ground_detail__is_deleted=False) |
            Q(air_detail__route__icontains=location,
              air_detail__is_deleted=False) |
            Q(air_detail__alert_segment__icontains=location,
              air_detail__is_deleted=False)
        )
    investigation_id = request.GET.get('investigation_id')
    if investigation_id:
        try:
            qs = qs.filter(
                investigation_links__investigation_id=int(investigation_id),
                investigation_links__is_deleted=False,
                investigation_links__investigation__is_deleted=False,
            )
        except (TypeError, ValueError):
            return None, 'investigation_id 必须为整数'
    return qs.distinct(), None


def _event_payload(data, existing=None):
    """清洗公共字段和明细，返回 ``(values, ground, air, error)``。"""
    if not isinstance(data, dict):
        return None, None, None, '请求体必须是 JSON 对象'
    values = {}
    public_fields = (
        'datetime', 'scene_code', 'classification_status',
        'interference_kind_code', 'affected_system_code', 'source_type_code',
        'flight_number', 'aircraft_no', 'aircraft_type', 'phenomenon',
        'initial_assessment', 'remark',
    )
    for field in public_fields:
        if field in data:
            values[field] = '' if data[field] is None and field not in ('datetime',) else data[field]
    if existing is not None:
        values.setdefault('scene_code', existing.scene_code)
        values.setdefault('classification_status', existing.classification_status)
        values.setdefault('interference_kind_code', existing.interference_kind_code)
        values.setdefault('affected_system_code', existing.affected_system_code)
        values.setdefault('source_type_code', existing.source_type_code)
    else:
        values.setdefault('scene_code', 'unknown')
        values.setdefault('classification_status', 'pending')
        values.setdefault('interference_kind_code', 'unknown')
        values.setdefault('affected_system_code', 'other')
        values.setdefault('source_type_code', 'unknown')
    if 'datetime' in values:
        try:
            values['datetime'] = _parse_datetime(values['datetime'])
        except ValueError as exc:
            return None, None, None, str(exc)
    elif existing is None:
        return None, None, None, '请输入发生时间'
    for field, choices, label in (
        ('scene_code', SCENE_CODE_CHOICES, '发生场景'),
        ('classification_status', CLASSIFICATION_STATUS_CHOICES, '分类状态'),
        ('interference_kind_code', INTERFERENCE_KIND_CODE_CHOICES, '具体干扰类型'),
        ('affected_system_code', AFFECTED_SYSTEM_CODE_CHOICES, '受影响系统'),
        ('source_type_code', SOURCE_TYPE_CODE_CHOICES, '疑似干扰源'),
    ):
        error = _choice_error(values.get(field), choices, label)
        if error:
            return None, None, None, error

    ground = data.get('ground_detail') if 'ground_detail' in data else None
    air = data.get('air_detail') if 'air_detail' in data else None
    if 'ground_detail' not in data:
        legacy_ground = {k: data[k] for k in (
            'location', 'frequency', 'ground_equipment',
        ) if k in data}
        if legacy_ground:
            ground = legacy_ground
    if 'air_detail' not in data:
        legacy_air = {k: data[k] for k in (
            'route', 'alert_frequency', 'alert_altitude', 'alert_altitude_unit',
            'alert_segment', 'duration', 'duration_unit',
        ) if k in data}
        if legacy_air:
            air = legacy_air
    if ground is not None and not isinstance(ground, dict):
        return None, None, None, '地面明细必须是对象'
    if air is not None and not isinstance(air, dict):
        return None, None, None, '空中明细必须是对象'
    scene = values['scene_code']
    if scene == 'ground' and air is not None:
        return None, None, None, '地面事件不能包含空中明细'
    if scene == 'air' and ground is not None:
        return None, None, None, '空中事件不能包含地面明细'
    if scene == 'unknown' and (ground is not None or air is not None):
        return None, None, None, '未知场景暂不能填写专属明细'
    if values['classification_status'] == 'confirmed':
        if scene == 'ground' and ground is None and existing is None:
            return None, None, None, '已确认的地面事件必须填写地面明细'
        if scene == 'air' and air is None and existing is None:
            return None, None, None, '已确认的空中事件必须填写空中明细'
        if scene == 'cross' and ground is None and air is None and existing is None:
            return None, None, None, '已确认的跨场景事件至少需要一类明细'
    return values, ground, air, None


def _normalise_ground(data):
    data = data or {}
    allowed = ('location', 'frequency', 'ground_equipment', 'remark')
    return {field: data.get(field, '') or '' for field in allowed}


def _normalise_air(data):
    data = data or {}
    try:
        altitude = _parse_decimal(data.get('alert_altitude'), '告警高度', positive=True)
        duration = _parse_decimal(data.get('duration'), '持续时间', positive=True)
    except ValueError as exc:
        raise ValueError(str(exc))
    altitude_unit = data.get('alert_altitude_unit', 'm') or 'm'
    duration_unit = data.get('duration_unit', 'min') or 'min'
    if altitude_unit not in dict(ALTITUDE_UNIT_CHOICES):
        raise ValueError('告警高度单位值无效')
    if duration_unit not in dict(DURATION_UNIT_CHOICES):
        raise ValueError('持续时间单位值无效')
    return {
        'route': data.get('route', '') or '',
        'alert_frequency': data.get('alert_frequency', '') or '',
        'alert_altitude': altitude,
        'alert_altitude_unit': altitude_unit,
        'alert_segment': data.get('alert_segment', '') or '',
        'duration': duration,
        'duration_unit': duration_unit,
    }


def _set_detail_tenant(detail, user):
    tenant_id = getattr(user, 'tenant_id', 'admin')
    if isinstance(detail, dict):
        detail['tenant_id'] = tenant_id
    else:
        detail.tenant_id = tenant_id
    return detail


def _sync_event_details(event, ground_data, air_data, data, user, creating=False):
    """按请求中出现的明细键创建、更新或软删除明细。"""
    if 'ground_detail' in data or ground_data is not None:
        if ground_data is None:
            GroundInterferenceDetail.objects.filter(
                event_id=event.id, is_deleted=False).update(
                    is_deleted=True, deleted_at=timezone.now())
        else:
            values = _normalise_ground(ground_data)
            detail = GroundInterferenceDetail.objects.all_with_deleted().filter(
                event_id=event.id).first()
            if detail:
                for key, value in values.items():
                    setattr(detail, key, value)
                detail.is_deleted = False
                detail.deleted_at = None
                _set_detail_tenant(detail, user)
                detail.save()
            else:
                GroundInterferenceDetail.objects.create(
                    event=event, **_set_detail_tenant(values, user))
    if 'air_detail' in data or air_data is not None:
        if air_data is None:
            AirInterferenceDetail.objects.filter(
                event_id=event.id, is_deleted=False).update(
                    is_deleted=True, deleted_at=timezone.now())
        else:
            values = _normalise_air(air_data)
            detail = AirInterferenceDetail.objects.all_with_deleted().filter(
                event_id=event.id).first()
            if detail:
                for key, value in values.items():
                    setattr(detail, key, value)
                detail.is_deleted = False
                detail.deleted_at = None
                _set_detail_tenant(detail, user)
                detail.save()
            else:
                AirInterferenceDetail.objects.create(
                    event=event, **_set_detail_tenant(values, user))
    # Changing a classified scene must not leave an incompatible stale detail.
    if event.scene_code == 'ground':
        AirInterferenceDetail.objects.filter(event_id=event.id, is_deleted=False).update(
            is_deleted=True, deleted_at=timezone.now())
    elif event.scene_code == 'air':
        GroundInterferenceDetail.objects.filter(event_id=event.id, is_deleted=False).update(
            is_deleted=True, deleted_at=timezone.now())
    elif event.scene_code == 'unknown':
        GroundInterferenceDetail.objects.filter(event_id=event.id, is_deleted=False).update(
            is_deleted=True, deleted_at=timezone.now())
        AirInterferenceDetail.objects.filter(event_id=event.id, is_deleted=False).update(
            is_deleted=True, deleted_at=timezone.now())


def _validate_detail_state(event):
    ground_exists = GroundInterferenceDetail.objects.filter(
        event_id=event.id, is_deleted=False).exists()
    air_exists = AirInterferenceDetail.objects.filter(
        event_id=event.id, is_deleted=False).exists()
    if event.scene_code == 'ground' and air_exists:
        return '地面事件不能存在空中明细'
    if event.scene_code == 'air' and ground_exists:
        return '空中事件不能存在地面明细'
    if event.classification_status == 'confirmed' and event.scene_code == 'ground' and not ground_exists:
        return '已确认的地面事件必须存在地面明细'
    if event.classification_status == 'confirmed' and event.scene_code == 'air' and not air_exists:
        return '已确认的空中事件必须存在空中明细'
    if event.scene_code == 'unknown' and (ground_exists or air_exists):
        return '未知场景事件不能存在专属明细'
    if event.classification_status == 'confirmed' and event.scene_code == 'cross':
        if not ground_exists and not air_exists:
            return '已确认的跨场景事件至少需要一类明细'
    return None


class EventListView(View):
    @auth(EVENT_VIEW_PERMISSION)
    def get(self, request):
        qs, error = _filtered_event_queryset(request, request.user)
        if error:
            return json_response(error=error)
        page, page_size = paginate(request, default_page_size=100)
        total = qs.count()
        records = qs[(page - 1) * page_size:page * page_size]
        items = []
        for event in records:
            item = event.to_view(include_details=False)
            links = InvestigationEvent.objects.filter(
                event_id=event.id, is_deleted=False,
                investigation__is_deleted=False).select_related('investigation')
            item['investigation_ids'] = [x.investigation_id for x in links]
            item['investigation_status'] = next(
                (x.investigation.status for x in links), None)
            items.append(item)
        return json_response({
            'records': items,
            'total': total,
            'page': page,
            'page_size': page_size,
            'options': {
                'scene_code': [{'value': x, 'label': y} for x, y in SCENE_CODE_CHOICES],
                'classification_status': [
                    {'value': x, 'label': y} for x, y in CLASSIFICATION_STATUS_CHOICES],
                'interference_kind_code': [
                    {'value': x, 'label': y} for x, y in INTERFERENCE_KIND_CODE_CHOICES],
            },
        })

    @auth(EVENT_ADD_PERMISSION + '|' + EVENT_EDIT_PERMISSION)
    def post(self, request):
        data = _body(request)
        if data is None:
            return json_response(error='请求体必须是 JSON 对象')
        record_id = data.get('id')
        existing = None
        if record_id:
            if not request.user.has_perms({EVENT_EDIT_PERMISSION}):
                return json_response(error='权限拒绝')
            try:
                existing = _event_queryset(request.user).select_for_update().filter(
                    pk=int(record_id)).first()
            except (TypeError, ValueError):
                existing = None
            if not existing:
                return json_response(error='事件不存在或无权限编辑')
        elif not request.user.has_perms({EVENT_ADD_PERMISSION}):
            return json_response(error='权限拒绝')
        values, ground, air, error = _event_payload(data, existing)
        if error:
            return json_response(error=error)
        try:
            with transaction.atomic():
                if existing:
                    before = existing.to_view(include_details=False)
                    for key, value in values.items():
                        setattr(existing, key, value)
                    existing.updated_by = request.user
                    existing.updated_at = timezone.now()
                    existing.save()
                    _sync_event_details(existing, ground, air, data, request.user)
                    error = _validate_detail_state(existing)
                    if error:
                        raise ValueError(error)
                    record_audit_event(
                        request, 'update', 'interference_event', str(existing.id),
                        existing.phenomenon[:100], {'id': existing.id},
                        before_value=before,
                        after_value=existing.to_view(include_details=False),
                    )
                    result = existing
                else:
                    if check_recent_duplicate(InterferenceEvent, {
                        'tenant_id': getattr(request.user, 'tenant_id', 'admin'),
                        'datetime': values.get('datetime'),
                        'scene_code': values.get('scene_code'),
                        'flight_number': values.get('flight_number', ''),
                    }):
                        return json_response(error='检测到重复提交，请勿重复操作')
                    values['created_by'] = request.user
                    values['tenant_id'] = getattr(request.user, 'tenant_id', 'admin')
                    result = InterferenceEvent.objects.create(**values)
                    _sync_event_details(result, ground, air, data, request.user, creating=True)
                    error = _validate_detail_state(result)
                    if error:
                        raise ValueError(error)
                    record_audit_event(
                        request, 'create', 'interference_event', str(result.id),
                        result.phenomenon[:100], {'id': result.id},
                    )
        except (ValueError, IntegrityError) as exc:
            return json_response(error=str(exc) or '保存失败')
        return json_response(result.to_view())


class EventDetailView(View):
    @auth(EVENT_VIEW_PERMISSION)
    def get(self, request, pk):
        event = _event_queryset(request.user).filter(pk=pk).first()
        if not event:
            return json_response(error='事件不存在或无权限访问')
        return json_response(event.to_view())

    @auth(EVENT_EDIT_PERMISSION)
    def put(self, request, pk):
        return self._update(request, pk)

    @auth(EVENT_EDIT_PERMISSION)
    def patch(self, request, pk):
        return self._update(request, pk)

    def _update(self, request, pk):
        data = _body(request) or {}
        data['id'] = pk
        # Reuse the single create/edit implementation so validation is identical.
        request._body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        request._body = bytes(request._body)
        return EventListView().post(request)

    @auth(EVENT_DELETE_PERMISSION)
    def delete(self, request, pk):
        with transaction.atomic():
            event = _event_queryset(request.user).select_for_update().filter(pk=pk).first()
            if not event:
                return json_response(error='事件不存在或无权限删除')
            now = timezone.now()
            event.is_deleted = True
            event.deleted_at = now
            event.updated_by = request.user
            event.updated_at = now
            event.save(update_fields=['is_deleted', 'deleted_at', 'updated_by', 'updated_at'])
            GroundInterferenceDetail.objects.filter(event_id=event.id).update(
                is_deleted=True, deleted_at=now)
            AirInterferenceDetail.objects.filter(event_id=event.id).update(
                is_deleted=True, deleted_at=now)
            InvestigationEvent.objects.filter(event_id=event.id).update(
                is_deleted=True, deleted_at=now)
            AttachmentService.soft_delete_by_object(
                request.user, ATTACHMENT_MODULE, EVENT_OBJECT_TYPE, event.id,
                reason='干扰事件删除', delete_file=True,
            )
            record_audit_event(
                request, 'delete', 'interference_event', str(event.id),
                event.phenomenon[:100], {'id': event.id},
            )
        return json_response()


class InvestigationListView(View):
    @auth(INVESTIGATION_VIEW_PERMISSION + '|' + EVENT_VIEW_PERMISSION)
    def get(self, request):
        qs = _investigation_queryset(request.user)
        status = request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        name = request.GET.get('name')
        if name:
            qs = qs.filter(name__icontains=name)
        owner = request.GET.get('owner')
        if owner:
            qs = qs.filter(owner__icontains=owner)
        page, page_size = paginate(request, default_page_size=100)
        total = qs.count()
        records = qs[(page - 1) * page_size:page * page_size]
        return json_response({
            'records': [x.to_view() for x in records],
            'total': total,
            'page': page,
            'page_size': page_size,
            'status_options': [
                {'value': x, 'label': y} for x, y in INVESTIGATION_STATUS_CHOICES],
        })

    @auth(INVESTIGATION_ADD_PERMISSION + '|' + EVENT_ADD_PERMISSION)
    def post(self, request):
        if not (request.user.has_perms({INVESTIGATION_ADD_PERMISSION}) or
                request.user.has_perms({EVENT_ADD_PERMISSION})):
            return json_response(error='权限拒绝')
        data = _body(request)
        if data is None:
            return json_response(error='请求体必须是 JSON 对象')
        if not data.get('name'):
            return json_response(error='请输入调查名称')
        status = data.get('status', 'draft')
        if status not in dict(INVESTIGATION_STATUS_CHOICES):
            return json_response(error='调查状态值无效')
        try:
            start_at = _parse_optional_datetime(data.get('start_at'), '开始时间')
            end_at = _parse_optional_datetime(data.get('end_at'), '结束时间')
        except ValueError as exc:
            return json_response(error=str(exc))
        event_ids = data.get('event_ids', data.get('events', [])) or []
        if not isinstance(event_ids, list):
            return json_response(error='event_ids 必须是数组')
        try:
            event_ids = [int(x) for x in event_ids]
        except (TypeError, ValueError):
            return json_response(error='event_ids 必须是整数数组')
        with transaction.atomic():
            investigation = InterferenceInvestigation.objects.create(
                tenant_id=getattr(request.user, 'tenant_id', 'admin'),
                name=data.get('name', ''), scope=data.get('scope', '') or '',
                owner=data.get('owner', '') or '',
                trigger_reason=data.get('trigger_reason', '') or '',
                start_at=start_at, end_at=end_at, status=status,
                conclusion=data.get('conclusion', '') or '',
                follow_up_advice=data.get('follow_up_advice', '') or '',
                remark=data.get('remark', '') or '', created_by=request.user,
            )
            error = _link_events(request, investigation, event_ids)
            if error:
                transaction.set_rollback(True)
                return json_response(error=error)
            record_audit_event(
                request, 'create', 'interference_investigation', str(investigation.id),
                investigation.name, {'event_ids': event_ids},
            )
        return json_response(investigation.to_view())


def _link_events(request, investigation, event_ids, relevance_note=''):
    events = list(_event_queryset(request.user).filter(id__in=event_ids))
    if len(events) != len(set(event_ids)):
        return '存在不存在或无权限访问的事件'
    for event in events:
        existing = InvestigationEvent.objects.all_with_deleted().filter(
            investigation_id=investigation.id, event_id=event.id).first()
        if existing and not existing.is_deleted:
            return '同一调查不能重复关联同一事件'
        if existing:
            existing.is_deleted = False
            existing.deleted_at = None
            existing.relevance_note = relevance_note or existing.relevance_note
            existing.tenant_id = getattr(request.user, 'tenant_id', 'admin')
            existing.created_by = request.user
            existing.save(update_fields=[
                'is_deleted', 'deleted_at', 'relevance_note', 'tenant_id', 'created_by'])
        else:
            InvestigationEvent.objects.create(
                investigation=investigation, event=event,
                sequence=InvestigationEvent.objects.filter(
                    investigation_id=investigation.id, is_deleted=False).count() + 1,
                relevance_note=relevance_note or '',
                tenant_id=getattr(request.user, 'tenant_id', 'admin'),
                created_by=request.user,
            )
    return None


class InvestigationDetailView(View):
    @auth(INVESTIGATION_VIEW_PERMISSION + '|' + EVENT_VIEW_PERMISSION)
    def get(self, request, pk):
        investigation = _investigation_queryset(request.user).filter(pk=pk).first()
        if not investigation:
            return json_response(error='调查不存在或无权限访问')
        data = investigation.to_view()
        data['events'] = [
            link.event.to_view() for link in InvestigationEvent.objects.filter(
                investigation_id=investigation.id, is_deleted=False,
                event__is_deleted=False).select_related('event')
        ]
        data['measurements'] = [
            measurement.to_view() for measurement in SpectrumMeasurement.objects.filter(
                investigation_id=investigation.id, is_deleted=False)
        ]
        return json_response(data)

    @auth(INVESTIGATION_EDIT_PERMISSION)
    def put(self, request, pk):
        return self._update(request, pk)

    @auth(INVESTIGATION_EDIT_PERMISSION)
    def patch(self, request, pk):
        return self._update(request, pk)

    def _update(self, request, pk):
        data = _body(request)
        if data is None:
            return json_response(error='请求体必须是 JSON 对象')
        with transaction.atomic():
            investigation = _investigation_queryset(request.user).select_for_update().filter(
                pk=pk).first()
            if not investigation:
                return json_response(error='调查不存在或无权限编辑')
            before = investigation.to_view()
            fields = (
                'name', 'scope', 'owner', 'trigger_reason', 'status',
                'conclusion', 'follow_up_advice', 'remark',
            )
            for field in fields:
                if field in data:
                    setattr(investigation, field, data[field] or '')
            if investigation.status not in dict(INVESTIGATION_STATUS_CHOICES):
                return json_response(error='调查状态值无效')
            try:
                if 'start_at' in data:
                    investigation.start_at = _parse_optional_datetime(
                        data['start_at'], '开始时间')
                if 'end_at' in data:
                    investigation.end_at = _parse_optional_datetime(
                        data['end_at'], '结束时间')
            except ValueError as exc:
                return json_response(error=str(exc))
            investigation.updated_by = request.user
            investigation.updated_at = timezone.now()
            investigation.save()
            record_audit_event(
                request, 'update', 'interference_investigation', str(investigation.id),
                investigation.name, {'id': investigation.id}, before_value=before,
                after_value=investigation.to_view(),
            )
        return json_response(investigation.to_view())

    @auth(INVESTIGATION_DELETE_PERMISSION)
    def delete(self, request, pk):
        with transaction.atomic():
            investigation = _investigation_queryset(request.user).select_for_update().filter(
                pk=pk).first()
            if not investigation:
                return json_response(error='调查不存在或无权限删除')
            now = timezone.now()
            investigation.is_deleted = True
            investigation.deleted_at = now
            investigation.updated_by = request.user
            investigation.updated_at = now
            investigation.save(update_fields=['is_deleted', 'deleted_at', 'updated_by', 'updated_at'])
            InvestigationEvent.objects.filter(investigation_id=pk).update(
                is_deleted=True, deleted_at=now)
            SpectrumMeasurement.objects.filter(investigation_id=pk).update(
                is_deleted=True, deleted_at=now)
            AttachmentService.soft_delete_by_object(
                request.user, ATTACHMENT_MODULE, INVESTIGATION_OBJECT_TYPE, pk,
                reason='规律调查删除', delete_file=True,
            )
            record_audit_event(
                request, 'delete', 'interference_investigation', str(pk),
                investigation.name, {'id': pk},
            )
        return json_response()


class InvestigationEventsView(View):
    @auth(INVESTIGATION_VIEW_PERMISSION + '|' + EVENT_VIEW_PERMISSION)
    def get(self, request, pk):
        investigation = _investigation_queryset(request.user).filter(pk=pk).first()
        if not investigation:
            return json_response(error='调查不存在或无权限访问')
        links = InvestigationEvent.objects.filter(
            investigation_id=pk, is_deleted=False, event__is_deleted=False
        ).select_related('event').order_by('sequence', 'linked_at')
        return json_response({
            'records': [
                {
                    'sequence': link.sequence,
                    'relevance_note': link.relevance_note,
                    'linked_at': link.linked_at,
                    'event': link.event.to_view(),
                } for link in links
            ],
            'total': links.count(),
        })

    @auth(INVESTIGATION_EDIT_PERMISSION + '|' + EVENT_ADD_PERMISSION)
    def post(self, request, pk):
        if not (request.user.has_perms({INVESTIGATION_EDIT_PERMISSION}) or
                request.user.has_perms({EVENT_ADD_PERMISSION})):
            return json_response(error='权限拒绝')
        data = _body(request) or {}
        event_ids = data.get('event_ids')
        if event_ids is None:
            event_ids = [data.get('event_id')] if data.get('event_id') is not None else []
        if not isinstance(event_ids, list):
            return json_response(error='event_ids 必须是数组')
        try:
            event_ids = [int(x) for x in event_ids]
        except (TypeError, ValueError):
            return json_response(error='event_ids 必须是整数数组')
        investigation = _investigation_queryset(request.user).filter(pk=pk).first()
        if not investigation:
            return json_response(error='调查不存在或无权限访问')
        with transaction.atomic():
            error = _link_events(
                request, investigation, event_ids, data.get('relevance_note', ''))
            if error:
                return json_response(error=error)
            record_audit_event(
                request, 'update', 'interference_investigation', str(pk),
                investigation.name, {'event_ids': event_ids, 'action': 'link_events'},
            )
        return json_response({'event_ids': event_ids})

    @auth(INVESTIGATION_EDIT_PERMISSION)
    def delete(self, request, pk):
        data = _body(request) or {}
        event_id = request.GET.get('event_id') or data.get('event_id')
        if not event_id:
            return json_response(error='请指定 event_id')
        try:
            event_id = int(event_id)
        except (TypeError, ValueError):
            return json_response(error='event_id 必须为整数')
        investigation = _investigation_queryset(request.user).filter(pk=pk).first()
        if not investigation:
            return json_response(error='调查不存在或无权限访问')
        updated = InvestigationEvent.objects.filter(
            investigation_id=pk, event_id=event_id, is_deleted=False).update(
                is_deleted=True, deleted_at=timezone.now())
        if not updated:
            return json_response(error='关联不存在或已删除')
        record_audit_event(
            request, 'delete', 'interference_investigation_event',
            f'{pk}:{event_id}', investigation.name, {'event_id': event_id},
        )
        return json_response()


MEASUREMENT_FIELDS = (
    'measured_at', 'location', 'instrument_model', 'instrument_no',
    'frequency_range', 'center_frequency', 'bandwidth', 'field_strength',
    'power', 'measurement_unit', 'antenna_polarization', 'result',
    'conclusion', 'remark',
)
MEASUREMENT_DECIMAL_FIELDS = {
    'center_frequency', 'bandwidth', 'field_strength', 'power',
}


def _measurement_values(data, existing=None):
    values = {}
    if not isinstance(data, dict):
        return None, '请求体必须是 JSON 对象'
    if existing is None and not data.get('measured_at'):
        return None, '请输入测量时间'
    for field in MEASUREMENT_FIELDS:
        if field not in data:
            continue
        value = data[field]
        try:
            if field == 'measured_at':
                value = _parse_datetime(value, '测量时间')
            elif field in MEASUREMENT_DECIMAL_FIELDS:
                value = _parse_decimal(value, field)
            elif value is None:
                value = ''
        except ValueError as exc:
            return None, str(exc)
        values[field] = value
    return values, None


class InvestigationMeasurementsView(View):
    @auth(MEASUREMENT_VIEW_PERMISSION + '|' + INVESTIGATION_VIEW_PERMISSION)
    def get(self, request, pk):
        investigation = _investigation_queryset(request.user).filter(pk=pk).first()
        if not investigation:
            return json_response(error='调查不存在或无权限访问')
        qs = _measurement_queryset(request.user).filter(investigation_id=pk)
        return json_response({'records': [x.to_view() for x in qs], 'total': qs.count()})

    @auth(MEASUREMENT_ADD_PERMISSION + '|' + INVESTIGATION_EDIT_PERMISSION)
    def post(self, request, pk):
        if not (request.user.has_perms({MEASUREMENT_ADD_PERMISSION}) or
                request.user.has_perms({INVESTIGATION_EDIT_PERMISSION})):
            return json_response(error='权限拒绝')
        investigation = _investigation_queryset(request.user).filter(pk=pk).first()
        if not investigation:
            return json_response(error='调查不存在或无权限访问')
        values, error = _measurement_values(_body(request))
        if error:
            return json_response(error=error)
        with transaction.atomic():
            measurement = SpectrumMeasurement.objects.create(
                **values, investigation=investigation,
                tenant_id=getattr(request.user, 'tenant_id', 'admin'),
                created_by=request.user,
            )
            record_audit_event(
                request, 'create', 'interference_measurement', str(measurement.id),
                investigation.name, {'investigation_id': pk},
            )
        return json_response(measurement.to_view())


class MeasurementDetailView(View):
    @auth(MEASUREMENT_VIEW_PERMISSION + '|' + INVESTIGATION_VIEW_PERMISSION)
    def get(self, request, pk):
        measurement = _measurement_queryset(request.user).filter(pk=pk).first()
        if not measurement:
            return json_response(error='测量记录不存在或无权限访问')
        return json_response(measurement.to_view())

    @auth(MEASUREMENT_EDIT_PERMISSION)
    def put(self, request, pk):
        return self._update(request, pk)

    @auth(MEASUREMENT_EDIT_PERMISSION)
    def patch(self, request, pk):
        return self._update(request, pk)

    def _update(self, request, pk):
        measurement = _measurement_queryset(request.user).filter(pk=pk).first()
        if not measurement:
            return json_response(error='测量记录不存在或无权限编辑')
        values, error = _measurement_values(_body(request), measurement)
        if error:
            return json_response(error=error)
        with transaction.atomic():
            for key, value in values.items():
                setattr(measurement, key, value)
            measurement.updated_by = request.user
            measurement.updated_at = timezone.now()
            measurement.save()
            record_audit_event(
                request, 'update', 'interference_measurement', str(measurement.id),
                str(measurement.id), {'investigation_id': measurement.investigation_id},
            )
        return json_response(measurement.to_view())

    @auth(MEASUREMENT_DELETE_PERMISSION)
    def delete(self, request, pk):
        with transaction.atomic():
            measurement = _measurement_queryset(request.user).select_for_update().filter(
                pk=pk).first()
            if not measurement:
                return json_response(error='测量记录不存在或无权限删除')
            now = timezone.now()
            measurement.is_deleted = True
            measurement.deleted_at = now
            measurement.updated_by = request.user
            measurement.updated_at = now
            measurement.save(update_fields=['is_deleted', 'deleted_at', 'updated_by', 'updated_at'])
            AttachmentService.soft_delete_by_object(
                request.user, ATTACHMENT_MODULE, MEASUREMENT_OBJECT_TYPE, pk,
                reason='频谱测量记录删除', delete_file=True,
            )
            record_audit_event(
                request, 'delete', 'interference_measurement', str(pk), str(pk),
                {'investigation_id': measurement.investigation_id},
            )
        return json_response()


def _parent_for_object(user, object_type, object_id):
    try:
        object_id = int(object_id)
    except (TypeError, ValueError):
        return None
    model_by_type = {
        EVENT_OBJECT_TYPE: _event_queryset,
        INVESTIGATION_OBJECT_TYPE: _investigation_queryset,
        MEASUREMENT_OBJECT_TYPE: _measurement_queryset,
    }
    queryset_factory = model_by_type.get(object_type)
    if not queryset_factory:
        return None
    return queryset_factory(user).filter(pk=object_id).first()


def _get_interference_attachment_for_user(user, attachment_id, object_type=None):
    """统一校验租户、模块、类型和父对象，防止跨模块附件越权。"""
    attachment = apply_tenant_filter(
        EvidenceAttachment.objects.filter(is_deleted=False), user
    ).filter(pk=attachment_id).first()
    if not attachment:
        return None, ATTACHMENT_FORBIDDEN_ERROR
    if attachment.module != ATTACHMENT_MODULE:
        return None, ATTACHMENT_FORBIDDEN_ERROR
    if object_type and attachment.object_type != object_type:
        return None, ATTACHMENT_FORBIDDEN_ERROR
    if attachment.object_type not in ATTACHMENT_OBJECT_TYPES:
        return None, ATTACHMENT_FORBIDDEN_ERROR
    # New-record uploads may use a temporary UUID before the parent exists.
    # Persisted numeric object IDs must always resolve to a live, tenant-visible
    # parent so deleted/orphaned objects cannot be reached through attachments.
    if (not _parent_for_object(user, attachment.object_type, attachment.object_id)
            and not _is_temporary_object_id(attachment.object_id)):
        return None, ATTACHMENT_FORBIDDEN_ERROR
    return attachment, None


class AttachmentListView(View):
    object_type = None
    parent_queryset = None
    view_permissions = ()
    upload_permissions = ()

    def _parent_exists(self, request, pk):
        return bool(self.parent_queryset(request.user).filter(pk=pk).first())

    @auth(EVENT_VIEW_PERMISSION + '|' + INVESTIGATION_VIEW_PERMISSION + '|' + MEASUREMENT_VIEW_PERMISSION)
    def get(self, request, pk):
        if not _has_attachment_permission(request.user, self.object_type, 'view'):
            return json_response(error='权限拒绝')
        if not self._parent_exists(request, pk):
            return json_response(error='业务对象不存在或无权限访问')
        return json_response(AttachmentService.list(
            request.user, ATTACHMENT_MODULE, self.object_type, pk))

    @auth(EVENT_ADD_PERMISSION + '|' + EVENT_EDIT_PERMISSION + '|' +
          INVESTIGATION_ADD_PERMISSION + '|' + INVESTIGATION_EDIT_PERMISSION + '|' +
          MEASUREMENT_ADD_PERMISSION + '|' + MEASUREMENT_EDIT_PERMISSION)
    def post(self, request, pk):
        if not _has_attachment_permission(request.user, self.object_type, 'upload'):
            return json_response(error='权限拒绝')
        if not self._parent_exists(request, pk):
            return json_response(error='业务对象不存在或无权限访问')
        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的文件')
        attachment, error = AttachmentService.upload(
            file=file, user=request.user, module=ATTACHMENT_MODULE,
            object_type=self.object_type, object_id=pk,
            config=InterferenceAttachmentConfig,
        )
        if error:
            return json_response(error=error)
        result = attachment.to_view()
        result['previewable'] = attachment.file_ext in PREVIEWABLE_EXTENSIONS
        record_audit_event(
            request, 'create', f'{self.object_type}_attachment', str(attachment.id),
            attachment.file_name, {'object_id': str(pk), 'object_type': self.object_type},
        )
        return json_response(result)


class EventAttachmentListView(AttachmentListView):
    object_type = EVENT_OBJECT_TYPE
    parent_queryset = staticmethod(_event_queryset)
    view_permissions = ATTACHMENT_PERMISSION_MAP[EVENT_OBJECT_TYPE]['view']
    upload_permissions = ATTACHMENT_PERMISSION_MAP[EVENT_OBJECT_TYPE]['upload']


class InvestigationAttachmentListView(AttachmentListView):
    object_type = INVESTIGATION_OBJECT_TYPE
    parent_queryset = staticmethod(_investigation_queryset)
    view_permissions = ATTACHMENT_PERMISSION_MAP[INVESTIGATION_OBJECT_TYPE]['view']
    upload_permissions = ATTACHMENT_PERMISSION_MAP[INVESTIGATION_OBJECT_TYPE]['upload']


class MeasurementAttachmentListView(AttachmentListView):
    object_type = MEASUREMENT_OBJECT_TYPE
    parent_queryset = staticmethod(_measurement_queryset)
    view_permissions = ATTACHMENT_PERMISSION_MAP[MEASUREMENT_OBJECT_TYPE]['view']
    upload_permissions = ATTACHMENT_PERMISSION_MAP[MEASUREMENT_OBJECT_TYPE]['upload']


class AttachmentDownloadView(View):
    @auth(EVENT_VIEW_PERMISSION + '|' + INVESTIGATION_VIEW_PERMISSION + '|' + MEASUREMENT_VIEW_PERMISSION)
    def get(self, request, pk):
        attachment, error = _get_interference_attachment_for_user(request.user, pk)
        if error:
            return json_response(error=error)
        if not _has_attachment_permission(request.user, attachment.object_type, 'view'):
            return json_response(error=ATTACHMENT_FORBIDDEN_ERROR)
        response, error = AttachmentService.download_response(
            request.user, pk, ATTACHMENT_MODULE, attachment.object_type,
            inline=request.GET.get('inline') in ('1', 'true', 'True'))
        return json_response(error=error) if error else response


class AttachmentPreviewUrlView(View):
    @auth(EVENT_VIEW_PERMISSION + '|' + INVESTIGATION_VIEW_PERMISSION + '|' + MEASUREMENT_VIEW_PERMISSION)
    def get(self, request, pk):
        attachment, error = _get_interference_attachment_for_user(request.user, pk)
        if error:
            return json_response(error=error)
        if not _has_attachment_permission(request.user, attachment.object_type, 'view'):
            return json_response(error=ATTACHMENT_FORBIDDEN_ERROR)
        data, error = AttachmentService.get_preview_url(
            request.user, pk, ATTACHMENT_MODULE, attachment.object_type,
            f'/api/interference/attachments/{pk}/preview-file/')
        return json_response(error=error) if error else json_response(data)


class AttachmentPreviewFileView(View):
    def get(self, request, pk):
        token = request.GET.get('preview_token')
        if not token:
            return json_response(error='缺少 preview_token 参数')
        response, error = AttachmentService.preview_file_response(token, pk)
        return json_response(error=error) if error else response


class AttachmentDeleteView(View):
    @auth(EVENT_EDIT_PERMISSION + '|' + EVENT_DELETE_PERMISSION + '|' +
          INVESTIGATION_EDIT_PERMISSION + '|' + INVESTIGATION_DELETE_PERMISSION + '|' +
          MEASUREMENT_EDIT_PERMISSION + '|' + MEASUREMENT_DELETE_PERMISSION)
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定附件ID'),
            Argument('delete_reason', required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        with transaction.atomic():
            attachment, error = _get_interference_attachment_for_user(
                request.user, form.id)
            if error:
                return json_response(error=error)
            if not _has_attachment_permission(request.user, attachment.object_type, 'delete'):
                return json_response(error=ATTACHMENT_FORBIDDEN_ERROR)
            error = AttachmentService.soft_delete(
                request.user, form.id, ATTACHMENT_MODULE, attachment.object_type,
                form.delete_reason, delete_file=True)
            if error:
                return json_response(error=error)
            record_audit_event(
                request, 'delete', 'interference_attachment', str(form.id),
                attachment.file_name, {'object_type': attachment.object_type,
                                       'object_id': attachment.object_id},
            )
        return json_response()


class EventExportView(View):
    @auth(EVENT_VIEW_PERMISSION)
    def get(self, request):
        # Apply the same filters as the list endpoint, but intentionally do not
        # paginate: an export represents the complete filtered result set.
        qs, error = _filtered_event_queryset(request, request.user)
        if error:
            return json_response(error=error)
        output = io.StringIO()
        writer = csv.writer(output)
        fields = (
            'id', 'datetime', 'scene_code', 'classification_status',
            'interference_kind_code', 'affected_system_code', 'source_type_code',
            'flight_number', 'aircraft_no', 'aircraft_type', 'phenomenon',
            'initial_assessment', 'remark',
        )
        writer.writerow(fields)
        count = 0
        for event in qs.iterator():
            record = event.to_view(include_details=False)
            writer.writerow([record.get(key, '') for key in fields])
            count += 1
        record_audit_event(request, 'export', 'interference_event', detail={
            'count': count,
        })
        result = HttpResponse('\ufeff' + output.getvalue(), content_type='text/csv; charset=utf-8')
        result['Content-Disposition'] = 'attachment; filename="interference-events.csv"'
        return result


class EventImportView(View):
    @auth(EVENT_ADD_PERMISSION)
    def post(self, request):
        if not request.user.has_perms({EVENT_ADD_PERMISSION}):
            return json_response(error='权限拒绝')
        data = _body(request)
        if data is None:
            raw_file = request.FILES.get('file')
            if not raw_file:
                return json_response(error='请求体必须是 JSON 对象或 CSV 文件')
            text = raw_file.read().decode('utf-8-sig')
            rows = list(csv.DictReader(io.StringIO(text)))
        else:
            rows = data.get('events', [])
        if not isinstance(rows, list):
            return json_response(error='events 必须是数组')
        created = []
        errors = []
        for index, row in enumerate(rows, 1):
            values, ground, air, error = _event_payload(row)
            if error:
                errors.append({'row': index, 'error': error})
                continue
            try:
                with transaction.atomic():
                    event = InterferenceEvent.objects.create(
                        **values,
                        created_by=request.user,
                        tenant_id=getattr(request.user, 'tenant_id', 'admin'),
                    )
                    _sync_event_details(event, ground, air, row, request.user, creating=True)
                    error = _validate_detail_state(event)
                    if error:
                        raise ValueError(error)
                    record_audit_event(
                        request, 'import', 'interference_event', str(event.id),
                        event.phenomenon[:100], {'row': index},
                    )
                    created.append(event.id)
            except (ValueError, IntegrityError) as exc:
                errors.append({'row': index, 'error': str(exc)})
        return json_response({'created_ids': created, 'errors': errors})
