# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""升级模块附件视图 - 转调 evidence 通用附件服务

设计：upgrade 模块只负责
1. 校验业务对象（UpgradeRecord）存在且有权限
2. 校验模块权限码（upgrade.upgrade.view / .add）
3. 转调 evidence.AttachmentService 完成实际文件操作

附件数据统一存 tdyw_evidence_attachments 表，通过
  module='upgrade' / object_type='record' / object_id=<record_id>
关联到升级表单。
"""
import logging

from django.views import View

from libs import json_response, auth, JsonParser, Argument
from libs.tenant_utils import apply_tenant_filter

from ..models import UpgradeRecord
from ..constants import (
    ATTACHMENT_MAX_SIZE_MB, ATTACHMENT_ALLOWED_EXTENSIONS, ATTACHMENT_UPLOAD_DIR,
)
from apps.evidence.attachment_service import AttachmentService, AttachmentConfig

logger = logging.getLogger(__name__)

# upgrade 模块附件配置（复用 constants.py 的配置）
UpgradeAttachmentConfig = AttachmentConfig(
    allowed_extensions=tuple(ATTACHMENT_ALLOWED_EXTENSIONS),
    max_size_mb=ATTACHMENT_MAX_SIZE_MB,
    upload_dir=ATTACHMENT_UPLOAD_DIR,
)

# 业务对象标识
MODULE = 'upgrade'
OBJECT_TYPE = 'record'


def _get_record(record_id, user):
    """获取升级表单（带租户过滤），不存在返回 None"""
    return apply_tenant_filter(
        UpgradeRecord.objects.filter(pk=record_id), user
    ).first()


class AttachmentListView(View):
    """附件列表 / 上传"""

    @auth('upgrade.upgrade.view')
    def get(self, request, record_id):
        record = _get_record(record_id, request.user)
        if record is None:
            return json_response(error='升级表单不存在或无权限访问')
        data = AttachmentService.list(
            request.user, MODULE, OBJECT_TYPE, record_id)
        return json_response(data)

    @auth('upgrade.upgrade.edit')
    def post(self, request, record_id):
        record = _get_record(record_id, request.user)
        if record is None:
            return json_response(error='升级表单不存在或无权限访问')

        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的文件')

        att, error = AttachmentService.upload(
            file=file,
            user=request.user,
            module=MODULE,
            object_type=OBJECT_TYPE,
            object_id=record_id,
            config=UpgradeAttachmentConfig,
        )
        if error:
            return json_response(error=error)

        result = att.to_view()
        result['uploaded_by_name'] = request.user.nickname
        result['created_at'] = att.uploaded_at
        return json_response(result)


class AttachmentDownloadView(View):
    """附件下载（鉴权）"""

    @auth('upgrade.upgrade.view')
    def get(self, request, pk):
        response, error = AttachmentService.download_response(request.user, pk)
        if error:
            return json_response(error=error)
        return response


class AttachmentDeleteView(View):
    """附件删除（软删除）"""

    @auth('upgrade.upgrade.edit')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定附件ID'),
            Argument('delete_reason', required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        error = AttachmentService.soft_delete(
            request.user, form.id, form.delete_reason)
        if error:
            return json_response(error=error)
        return json_response()


# 兼容旧导入路径（apps.upgrade.views.upload.AttachmentUploadView）
# 旧接口仅返回 URL，保留以免破坏未迁移的前端代码
class AttachmentUploadView(View):
    """[已废弃] 旧版附件上传接口，仅返回 URL"""

    @auth('upgrade.upgrade.add')
    def post(self, request):
        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的文件')

        # 旧接口不关联具体记录，用临时 object_id，仅返回 URL
        att, error = AttachmentService.upload(
            file=file,
            user=request.user,
            module=MODULE,
            object_type='legacy_upload',
            object_id='0',
            config=UpgradeAttachmentConfig,
        )
        if error:
            return json_response(error=error)
        return json_response({'url': f'/{att.file_path}'})
