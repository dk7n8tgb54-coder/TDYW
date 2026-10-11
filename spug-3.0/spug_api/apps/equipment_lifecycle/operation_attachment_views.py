# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""设备全生命周期——统一记录主记录附件视图（复用 EvidenceAttachment 能力）。

从原运行记录附件视图改造（2026-10-11 合并改造）：三种记录类型均可在
主记录级上传/管理附件；正式故障已关闭/已撤销后只读（不可上传/删除，
仍可下载）。访问前先校验记录存在且属于当前租户（父对象校验），再校验
附件归属（附件存在、未软删除、归属本模块与父记录、租户可见）。
"""
from django.db import transaction
from django.views.generic import View

from libs import json_response, auth
from libs.tenant_utils import apply_tenant_filter
from apps.evidence.attachment_service import (
    AttachmentService, DefaultAttachmentConfig, ATTACHMENT_DELETE_DENIED_ERROR,
)
from apps.evidence.models import EvidenceAttachment
from apps.logs.audit import record_audit_event

from apps.equipment_lifecycle.operation_views import (
    AUDIT_TARGET_RECORD,
    RECORD_ATTACHMENT_MODULE,
    RECORD_ATTACHMENT_OBJECT_TYPE,
    _get_record_for_user,
)


def _get_record_attachment_for_user(record, attachment_id, user):
    """附件归属校验：附件存在、未软删除、归属本模块与父记录、租户可见。"""
    return apply_tenant_filter(
        EvidenceAttachment.objects.filter(is_deleted=False), user
    ).filter(pk=attachment_id, module=RECORD_ATTACHMENT_MODULE,
             object_type=RECORD_ATTACHMENT_OBJECT_TYPE,
             object_id=str(record.id)).first()


class RecordAttachmentView(View):
    """统一记录主记录附件（复用 EvidenceAttachment 能力）。"""

    @auth('equipment_lifecycle.operation_record.view')
    def get(self, request, pk):
        record = _get_record_for_user(pk, request.user)
        if not record:
            return json_response(error='记录不存在')
        attachments = AttachmentService.list(
            request.user, RECORD_ATTACHMENT_MODULE, RECORD_ATTACHMENT_OBJECT_TYPE,
            record.id)
        return json_response({'data': attachments})

    @auth('equipment_lifecycle.operation_record.edit')
    def post(self, request, pk):
        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='记录不存在')
            if record.status not in record.editable_statuses:
                return json_response(error='当前状态的记录不能上传附件')
            file = request.FILES.get('file')
            if not file:
                return json_response(error='缺少上传文件')
            att, error = AttachmentService.upload(
                file, request.user, RECORD_ATTACHMENT_MODULE,
                RECORD_ATTACHMENT_OBJECT_TYPE, record.id,
                config=DefaultAttachmentConfig, owner_tenant_id=record.tenant_id)
            if error:
                return json_response(error=error)
            record_audit_event(request, 'create', AUDIT_TARGET_RECORD,
                               record.id, record.record_no,
                               after_value={'action': 'upload_attachment',
                                            'file_name': att.file_name})
        return json_response(att.to_view())


class RecordAttachmentDetailView(View):
    @auth('equipment_lifecycle.operation_record.edit')
    def delete(self, request, pk, aid):
        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='记录不存在')
            if record.status not in record.editable_statuses:
                return json_response(error='当前状态的记录不能删除附件')
            att = _get_record_attachment_for_user(record, aid, request.user)
            if not att:
                return json_response(error=ATTACHMENT_DELETE_DENIED_ERROR)
            error = AttachmentService.soft_delete(
                request.user, aid, RECORD_ATTACHMENT_MODULE,
                RECORD_ATTACHMENT_OBJECT_TYPE, reason='运行与故障记录附件删除')
            if error:
                return json_response(error=error)
            record_audit_event(request, 'delete', AUDIT_TARGET_RECORD,
                               record.id, record.record_no,
                               after_value={'action': 'delete_attachment',
                                            'file_name': att.file_name})
        return json_response({})


class RecordAttachmentDownloadView(View):
    @auth('equipment_lifecycle.operation_record.view')
    def get(self, request, pk, aid):
        record = _get_record_for_user(pk, request.user)
        if not record:
            return json_response(error='记录不存在')
        att = _get_record_attachment_for_user(record, aid, request.user)
        if not att:
            return json_response(error='附件不存在或无权限访问')
        response, error = AttachmentService.download_response(
            request.user, aid, RECORD_ATTACHMENT_MODULE, RECORD_ATTACHMENT_OBJECT_TYPE)
        if error:
            return json_response(error=error)
        return response
