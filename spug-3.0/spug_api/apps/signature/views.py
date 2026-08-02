# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""账号签名 - HTTP 视图

管理接口（/api/account/user/<user_id>/signature/...）：
    GET    查询当前签名及管理详情
    POST   首次赋予
    PUT    替换并生成新版本
    PATCH  /status/  停用或重新启用
    GET    /history/ 历史版本分页

所有管理接口第一层强制 request.user.is_supper is True。

普通用户接口：
    GET /api/signature/mine/    查询本人当前签名

受控预览接口：
    GET /api/signature/preview/<attachment_id>/?preview_token=...  返回 image/png 流
"""
import logging
import os

from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.views.generic import View

from libs import JsonParser, Argument, json_response
from apps.evidence.models import EvidenceAttachment

from . import services
from .models import STATUS_ACTIVE, STATUS_DISABLED

logger = logging.getLogger(__name__)


class SupperOnlyView(View):
    """所有管理写接口必须校验超级管理员身份。

    前端隐藏按钮只用于体验，后端是权限和数据真相来源。
    普通管理员和普通用户直接调用接口一律拒绝。
    """

    def dispatch(self, request, *args, **kwargs):
        if not getattr(request.user, 'is_supper', False):
            return json_response(error='权限拒绝：仅超级管理员可管理账号签名')
        return super().dispatch(request, *args, **kwargs)


class SignatureManageView(SupperOnlyView):
    """GET 详情 / POST 首次赋予 / PUT 替换"""

    def get(self, request, user_id):
        detail, error = services.get_signature_admin_detail(request.user, user_id)
        if error:
            return json_response(error=error)
        return json_response(detail)

    def post(self, request, user_id):
        return self._upload(request, user_id, allow_replace=False)

    def put(self, request, user_id):
        # Django 默认只为 POST 解析 multipart，PUT 需手动解析 request.FILES
        self._ensure_multipart_parsed(request)
        return self._upload(request, user_id, allow_replace=True)

    @staticmethod
    def _ensure_multipart_parsed(request):
        """Django 的 request.FILES/request.POST 只在 method=POST 时自动解析。

        PUT/PATCH 携带 multipart/form-data 时需手动触发解析，否则
        request.FILES 为空，无法接收上传文件。

        注意：不能先访问 request.FILES 再手动解析——首次访问 FILES 会触发
        _load_post_and_files 锁定 upload_handlers，之后 parse_file_upload
        会抛 "You cannot set the upload handlers after the upload has been processed"。
        因此直接检查 _files 是否已缓存且非空，避免触发锁定。
        """
        # 检查是否已经解析出文件（避免重复解析）；不直接访问 request.FILES 以免触发锁定
        cached_files = getattr(request, '_files', None)
        if cached_files:
            return
        content_type = request.META.get('CONTENT_TYPE', '')
        if 'multipart' not in content_type:
            return
        from io import BytesIO
        body_bytes = request.body
        if not body_bytes:
            return
        data = BytesIO(body_bytes)
        request._post, request._files = request.parse_file_upload(request.META, data)

    @staticmethod
    def _upload(request, user_id, allow_replace):
        file = request.FILES.get('file')
        if not file:
            return json_response(error='请上传签名图片')
        remark = request.POST.get('remark') or ''

        # 区分首次赋予 / 替换：根据当前是否已配置
        from .models import AccountSignature
        existing = AccountSignature.objects.filter(user_id=user_id).first()
        if existing and not allow_replace:
            return json_response(error='该账号已配置签名，请使用替换功能')
        if not existing and allow_replace:
            return json_response(error='该账号尚未配置签名，请先赋予')

        detail, error = services.set_signature(
            operator=request.user,
            target_user_id=user_id,
            image_file=file,
            remark=remark,
            request=request,
        )
        if error:
            return json_response(error=error)
        return json_response(detail)


class SignatureStatusView(SupperOnlyView):
    """PATCH /status/ 停用或重新启用"""

    def patch(self, request, user_id):
        form, error = JsonParser(
            Argument('status', help='请指定状态'),
            Argument('reason', required=False, default=''),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        if form.status == STATUS_DISABLED:
            detail, err = services.disable_signature(
                request.user, user_id, reason=form.reason, request=request)
        elif form.status == STATUS_ACTIVE:
            detail, err = services.enable_signature(request.user, user_id, request=request)
        else:
            return json_response(error='状态值非法，仅支持 active 或 disabled')
        if err:
            return json_response(error=err)
        return json_response(detail)


class SignatureHistoryView(SupperOnlyView):
    """GET /history/ 历史版本分页"""

    def get(self, request, user_id):
        try:
            page = int(request.GET.get('page', 1))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = int(request.GET.get('page_size', 20))
        except (TypeError, ValueError):
            page_size = 20
        data, error = services.list_signature_versions(request.user, user_id, page=page, page_size=page_size)
        if error:
            return json_response(error=error)
        return json_response(data)


class MySignatureView(View):
    """GET /api/signature/mine/ 普通用户只读查询本人当前签名

    只查询登录账号本人，不接受 user_id 参数。
    不提供 POST、PUT、PATCH 或 DELETE；普通用户不能通过参数查询其他 user_id。
    """

    def get(self, request):
        data = services.get_my_current_signature(request.user)
        return json_response(data)

    # 显式拒绝所有写方法，防止普通用户通过本端点写入签名数据
    def post(self, request, *args, **kwargs):
        return json_response(error='方法不允许')

    def put(self, request, *args, **kwargs):
        return json_response(error='方法不允许')

    def patch(self, request, *args, **kwargs):
        return json_response(error='方法不允许')

    def delete(self, request, *args, **kwargs):
        return json_response(error='方法不允许')


class SignaturePreviewView(View):
    """GET /api/signature/preview/<attachment_id>/?preview_token=...

    受控图片预览：
    - 复用 evidence 模块的 attachment_preview_token（短时效、附件作用域）
    - 中间件已校验 token 并设置 request.preview_token_data
    - 视图再次校验 token 与附件一致性，防止跨附件/跨租户/跨模块
    - 返回 image/png + inline + nosniff + 无公共缓存
    """

    def _validate_preview_attachment(self, token_data, url_attachment_id):
        """校验预览令牌与附件一致性。返回 (att, error_str)。error_str 为空表示通过。"""
        if not token_data:
            return None, '预览令牌无效或已过期'
        try:
            url_attachment_id = int(url_attachment_id)
        except (TypeError, ValueError):
            return None, '预览请求非法'
        if token_data.get('attachment_id') != url_attachment_id:
            logger.warning(
                '[Signature] preview token attachment_id mismatch: token=%s, url=%s',
                token_data.get('attachment_id'), url_attachment_id,
            )
            return None, '预览令牌与请求附件不匹配'

        att = EvidenceAttachment.objects.filter(pk=url_attachment_id).first()
        if not att:
            return None, '签名附件不存在'
        if att.is_deleted:
            return None, '签名附件已删除'
        if (att.module != services.SIGNATURE_MODULE
                or att.object_type != services.SIGNATURE_OBJECT_TYPE):
            logger.warning(
                '[Signature] preview token used for non-signature attachment: %s',
                url_attachment_id,
            )
            return None, '预览令牌无效'
        if str(att.object_id) != str(token_data.get('object_id') or ''):
            logger.warning(
                '[Signature] preview token object_id mismatch: token=%s, db=%s',
                token_data.get('object_id'), att.object_id,
            )
            return None, '预览令牌无效'
        return att, ''

    def _resolve_preview_file_path(self, att):
        """校验预览文件路径安全与存在。返回 (file_real, error_str)。"""
        full_path = os.path.join(settings.MEDIA_ROOT, att.file_path)
        media_real = os.path.realpath(settings.MEDIA_ROOT)
        file_real = os.path.realpath(full_path)
        if not (file_real == media_real or file_real.startswith(media_real + os.sep)):
            logger.error('[Signature] preview path outside MEDIA_ROOT: %s', att.file_path)
            return None, '文件不存在'
        if not os.path.exists(file_real):
            logger.warning('[Signature] preview file missing: %s', att.file_path)
            return None, '签名文件不存在'
        return file_real, ''

    def get(self, request, attachment_id):
        token_data = getattr(request, 'preview_token_data', None)
        att, err = self._validate_preview_attachment(token_data, attachment_id)
        if err:
            return self._reject(err)
        file_real, err = self._resolve_preview_file_path(att)
        if err:
            return self._reject(err)

        try:
            response = FileResponse(open(file_real, 'rb'), content_type='image/png')
        except OSError:
            return self._reject('签名文件读取失败')

        response['Content-Disposition'] = 'inline; filename="signature.png"'
        response['Content-Length'] = os.path.getsize(file_real)
        # 防止 MIME 嗅探
        response['X-Content-Type-Options'] = 'nosniff'
        # 签名图片默认不做公共缓存
        response['Cache-Control'] = 'private, no-store, max-age=0'
        return response

    @staticmethod
    def _reject(message):
        response = HttpResponse(message, content_type='text/plain; charset=utf-8', status=403)
        response['X-Content-Type-Options'] = 'nosniff'
        return response
