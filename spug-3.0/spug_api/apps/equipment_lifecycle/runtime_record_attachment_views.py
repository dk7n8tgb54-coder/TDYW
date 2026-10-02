# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""设备全生命周期——运行记录附件视图（复用 EvidenceAttachment 能力）。

从 runtime_record_views 拆出（文件行数治理）：附件上传/列表/删除/下载。
- 访问前先校验运行记录存在且属于当前租户（父对象校验），再校验附件归属
  （附件存在、未软删除、归属本模块与父记录、租户可见）；
- 终态（已关闭/已转故障）记录不允许上传/删除附件，仍可下载；
- 单向依赖 runtime_record_views 的取数助手（不回引本模块）。
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

from apps.equipment_lifecycle.models import EDITABLE_RUNTIME_RECORD_STATUSES
from apps.equipment_lifecycle.runtime_record_views import (
    _get_record_for_user,
    AUDIT_TARGET_RUNTIME_RECORD,
    RUNTIME_ATTACHMENT_MODULE,
    RUNTIME_ATTACHMENT_OBJECT_TYPE,
)


def _get_record_attachment_for_user(record, attachment_id, user):
    """附件归属校验：附件存在、未软删除、归属本模块与父记录、租户可见。"""
    att = apply_tenant_filter(
        EvidenceAttachment.objects.filter(is_deleted=False), user
    ).filter(pk=attachment_id, module=RUNTIME_ATTACHMENT_MODULE,
             object_type=RUNTIME_ATTACHMENT_OBJECT_TYPE,
             object_id=str(record.id)).first()
    if not att:
        return None
    return att


class RuntimeRecordAttachmentView(View):
    """运行记录附件（复用 EvidenceAttachment 能力）。

    访问前先校验运行记录存在且属于当前租户（父对象校验）。
    """

    @auth('equipment_lifecycle.runtime_record.view')
    def get(self, request, pk):
        record = _get_record_for_user(pk, request.user)
        if not record:
            return json_response(error='运行记录不存在')
        attachments = AttachmentService.list(
            request.user, RUNTIME_ATTACHMENT_MODULE, RUNTIME_ATTACHMENT_OBJECT_TYPE, record.id)
        return json_response({'data': attachments})

    @auth('equipment_lifecycle.runtime_record.edit')
    def post(self, request, pk):
        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='运行记录不存在')
            if record.status not in EDITABLE_RUNTIME_RECORD_STATUSES:
                return json_response(error='已关闭或已转故障的运行记录不能上传附件')
            file = request.FILES.get('file')
            if not file:
                return json_response(error='缺少上传文件')
            att, error = AttachmentService.upload(
                file, request.user, RUNTIME_ATTACHMENT_MODULE,
                RUNTIME_ATTACHMENT_OBJECT_TYPE, record.id,
                config=DefaultAttachmentConfig, owner_tenant_id=record.tenant_id)
            if error:
                return json_response(error=error)
            record_audit_event(request, 'create', AUDIT_TARGET_RUNTIME_RECORD,
                               record.id, record.record_no,
                               after_value={'action': 'upload_attachment',
                                            'file_name': att.file_name})
        return json_response(att.to_view())


class RuntimeRecordAttachmentDetailView(View):
    @auth('equipment_lifecycle.runtime_record.edit')
    def delete(self, request, pk, aid):
        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='运行记录不存在')
            if record.status not in EDITABLE_RUNTIME_RECORD_STATUSES:
                return json_response(error='已关闭或已转故障的运行记录不能删除附件')
            att = _get_record_attachment_for_user(record, aid, request.user)
            if not att:
                return json_response(error=ATTACHMENT_DELETE_DENIED_ERROR)
            error = AttachmentService.soft_delete(
                request.user, aid, RUNTIME_ATTACHMENT_MODULE,
                RUNTIME_ATTACHMENT_OBJECT_TYPE, reason='运行记录附件删除')
            if error:
                return json_response(error=error)
            record_audit_event(request, 'delete', AUDIT_TARGET_RUNTIME_RECORD,
                               record.id, record.record_no,
                               after_value={'action': 'delete_attachment',
                                            'file_name': att.file_name})
        return json_response({})


class RuntimeRecordAttachmentDownloadView(View):
    @auth('equipment_lifecycle.runtime_record.view')
    def get(self, request, pk, aid):
        record = _get_record_for_user(pk, request.user)
        if not record:
            return json_response(error='运行记录不存在')
        att = _get_record_attachment_for_user(record, aid, request.user)
        if not att:
            return json_response(error='附件不存在或无权限访问')
        response, error = AttachmentService.download_response(
            request.user, aid, RUNTIME_ATTACHMENT_MODULE, RUNTIME_ATTACHMENT_OBJECT_TYPE)
        if error:
            return json_response(error=error)
        return response
