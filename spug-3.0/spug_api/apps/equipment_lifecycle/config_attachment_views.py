# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——配置变更附件视图（复用 EvidenceAttachment 能力）。

从 config_views 拆出（文件行数治理）：附件上传/列表/删除/下载。
- 访问前先校验配置变更存在且属于当前租户（父对象校验），再校验附件归属
  （附件存在、未软删除、归属本模块与父记录、租户可见）；
- 草稿已取消/已回退/已生效后不允许上传/删除附件（留档完整），仍可下载；
- 单向依赖 config_views 的取数助手（不回引本模块）。
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

from apps.equipment_lifecycle.config_models import CONFIG_CHANGE_DRAFT
from apps.equipment_lifecycle.config_views import (
    AUDIT_TARGET_CONFIG_CHANGE,
    _get_change_for_user,
)

CONFIG_ATTACHMENT_MODULE = 'equipment_lifecycle'
CONFIG_ATTACHMENT_OBJECT_TYPE = 'el_config_change'

# 允许上传/删除附件的变更状态：仅草稿（生效后留档，附件不增删）
CONFIG_ATTACHMENT_EDITABLE_STATUSES = [CONFIG_CHANGE_DRAFT]


def _get_change_attachment_for_user(change, attachment_id, user):
    """附件归属校验：附件存在、未软删除、归属本模块与父记录、租户可见。"""
    att = apply_tenant_filter(
        EvidenceAttachment.objects.filter(is_deleted=False), user
    ).filter(pk=attachment_id, module=CONFIG_ATTACHMENT_MODULE,
             object_type=CONFIG_ATTACHMENT_OBJECT_TYPE,
             object_id=str(change.id)).first()
    if not att:
        return None
    return att


class ConfigChangeAttachmentView(View):
    """配置变更附件（复用 EvidenceAttachment 能力，父对象校验先行）。"""

    @auth('equipment_lifecycle.config.view')
    def get(self, request, pk):
        change = _get_change_for_user(pk, request.user)
        if not change:
            return json_response(error='配置变更不存在')
        attachments = AttachmentService.list(
            request.user, CONFIG_ATTACHMENT_MODULE, CONFIG_ATTACHMENT_OBJECT_TYPE, change.id)
        return json_response({'data': attachments})

    @auth('equipment_lifecycle.config.attachment')
    def post(self, request, pk):
        with transaction.atomic():
            change = _get_change_for_user(pk, request.user, for_update=True)
            if not change:
                return json_response(error='配置变更不存在')
            if change.status not in CONFIG_ATTACHMENT_EDITABLE_STATUSES:
                return json_response(error='只有草稿状态的配置变更可以上传附件')
            file = request.FILES.get('file')
            if not file:
                return json_response(error='缺少上传文件')
            att, error = AttachmentService.upload(
                file, request.user, CONFIG_ATTACHMENT_MODULE,
                CONFIG_ATTACHMENT_OBJECT_TYPE, change.id,
                config=DefaultAttachmentConfig, owner_tenant_id=change.tenant_id)
            if error:
                return json_response(error=error)
            record_audit_event(request, 'update', AUDIT_TARGET_CONFIG_CHANGE,
                               change.id, change.change_no,
                               after_value={'action': 'upload_attachment',
                                            'file_name': att.file_name})
        return json_response(att.to_view())


class ConfigChangeAttachmentDetailView(View):
    @auth('equipment_lifecycle.config.attachment')
    def delete(self, request, pk, aid):
        with transaction.atomic():
            change = _get_change_for_user(pk, request.user, for_update=True)
            if not change:
                return json_response(error='配置变更不存在')
            if change.status not in CONFIG_ATTACHMENT_EDITABLE_STATUSES:
                return json_response(error='只有草稿状态的配置变更可以删除附件')
            att = _get_change_attachment_for_user(change, aid, request.user)
            if not att:
                return json_response(error=ATTACHMENT_DELETE_DENIED_ERROR)
            error = AttachmentService.soft_delete(
                request.user, aid, CONFIG_ATTACHMENT_MODULE,
                CONFIG_ATTACHMENT_OBJECT_TYPE, reason='配置变更附件删除')
            if error:
                return json_response(error=error)
            record_audit_event(request, 'update', AUDIT_TARGET_CONFIG_CHANGE,
                               change.id, change.change_no,
                               after_value={'action': 'delete_attachment',
                                            'file_name': att.file_name})
        return json_response({})


class ConfigChangeAttachmentDownloadView(View):
    @auth('equipment_lifecycle.config.view')
    def get(self, request, pk, aid):
        change = _get_change_for_user(pk, request.user)
        if not change:
            return json_response(error='配置变更不存在')
        att = _get_change_attachment_for_user(change, aid, request.user)
        if not att:
            return json_response(error='附件不存在或无权限访问')
        response, error = AttachmentService.download_response(
            request.user, aid, CONFIG_ATTACHMENT_MODULE, CONFIG_ATTACHMENT_OBJECT_TYPE)
        if error:
            return json_response(error=error)
        return response
