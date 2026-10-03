# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——故障"处理进展"视图（时间线 / 追加 / 更正 / 附件）。

从 fault_views.py 拆出的独立视图模块（2026-09 人员记录优化时落位）：
- 处理进展记录故障整体跟进（检查、本方处理、送厂、厂家反馈、返还、测试、
  持续观察等），追加进展不改变故障状态、不影响系统健康状态计算；
- 进展记录人 recorder_name：手动输入的记录人姓名（只表示实际添加本条
  进展的人，不代表负责整个故障；不关联 User，实际记录人可能没有系统账号）；
  缺省当前登录用户显示姓名；handler 外键保留为记录操作账号（审计字段），
  历史记录无 recorder_name 时展示回落 handler 用户名；
- 更正不静默覆盖：原内容、修改内容与更正原因追加保存到 corrections；
- 附件复用 EvidenceAttachment 能力（module=equipment_lifecycle,
  object_type=el_fault_handling, object_id=记录ID）。

依赖说明：本模块从 fault_views 引入共享的故障取数/时间解析助手与常量
（单向依赖，fault_views 不回引本模块），路由见 urls.py。
"""
import json

from django.db import transaction
from django.utils import timezone
from django.views.generic import View

from libs import JsonParser, Argument, json_response, auth
from libs.tenant_utils import apply_tenant_filter
from apps.evidence.attachment_service import (
    AttachmentService, DefaultAttachmentConfig, ATTACHMENT_DELETE_DENIED_ERROR,
)
from apps.evidence.models import EvidenceAttachment
from apps.logs.audit import record_audit_event

from apps.equipment_lifecycle import fault_services
from apps.equipment_lifecycle.models import SystemFaultHandlingRecord
from apps.equipment_lifecycle.fault_views import (
    AUDIT_TARGET_FAULT,
    EDITABLE_FAULT_STATUSES,
    _get_fault_for_user,
    _parse_dt,
)

# 处理进展附件归属标识（复用 EvidenceAttachment 体系，不新建文件存储）
FAULT_ATTACHMENT_MODULE = 'equipment_lifecycle'
FAULT_ATTACHMENT_OBJECT_TYPE = 'el_fault_handling'


def _get_record_for_user(fault, rid, user, for_update=False):
    qs = apply_tenant_filter(SystemFaultHandlingRecord.objects.all(), user)
    if for_update:
        qs = qs.select_for_update()
    return qs.filter(pk=rid, fault=fault).first()


def _validate_progress_type(value):
    """校验进展类型（选填，空串=未选择），返回规范化取值或 None（非法）。"""
    value = (value or '').strip()
    if not value:
        return ''
    return value if value in SystemFaultHandlingRecord.PROGRESS_TYPE_TEXT_MAP else None


def _validate_correction_fields(form):
    """校验更正载荷的可选字段，返回 (progress_type, recorder_name, handled_at, error)。

    进展类型/进展记录人/进展时间未提交（None）时保留原值；显式提交才校验
    与更新（进展类型空串=未选择；进展记录人为手动输入姓名，显式提交空串
    视为不合法——记录人必填）。
    """
    progress_type = None
    if form.progress_type is not None:
        progress_type = _validate_progress_type(form.progress_type)
        if progress_type is None:
            return None, None, None, '进展类型不合法'
    recorder_name = None
    if form.recorder_name is not None:
        recorder_name = form.recorder_name.strip()[:200]
        if not recorder_name:
            return None, None, None, '进展记录人不能为空'
    handled_at = None
    if form.handled_at:
        handled_at = _parse_dt(form.handled_at)
        if not handled_at:
            return None, None, None, '进展时间格式不正确，应为 YYYY-MM-DD HH:MM'
    return progress_type, recorder_name, handled_at, None


class FaultHandlingRecordView(View):
    """处理进展（原"处置记录"）：按进展时间正序的时间线 / 追加进展。

    仅强制"进展时间、进展内容、进展记录人"；记录人为手动输入姓名，
    缺省当前登录用户显示姓名；时间缺省为当前时间，进展类型与处理结果
    均为选填。暂未修复、厂家维修中或等待返还期间可持续追加进展，
    追加进展不改变故障状态、不影响系统健康状态计算。
    """

    @auth('equipment_lifecycle.fault.view')
    def get(self, request, pk):
        fault = _get_fault_for_user(pk, request.user)
        if not fault:
            return json_response(error='故障记录不存在')
        query = apply_tenant_filter(SystemFaultHandlingRecord.objects.all(), request.user).filter(
            fault=fault)
        from libs.pagination import paginate
        page, page_size = paginate(request, default_page_size=100)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [r.to_view() for r in records],
            'total': total, 'page': page, 'page_size': page_size,
        })

    @auth('equipment_lifecycle.fault.handle')
    def post(self, request, pk):
        form, error = JsonParser(
            Argument('handled_at', type=str, required=False, default=None,
                     help='进展时间，缺省为当前时间'),
            Argument('content', type=str, required=True, help='进展内容'),
            Argument('progress_type', type=str, required=False, default='',
                     help='进展类型（选填：check/self_fix/to_vendor/vendor_feedback/'
                          'return/test/watch/other，缺省未选择）'),
            Argument('result', type=str, required=False, default=''),
            Argument('work_hours', type=float, required=False, default=None,
                     help='本次工时（小时，选填）'),
            Argument('recorder_name', type=str, required=False, default=None,
                     help='进展记录人姓名（手动输入，实际添加本条进展的人，'
                          '缺省当前登录用户显示姓名）'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        handled_at = _parse_dt(form.handled_at) if form.handled_at else timezone.now()
        if not handled_at:
            return json_response(error='进展时间格式不正确，应为 YYYY-MM-DD HH:MM')
        if handled_at > timezone.now():
            return json_response(error='进展时间不能晚于当前时间')
        content = form.content.strip()
        if not content:
            return json_response(error='进展内容不能为空')
        progress_type = _validate_progress_type(form.progress_type)
        if progress_type is None:
            return json_response(error='进展类型不合法')
        if form.work_hours is not None and form.work_hours < 0:
            return json_response(error='工时不能为负数')
        # 记录人手动输入必填（不默认当前登录用户）
        recorder_name = (form.recorder_name or '').strip()[:200]
        if not recorder_name:
            return json_response(error='进展记录人不能为空')
        with fault_services.health_recalc_lock():
            with transaction.atomic():
                fault = _get_fault_for_user(pk, request.user, for_update=True)
                if not fault:
                    return json_response(error='故障记录不存在')
                if fault.status not in EDITABLE_FAULT_STATUSES:
                    return json_response(error='已关闭或已撤销的故障不能追加处理进展')
                record = SystemFaultHandlingRecord.objects.create(
                    tenant_id=fault.tenant_id,
                    fault=fault,
                    handled_at=handled_at,
                    handler=request.user,
                    recorder_name=recorder_name,
                    progress_type=progress_type,
                    content=content[:2000],
                    result=(form.result or '').strip()[:200],
                    work_hours=form.work_hours,
                )
                record_audit_event(request, 'create', AUDIT_TARGET_FAULT, fault.id,
                                   fault.fault_no,
                                   after_value={'action': 'add_handling_record',
                                                'record_id': record.id,
                                                'progress_type': record.progress_type,
                                                'recorder_name': record.recorder_name,
                                                'handled_at': handled_at.isoformat(sep=' ',
                                                                                   timespec='minutes')})
        return json_response(record.to_view())


class FaultHandlingRecordDetailView(View):
    """处理进展更正：保存原内容、修改内容和更正原因，不静默覆盖。"""

    @auth('equipment_lifecycle.fault.edit')
    def put(self, request, pk, rid):
        form, error = JsonParser(
            Argument('handled_at', type=str, required=False, default=None),
            Argument('content', type=str, required=True, help='进展内容'),
            Argument('progress_type', type=str, required=False, default=None,
                     help='进展类型；未提交时保留原值'),
            Argument('result', type=str, required=False, default=''),
            Argument('work_hours', type=float, required=False, default=None,
                     help='本次工时（小时）；未提交时保留原值'),
            Argument('recorder_name', type=str, required=False, default=None,
                     help='进展记录人姓名（手动输入）；未提交时保留原值'),
            Argument('correction_reason', type=str, required=True, help='更正原因'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        content = form.content.strip()
        if not content:
            return json_response(error='进展内容不能为空')
        correction_reason = form.correction_reason.strip()
        if not correction_reason:
            return json_response(error='更正原因不能为空')
        progress_type, recorder_name, handled_at, err = _validate_correction_fields(form)
        if err:
            return json_response(error=err)
        with fault_services.health_recalc_lock():
            with transaction.atomic():
                fault = _get_fault_for_user(pk, request.user, for_update=True)
                if not fault:
                    return json_response(error='故障记录不存在')
                if fault.status not in EDITABLE_FAULT_STATUSES:
                    return json_response(error='已关闭或已撤销的故障不能更正处理进展')
                record = _get_record_for_user(fault, rid, request.user, for_update=True)
                if not record:
                    return json_response(error='处理进展不存在')
                corrections = record.get_corrections()
                corrections.append({
                    'old': record.content,
                    'new': content[:2000],
                    'reason': correction_reason[:500],
                    'by': request.user.username,
                    'at': timezone.now().isoformat(sep=' ', timespec='minutes'),
                })
                record.content = content[:2000]
                if progress_type is not None:
                    record.progress_type = progress_type
                if recorder_name is not None:
                    record.recorder_name = recorder_name
                record.result = (form.result or '').strip()[:200]
                if form.work_hours is not None:
                    if form.work_hours < 0:
                        return json_response(error='工时不能为负数')
                    record.work_hours = form.work_hours
                if handled_at:
                    record.handled_at = handled_at
                record.corrections = json.dumps(corrections, ensure_ascii=False)
                record.save()
                record_audit_event(request, 'update', AUDIT_TARGET_FAULT, fault.id,
                                   fault.fault_no,
                                   after_value={'action': 'correct_handling_record',
                                                'record_id': record.id,
                                                'reason': correction_reason[:200]})
        return json_response(record.to_view())


class FaultHandlingAttachmentView(View):
    """处理进展附件（复用 EvidenceAttachment 能力）。

    访问前先校验进展记录所属故障存在且属于当前租户。
    """

    @auth('equipment_lifecycle.fault.view')
    def get(self, request, pk, rid):
        fault = _get_fault_for_user(pk, request.user)
        if not fault:
            return json_response(error='故障记录不存在')
        record = _get_record_for_user(fault, rid, request.user)
        if not record:
            return json_response(error='处理进展不存在')
        attachments = AttachmentService.list(
            request.user, FAULT_ATTACHMENT_MODULE, FAULT_ATTACHMENT_OBJECT_TYPE, record.id)
        return json_response({'data': attachments})

    @auth('equipment_lifecycle.fault.handle')
    def post(self, request, pk, rid):
        with fault_services.health_recalc_lock():
            with transaction.atomic():
                fault = _get_fault_for_user(pk, request.user, for_update=True)
                if not fault:
                    return json_response(error='故障记录不存在')
                if fault.status not in EDITABLE_FAULT_STATUSES:
                    return json_response(error='已关闭或已撤销的故障不能上传进展附件')
                record = _get_record_for_user(fault, rid, request.user)
                if not record:
                    return json_response(error='处理进展不存在')
                file = request.FILES.get('file')
                if not file:
                    return json_response(error='缺少上传文件')
                att, error = AttachmentService.upload(
                    file, request.user, FAULT_ATTACHMENT_MODULE, FAULT_ATTACHMENT_OBJECT_TYPE,
                    record.id, config=DefaultAttachmentConfig, owner_tenant_id=fault.tenant_id)
                if error:
                    return json_response(error=error)
                record_audit_event(request, 'create', AUDIT_TARGET_FAULT, fault.id,
                                   fault.fault_no,
                                   after_value={'action': 'upload_handling_attachment',
                                                'record_id': record.id,
                                                'file_name': att.file_name})
        return json_response(att.to_view())


class FaultHandlingAttachmentDetailView(View):
    @auth('equipment_lifecycle.fault.edit')
    def delete(self, request, pk, rid, aid):
        with fault_services.health_recalc_lock():
            with transaction.atomic():
                fault = _get_fault_for_user(pk, request.user, for_update=True)
                if not fault:
                    return json_response(error='故障记录不存在')
                if fault.status not in EDITABLE_FAULT_STATUSES:
                    return json_response(error='已关闭或已撤销的故障不能删除进展附件')
                record = _get_record_for_user(fault, rid, request.user)
                if not record:
                    return json_response(error='处理进展不存在')
                att = apply_tenant_filter(
                    EvidenceAttachment.objects.filter(is_deleted=False), request.user
                ).filter(pk=aid, module=FAULT_ATTACHMENT_MODULE,
                         object_type=FAULT_ATTACHMENT_OBJECT_TYPE,
                         object_id=str(record.id)).first()
                if not att:
                    return json_response(error=ATTACHMENT_DELETE_DENIED_ERROR)
                error = AttachmentService.soft_delete(
                    request.user, aid, FAULT_ATTACHMENT_MODULE, FAULT_ATTACHMENT_OBJECT_TYPE,
                    reason='故障处理进展附件删除')
                if error:
                    return json_response(error=error)
                record_audit_event(request, 'delete', AUDIT_TARGET_FAULT, fault.id,
                                   fault.fault_no,
                                   after_value={'action': 'delete_handling_attachment',
                                                'record_id': record.id,
                                                'file_name': att.file_name})
        return json_response({})


class FaultHandlingAttachmentDownloadView(View):
    @auth('equipment_lifecycle.fault.view')
    def get(self, request, pk, rid, aid):
        fault = _get_fault_for_user(pk, request.user)
        if not fault:
            return json_response(error='故障记录不存在')
        record = _get_record_for_user(fault, rid, request.user)
        if not record:
            return json_response(error='处理进展不存在')
        response, error = AttachmentService.download_response(
            request.user, aid, FAULT_ATTACHMENT_MODULE, FAULT_ATTACHMENT_OBJECT_TYPE)
        if error:
            return json_response(error=error)
        return response
