# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度管理视图：制度文件、草稿、编辑会话、发布版本、预览文件与 ONLYOFFICE 编辑

接口约定（nginx 对外前缀 /api/institution/）。多文件模型（2026-10-29）：
文件级路由挂在 manuals/<pk>/files/<fid>/ 下，每个请求先校验文件确属
当前制度；旧单文件路由（manuals/<pk>/draft|originals/...）在过渡期
委托唯一启用文件，多文件制度明确拒绝。

  GET    /manuals/<pk>/files/                     待发布文件清单（含草稿/占用状态）
  POST   /manuals/<pk>/files/create/              新增文件（multipart，建条目+原稿+草稿）
  POST   /manuals/<pk>/files/<fid>/rename/        文件改名
  POST   /manuals/<pk>/files/<fid>/move/          文件排序（position 目标序位）
  POST   /manuals/<pk>/files/<fid>/remove/        移除出待发布集合
  GET    /manuals/<pk>/files/<fid>/originals/     文件原稿列表
  POST   /manuals/<pk>/files/<fid>/originals/upload/   上传原稿
  GET    /manuals/<pk>/files/<fid>/originals/<oid>/download/    下载原稿
  GET    /manuals/<pk>/files/<fid>/originals/<oid>/preview-url/ 预览原稿
  GET    /manuals/<pk>/files/<fid>/draft/         文件草稿信息
  POST   /manuals/<pk>/files/<fid>/draft/create/  草稿建立/恢复（优先级：已有草稿拒绝
                                                   > 当前生效版本快照 > 最近原稿；
                                                   original_id=明确的原稿重建，需确认）
  POST   /manuals/<pk>/files/<fid>/revision/start/ 开始修订（状态动作；工作副本
                                                   缺失/损坏/基线不一致时带
                                                   confirm_repair 从生效快照修复）
  POST   /manuals/<pk>/files/<fid>/draft/session/ 验证密码开启编辑会话
  DELETE /manuals/<pk>/files/<fid>/draft/session/ 主动退出编辑会话
  POST   /manuals/<pk>/files/<fid>/draft/save/    保存草稿（multipart，校验修订序号）
  GET    /manuals/<pk>/files/<fid>/draft/download/     下载草稿
  GET    /manuals/<pk>/files/<fid>/draft/preview-url/  预览草稿地址
  GET    /manuals/<pk>/files/<fid>/draft/editor-config/  ONLYOFFICE 编辑配置
  POST   /manuals/<pk>/draft/from-version/        整套回退（按版本快照重建草稿集合）
  GET    /manuals/<pk>/draft-status/              草稿状态总览（编制/发布角色；
                                                   草稿 vs 生效版本 + 整套摘要）
  POST   /manuals/<pk>/publish/                   整套发布（变更说明必填）
  GET    /manuals/<pk>/publish-preview/           发布前预检（分组发布计划）
  GET    /manuals/<pk>/versions/                  版本列表（含文件快照清单）
  GET    /manuals/<pk>/versions/<vid>/files/      版本文件快照清单（含变更状态）
  GET    /manuals/<pk>/versions/<vid>/files/<sfid>/download/    下载快照
  GET    /manuals/<pk>/versions/<vid>/files/<sfid>/preview-url/ 预览快照
  GET    /manuals/<pk>/versions/<vid>/download/   旧接口：委托唯一快照，多文件拒绝
  GET    /manuals/<pk>/versions/<vid>/preview-url/ 同上
  POST   /manuals/<pk>/deprecate/                 废止当前生效版本
  GET    /manuals/<pk>/attachments/<kind>-<id>/preview-file/   文件流（preview_token）
  GET    /manuals/<pk>/files/<fid>/attachments/oo-editor-file/     DS 取草稿文件
  POST   /manuals/<pk>/files/<fid>/attachments/oo-editor-callback/ DS 保存回调

两套外部访问通道互不复用：
- preview-file 路由不加 @auth：由 AuthenticationMiddleware 依据短时效
  preview_token（固定 300s）认证；视图内再对令牌绑定关系、文件归属与
  手册角色做二次校验。kkFileView 回源与浏览器原生预览共用。
- oo-editor-file / oo-editor-callback 供 ONLYOFFICE 文档服务（DS）使用，
  请求不携带 x-token，路径在 AUTHENTICATION_EXCLUDES 中豁免认证，由
  视图自行校验 editor_token / 回调 JWT；URL 中的文件 ID 与 document.key
  中的文件 ID 交叉核对。DS 保存遵循官方 JSON 回调协议（status 2/6 落盘、
  JWT 载荷即权威 body、users 数组归属账号），与手动编辑的 multipart
  降级路径（files/<fid>/draft/save）共享会话+修订序号保护。
"""
import base64
import json
import logging
import os
from urllib.parse import quote

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.generic import View

from apps.evidence.attachment_preview_token import (
    generate_attachment_preview_token, validate_attachment_preview_token)
from apps.logs.audit import record_audit_event
from libs import Argument, JsonParser, auth, json_response
from libs.pagination import paginate

from . import editor_services, serializers, services, storage, version_compare
from .models import (Manual, ManualDraft, ManualFile, ManualOriginal,
                     ManualVersion, ManualVersionFile)
from .views import _download_response, _manual_from_request
from .views_files import (_assignment_payload, _can_view_workspace,
                          _file_from_request, _session_payload)

logger = logging.getLogger(__name__)

# 编辑服务令牌有效期（下载文件/回调保存）
EDITOR_TOKEN_MAX_AGE = 600
# 注意：attachment_preview_token 载荷固定 6 段冒号分隔，object_id 内
# 不能再用冒号，复合键统一用 '-' 连接（session_key 为纯 hex 无 '-'）


def build_editor_token(manual, file_entry, draft, user):
    """生成 DS 取文件用的 editor_token（绑定制度+文件+修订序号+签发人）

    校验方见 OoEditorFileView；修订号变化即失效（DS 须重新取配置）。
    """
    return generate_attachment_preview_token(
        attachment_id=draft.id, user_id=user.id, tenant_id='',
        module=storage.PREVIEW_MODULE, object_type='editor_draft',
        object_id=f'{manual.id}-{file_entry.id}-{draft.revision}')


def _build_preview_url(request, manual, file_kind, obj, stored_name,
                       file_name=None):
    """生成 kkFileView 在线预览地址与短时效令牌

    fullfilename 用含 UUID 的存储文件名，避免 kkFileView 同名缓存串键。
    """
    preview_token = generate_attachment_preview_token(
        attachment_id=obj.id, user_id=request.user.id, tenant_id='',
        module=storage.PREVIEW_MODULE, object_type=file_kind,
        object_id=str(obj.id))
    preview_file_api_path = (
        f'/api/institution/manuals/{manual.id}/attachments/'
        f'{file_kind}-{obj.id}/preview-file/'
    )
    kkfileview_api_url = getattr(settings, 'KKFILEVIEW_API_URL', '')
    kkfileview_server_url = getattr(settings, 'KKFILEVIEW_SERVER_URL', '')
    if not kkfileview_api_url or not kkfileview_server_url:
        return None
    file_url = (
        f'{kkfileview_server_url}{preview_file_api_path}'
        f'?preview_token={quote(preview_token)}'
        f'&fullfilename={quote(stored_name)}'
    )
    encoded_url = base64.b64encode(file_url.encode('utf-8')).decode('utf-8')
    return {
        'preview_url': f'{kkfileview_api_url}/onlinePreview?url={encoded_url}',
        'file_name': file_name if file_name is not None else obj.original_name,
        'preview_type': 'kkfileview',
    }


def _draft_missing_response(file_entry):
    """草稿缺失的业务错误响应：error + draft_recovery（HTTP 200）

    draft_recovery 顶层字段说明恢复途径（source=current_version/original、
    version_no、requires_confirm），供 API 消费方与测试读取；浏览器端由
    拦截器以 error 文本提示一次，前端恢复入口以 files/ 清单行的
    draft_recovery 为准渲染。
    """
    hint = services.build_draft_recovery_hint(file_entry)
    if hint['source'] == 'current_version':
        message = (f'当前文件没有草稿，'
                   f'请从当前生效版本（v{hint["version_no"]}）恢复草稿')
    else:
        message = '当前文件没有草稿，请从初始原稿创建草稿或在版本历史中回退'
    return HttpResponse(
        json.dumps({'error': message, 'data': '', 'draft_recovery': hint},
                   ensure_ascii=False),
        content_type='application/json')


def _draft_or_error(file_entry):
    """取文件草稿；无草稿返回携带 draft_recovery 的业务错误响应"""
    draft = ManualDraft.objects.filter(file=file_entry).first()
    if not draft or not draft.file_path:
        return None, _draft_missing_response(file_entry)
    return draft, None


# ---------------------------------------------------------------------------
# 文件草稿（文件级会话 / 保存 / 下载 / 预览 / 编辑配置）


class FileDraftDetailView(View):
    @auth('institution.manual.draft_edit')
    def get(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not services.can_edit_draft(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        draft, err = _draft_or_error(file_entry)
        if err:
            return err
        data = serializers.to_draft_dict(draft)
        data['file'] = serializers.to_manual_file_dict(
            file_entry, draft, _session_payload(file_entry, request),
            assignment=_assignment_payload(file_entry, request),
            submission=services.file_submission_state(file_entry, draft))
        data['active_session'] = _session_payload(file_entry, request)
        return json_response(data=data)


class FileDraftCreateView(View):
    """文件草稿建立/恢复入口（严格优先级，原稿不得成为默认恢复来源）

    默认（不传 original_id）按以下优先级执行：
    1. 当前文件已有草稿 -> 拒绝（请继续编辑或明确执行重建，不得无提示覆盖）
    2. 无草稿且制度有当前生效版本 -> 从当前生效版本中该文件的
       ManualVersionFile 快照恢复草稿（base_version=来源版本；当前版本
       不含该文件时明确报错，绝不静默改用原稿补齐）
    3. 无草稿且制度从未发布过版本 -> 从该文件最近一次原稿创建草稿

    显式重建（传 original_id）：「从原始上传文件重建草稿」高级操作。
    制度发布过版本（含已废止）时必须 confirm=true 二次确认；将丢弃当前
    草稿内容时还需通过编辑密码校验（未配置密码的手册跳过密码项）；
    存在活跃编辑会话时一律拒绝。操作记录含来源原稿 ID、重建前修订号、
    当前发布版本号与操作账号；原稿记录与历史版本永不删除或改写。
    """

    def _recover_missing_draft(self, manual, file_entry, user):
        """无草稿时的默认恢复（严格优先级）：版本快照 > 废止拒绝 > 最近可用原稿

        Returns:
            tuple: (draft 或 None, action_kind 或 None, 错误响应或 None)
        """
        if manual.current_version:
            draft, err = services.restore_draft_from_current_version(
                file_entry, user)
            if err:
                return None, None, json_response(error=err)
            return draft, services.ACTION_RESTORE_DRAFT, None
        if services.has_published_versions(manual):
            # 有历史版本但无生效版本（已废止）：基线缺失，不静默回原稿
            return None, None, json_response(error=(
                '制度已发布过版本但当前无生效版本，请在版本历史中回退，'
                '或使用「从原始上传文件重建草稿」高级恢复操作'))
        original = file_entry.originals.filter(
            cleaned_at__isnull=True).order_by('-id').first()
        if not original:
            if file_entry.originals.exists():
                return None, None, json_response(error=(
                    '该文件的初始原稿已按保留策略清理（仅存来源元数据），'
                    '不能创建草稿；请为该文件更换来源（上传新原稿）后重试'))
            return None, None, json_response(error='请先上传原稿再创建草稿')
        draft, err = services.create_draft_from_original(
            file_entry, original, user)
        if err:
            return None, None, json_response(error=err)
        return draft, services.ACTION_CREATE_DRAFT, None

    @auth('institution.manual.draft_edit')
    def post(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not (services.can_manage_manual(request.user) or
                services.can_edit_draft(request.user, manual)):
            return json_response(error='手册不存在或无权限访问')
        if manual.status != Manual.STATUS_ACTIVE:
            return json_response(error='手册已归档，不能编辑')
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        form, error = JsonParser(
            Argument('original_id', type=int, required=False, default=None),
            Argument('confirm', type=bool, required=False, default=False),
            Argument('password', type=str, required=False, default=None),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        existing = ManualDraft.objects.filter(file=file_entry).first()
        if form.original_id:
            return self._rebuild_from_original(
                request, manual, file_entry, existing, form)
        if existing and existing.file_path:
            return json_response(
                error='当前文件已有草稿，请继续编辑或明确执行重建')
        # 无草稿（含空草稿脏行）：按优先级恢复
        draft, action_kind, err = self._recover_missing_draft(
            manual, file_entry, request.user)
        if err:
            return err
        record_audit_event(
            request, 'update', services.AUDIT_TARGET_TYPE,
            target_id=manual.id, target_name=manual.name,
            detail={'action_kind': action_kind,
                    'file_id': file_entry.id, 'revision': draft.revision,
                    'module': 'institution'})
        return json_response(data=serializers.to_draft_dict(draft))

    def _rebuild_from_original(self, request, manual, file_entry, existing, form):
        """明确的「从原始上传文件重建草稿」（original_id 已传）"""
        original = ManualOriginal.objects.filter(
            pk=form.original_id, manual=manual, file=file_entry).first()
        if not original:
            return json_response(error='原稿不存在或无权限访问')
        if original.cleaned_at:
            return json_response(error=storage.ORIGINAL_CLEANED_ERROR)
        if services.has_published_versions(manual):
            if services.get_active_session_for_file(file_entry):
                return json_response(error=(
                    '该文件有进行中的编辑会话，不能重建草稿；请先退出会话再执行'))
            if not form.confirm:
                return json_response(error=(
                    '该制度已发布过版本：从原始上传文件重建草稿会以原始文件'
                    '替换当前草稿，属高风险操作，请携带二次确认（confirm）执行'))
            if existing and existing.file_path and manual.password_hash:
                if form.password is None:
                    return json_response(error=(
                        '从原始上传文件重建草稿会丢弃当前草稿内容，'
                        '请输入编辑密码确认后执行'))
                ok, err = services.verify_manual_password(manual, form.password)
                if not ok:
                    return json_response(error=err)
        draft, err = services.create_draft_from_original(
            file_entry, original, request.user, log_detail={
                'rebuild_from_original': True,
                'previous_revision': existing.revision if existing else None,
                'current_version_no': (
                    manual.current_version.version_no
                    if manual.current_version else None),
            })
        if err:
            return json_response(error=err)
        record_audit_event(
            request, 'update', services.AUDIT_TARGET_TYPE,
            target_id=manual.id, target_name=manual.name,
            detail={'action_kind': services.ACTION_CREATE_DRAFT,
                    'file_id': file_entry.id, 'revision': draft.revision,
                    'source_original_id': original.id, 'rebuild': True,
                    'module': 'institution'})
        return json_response(data=serializers.to_draft_dict(draft))


class FileDraftSessionView(View):
    """验证编辑密码开启该文件的会话（文件级单写）；DELETE 主动退出"""

    @auth('institution.manual.draft_edit')
    def post(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not services.can_edit_draft(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        if manual.status != Manual.STATUS_ACTIVE:
            return json_response(error='手册已归档，不能编辑')
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        draft, err = _draft_or_error(file_entry)
        if err:
            return err
        form, error = JsonParser(
            Argument('password', type=str, required=True, help='请输入编辑密码'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        ok, err = services.verify_manual_password(manual, form.password)
        if not ok:
            return json_response(error=err)
        session, err = services.start_edit_session(file_entry, request.user)
        if err:
            return json_response(error=err)
        services.log_operation(
            manual, request.user, services.ACTION_SESSION_START,
            file=file_entry, file_id=file_entry.id,
            session_key=session.session_key, file_revision=draft.revision)
        return json_response(data=serializers.to_session_dict(session, draft))

    @auth('institution.manual.draft_edit')
    def delete(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        form, error = JsonParser(
            Argument('session_key', type=str, required=True, help='缺少会话标识'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        session = file_entry.edit_sessions.filter(
            session_key=form.session_key, user=request.user,
            revoked_at__isnull=True).first()
        if session:
            session.revoked_at = timezone.now()
            session.revoked_reason = '用户主动退出'
            session.save(update_fields=['revoked_at', 'revoked_reason'])
        return json_response()


class FileDraftSaveView(View):
    """保存文件草稿：会话有效 + 修订序号一致才接受；文件先行，失败补偿"""

    @auth('institution.manual.draft_edit')
    @transaction.atomic
    def post(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not services.can_edit_draft(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        draft, err = _draft_or_error(file_entry)
        if err:
            return err
        session_key = request.POST.get('session_key', '')
        revision = request.POST.get('revision', '')
        session, err = services.get_active_session(
            file_entry, request.user, session_key)
        if err:
            return json_response(error=err)
        if str(revision) != str(draft.revision):
            return json_response(error='草稿已被其他会话更新，请刷新草稿后重试')
        upload = request.FILES.get('file')
        if not upload:
            return json_response(error='请选择要保存的文件')
        ext = storage.extract_extension(upload.name)
        if ext != '.docx':
            return json_response(error='草稿工作文件必须是 .docx 格式')
        if upload.size > storage.MAX_FILE_SIZE:
            return json_response(error='文件大小超过限制（100MB）')
        draft, err = services.save_file_draft(
            file_entry, request.user, upload, int(revision))
        if err:
            return json_response(error=err)
        services.touch_session(session)
        record_audit_event(
            request, 'update', services.AUDIT_TARGET_TYPE,
            target_id=manual.id, target_name=manual.name,
            detail={'action_kind': services.ACTION_SAVE_DRAFT,
                    'file_id': file_entry.id, 'file_revision': draft.revision,
                    'module': 'institution'})
        return json_response(data=serializers.to_draft_dict(draft))


class FileDraftDownloadView(View):
    @auth('institution.manual.download')
    def get(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not services.can_edit_draft(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        draft, err = _draft_or_error(file_entry)
        if err:
            return err
        services.log_operation(
            manual, request.user, 'download', file=file_entry,
            file_name=draft.original_name, file_kind='draft',
            file_id=file_entry.id)
        abs_path = storage.resolve_absolute_path(draft.file_path)
        return _download_response(request, abs_path, draft.original_name)


class FileDraftPreviewUrlView(View):
    @auth('institution.manual.draft_edit')
    def get(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not services.can_edit_draft(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        draft, err = _draft_or_error(file_entry)
        if err:
            return err
        data = _build_preview_url(
            request, manual, storage.FILE_KIND_DRAFT, draft, draft.original_name)
        if not data:
            return json_response(error='Office文档预览服务未配置，请联系管理员')
        return json_response(data=data)


class OriginalPreviewUrlView(View):
    @auth('institution.manual.view')
    def get(self, request, pk, oid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        original = ManualOriginal.objects.filter(pk=oid, manual=manual).first()
        if not original:
            return json_response(error='原稿不存在或无权限访问')
        if original.cleaned_at:
            return json_response(error=storage.ORIGINAL_CLEANED_ERROR)
        data = _build_preview_url(
            request, manual, storage.FILE_KIND_ORIGINAL, original,
            original.original_name)
        if not data:
            return json_response(error='Office文档预览服务未配置，请联系管理员')
        return json_response(data=data)


class DraftFromVersionView(View):
    """整套回退：以历史版本的快照清单重建待发布草稿集合"""

    @auth('institution.manual.draft_edit')
    def post(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not (services.can_manage_manual(request.user) or
                services.can_edit_draft(request.user, manual)):
            return json_response(error='手册不存在或无权限访问')
        form, error = JsonParser(
            Argument('version_id', type=int, required=True, help='请选择要回退的版本'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        version = ManualVersion.objects.filter(
            pk=form.version_id, manual=manual).first()
        if not version:
            return json_response(error='版本不存在或无权限访问')
        restored, err = services.rollback_to_version(manual, version, request.user)
        if err:
            return json_response(error=err)
        record_audit_event(
            request, 'update', services.AUDIT_TARGET_TYPE,
            target_id=manual.id, target_name=manual.name,
            detail={'action_kind': services.ACTION_ROLLBACK,
                    'from_version_no': version.version_no,
                    'restored_files': restored, 'module': 'institution'})
        return json_response(data={
            'restored_files': restored, 'from_version_no': version.version_no})


# ---------------------------------------------------------------------------
# 过渡期旧单文件 API（委托唯一启用文件；多文件制度明确拒绝）


def _delegate_file_view(file_view_cls, request, pk, *args, **kwargs):
    """旧路由 -> 唯一启用文件 -> 文件级视图"""
    manual, resp = _manual_from_request(request, pk)
    if resp:
        return resp
    file_entry, err = services.get_single_active_file(manual)
    if err:
        return json_response(error=err)
    return file_view_cls.as_view()(request, pk, file_entry.id, *args, **kwargs)


class DraftDetailView(View):
    @auth('institution.manual.draft_edit')
    def get(self, request, pk):
        return _delegate_file_view(FileDraftDetailView, request, pk)


class DraftCreateView(View):
    @auth('institution.manual.draft_edit')
    def post(self, request, pk):
        return _delegate_file_view(FileDraftCreateView, request, pk)


class DraftSessionView(View):
    @auth('institution.manual.draft_edit')
    def post(self, request, pk):
        return _delegate_file_view(FileDraftSessionView, request, pk)

    @auth('institution.manual.draft_edit')
    def delete(self, request, pk):
        return _delegate_file_view(FileDraftSessionView, request, pk)


class DraftSaveView(View):
    @auth('institution.manual.draft_edit')
    def post(self, request, pk):
        return _delegate_file_view(FileDraftSaveView, request, pk)


class DraftDownloadView(View):
    @auth('institution.manual.download')
    def get(self, request, pk):
        return _delegate_file_view(FileDraftDownloadView, request, pk)


class DraftPreviewUrlView(View):
    @auth('institution.manual.draft_edit')
    def get(self, request, pk):
        return _delegate_file_view(FileDraftPreviewUrlView, request, pk)


class EditorConfigView(View):
    @auth('institution.manual.draft_edit')
    def get(self, request, pk):
        return _delegate_file_view(FileEditorConfigView, request, pk)


# ---------------------------------------------------------------------------
# 发布与版本（整套发布；版本携带有序文件快照清单）


class PublishView(View):
    """整套发布：全部启用文件快照成功后才切换当前版本

    本视图在 urls.py 以 transaction.non_atomic_requests 注册——快照
    物理复制（长阻塞 IO）不得占用 ATOMIC_REQUESTS 事务；发布三段式
    （行锁校验 -> 事务外复制 -> 行锁落库）由 publish_whole_set 管理，
    任一步失败旧生效版保持完整。
    """

    @auth('institution.manual.publish')
    def post(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not services.can_publish(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        if manual.status != Manual.STATUS_ACTIVE:
            return json_response(error='手册已归档，不能发布')
        form, error = JsonParser(
            Argument('change_note', type=str, required=True, help='请填写变更说明'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        change_note = form.change_note.strip()
        if not change_note:
            return json_response(error='请填写变更说明')
        version, err = services.publish_whole_set(manual, request.user, change_note)
        if err:
            return json_response(error=err)
        manual.refresh_from_db()
        record_audit_event(
            request, 'create', services.AUDIT_TARGET_TYPE,
            target_id=manual.id, target_name=manual.name,
            detail={'action_kind': services.ACTION_PUBLISH,
                    'version_no': version.version_no,
                    'file_count': version.files.count(), 'module': 'institution'})
        return json_response(data=serializers.to_version_dict(version, manual))


class VersionListView(View):
    @auth('institution.manual.view')
    def get(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not services.can_view_published(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        qs = manual.versions.select_related('published_by').prefetch_related(
            'files__manual_file').all()
        page, page_size = paginate(request, default_page_size=20, max_page_size=100)
        total = qs.count()
        items = qs[(page - 1) * page_size: page * page_size]
        return json_response(data={
            'total': total, 'page': page, 'page_size': page_size,
            'items': [serializers.to_version_dict(v, manual) for v in items],
        })


class VersionFilesListView(View):
    """某版本的完整有序文件快照清单（历史版本展示当时的文件集合）

    items 为本版本全部快照行，每行附服务端计算的 change_type（added/
    modified/unchanged）、is_changed_from_previous、latest_changed_version_no
    与 latest_changed_at（截至本版本文件内容最近一次变化的版本）；
    removed_items 为上一版本存在、本版本移除的文件（附上一版快照定位），
    不静默隐藏。变更状态全部由版本快照与哈希比较得出。
    """

    @auth('institution.manual.view')
    def get(self, request, pk, vid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not services.can_view_published(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        version = ManualVersion.objects.filter(pk=vid, manual=manual).first()
        if not version:
            return json_response(error='版本不存在或无权限访问')
        computed = version_compare.compute_version_changes(manual, version)
        items = []
        for snapshot in version.files.order_by('sort_order', 'id'):
            row = serializers.to_version_file_dict(snapshot)
            row.update(computed['by_file'].get(snapshot.manual_file_id) or {})
            items.append(row)
        return json_response(data={
            'version_id': version.id,
            'version_no': version.version_no,
            'change_note': version.change_note,
            'previous_version_no': computed['previous_version_no'],
            'items': items,
            'removed_items': computed['removed_items'],
        })


class FileVersionHistoryView(View):
    """某制度文件的逐版本发布参与记录（"文件变更记录"页签数据源）

    权限沿用发布域（can_view_published）：发布历史属于已发布内容。
    变更状态全部由版本快照 SHA256 服务端计算，前端不得推断。
    """

    @auth('institution.manual.view')
    def get(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not services.can_view_published(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        items = version_compare.compute_file_version_history(manual, file_entry)
        return json_response(data={
            'file_id': file_entry.id,
            'file_name': file_entry.display_name,
            'items': items,
        })


class DraftStatusView(View):
    """草稿状态总览（只读）：逐份文件 草稿 vs 当前生效版本 + 整套摘要

    面向草稿工作区与详情页头部摘要。权限口径与待发布文件清单一致
    （_can_view_workspace：编制/发布角色或模块管理权限）——编制者无需
    调用仅发布角色可用的 publish-preview；仅查看角色的账号不可见草稿
    信息。关系与整套待发布变化（修改/新增/移除/改名/排序）全部由
    服务端按快照哈希/名称/序位计算（version_compare.build_draft_status），
    前端不得以修订号或文件名推断。编辑会话占用或草稿文件缺失时该文件
    状态为 unconfirmed（暂不能确认），不得当作"无变化"。本状态只是
    只读展示，不是发布放行凭证；发布预检用 publish-preview（发布域），
    权威校验在 publish_whole_set。
    """

    @auth('institution.manual.view')
    def get(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not _can_view_workspace(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        return json_response(
            data=version_compare.build_draft_status(manual, request.user))


class PublishPreviewView(View):
    """发布前预检（只读）：返回整套发布计划的分组清单

    以草稿哈希与当前生效版快照逐文件比较，分组为 changed/unchanged/
    added/removed/blocked（无草稿/草稿缺失/编辑会话占用），供发布确认
    窗口展示；分组结果不是放行凭证，发布仍以 publish_whole_set 的
    行锁内复核为权威。
    """

    @auth('institution.manual.view')
    def get(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not services.can_publish(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        if manual.status != Manual.STATUS_ACTIVE:
            return json_response(error='手册已归档，不能发布')
        return json_response(
            data=version_compare.build_publish_plan(manual, request.user))


class VersionFileDownloadView(View):
    @auth('institution.manual.download')
    def get(self, request, pk, vid, sfid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not services.can_view_published(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        snapshot = ManualVersionFile.objects.filter(
            pk=sfid, version_id=vid, version__manual=manual).first()
        if not snapshot:
            return json_response(error='版本文件不存在或无权限访问')
        if snapshot.cleaned_at:
            return json_response(error='该文件已按保留策略清理，仅存清单与哈希元数据')
        services.log_operation(
            manual, request.user, 'download', version=snapshot.version,
            file_name=snapshot.display_name, file_kind='version_file',
            version_no=snapshot.version.version_no, file_id=snapshot.manual_file_id)
        abs_path = storage.resolve_absolute_path(snapshot.file_path)
        return _download_response(request, abs_path, snapshot.display_name)


class VersionFilePreviewUrlView(View):
    @auth('institution.manual.view')
    def get(self, request, pk, vid, sfid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not services.can_view_published(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        snapshot = ManualVersionFile.objects.filter(
            pk=sfid, version_id=vid, version__manual=manual).first()
        if not snapshot:
            return json_response(error='版本文件不存在或无权限访问')
        if snapshot.cleaned_at:
            return json_response(error='该文件已按保留策略清理，仅存清单与哈希元数据')
        data = _build_preview_url(
            request, manual, storage.FILE_KIND_VERSION_FILE, snapshot,
            snapshot.display_name, file_name=snapshot.display_name)
        if not data:
            return json_response(error='Office文档预览服务未配置，请联系管理员')
        return json_response(data=data)


class _VersionSingleSnapshotMixin:
    """旧单文件版本接口委托：唯一快照原样透传，多文件版本明确拒绝"""

    def _get_snapshot(self, request, manual, vid):
        version = ManualVersion.objects.filter(pk=vid, manual=manual).first()
        if not version:
            return None, json_response(error='版本不存在或无权限访问')
        snapshots = list(version.files.order_by('sort_order', 'id'))
        if len(snapshots) != 1:
            return None, json_response(
                error='该版本包含多份文件，请使用版本文件清单逐份下载或预览')
        if snapshots[0].cleaned_at:
            return None, json_response(
                error='该文件已按保留策略清理，仅存清单与哈希元数据')
        return snapshots[0], None


class VersionDownloadView(_VersionSingleSnapshotMixin, View):
    @auth('institution.manual.download')
    def get(self, request, pk, vid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not services.can_view_published(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        snapshot, resp = self._get_snapshot(request, manual, vid)
        if resp:
            return resp
        services.log_operation(
            manual, request.user, 'download',
            file_name=snapshot.display_name, file_kind='version',
            version_no=snapshot.version.version_no)
        abs_path = storage.resolve_absolute_path(snapshot.file_path)
        return _download_response(request, abs_path, snapshot.display_name)


class VersionPreviewUrlView(_VersionSingleSnapshotMixin, View):
    @auth('institution.manual.view')
    def get(self, request, pk, vid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not services.can_view_published(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        snapshot, resp = self._get_snapshot(request, manual, vid)
        if resp:
            return resp
        data = _build_preview_url(
            request, manual, storage.FILE_KIND_VERSION, snapshot,
            snapshot.display_name, file_name=snapshot.display_name)
        if not data:
            return json_response(error='Office文档预览服务未配置，请联系管理员')
        return json_response(data=data)


class DeprecateView(View):
    @auth('institution.manual.publish')
    @transaction.atomic
    def post(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not services.can_publish(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        version, err = services.deprecate_current_version(manual, request.user)
        if err:
            return json_response(error=err)
        record_audit_event(
            request, 'update', services.AUDIT_TARGET_TYPE,
            target_id=manual.id, target_name=manual.name,
            detail={'action_kind': services.ACTION_DEPRECATE,
                    'version_no': version.version_no, 'module': 'institution'})
        return json_response(data=serializers.to_version_dict(version, manual))


# ---------------------------------------------------------------------------
# ONLYOFFICE Docs 在线编辑（文件级；DS 取文件 + 保存回调遵循官方 JSON 回调协议）


class FileEditorConfigView(View):
    """返回 ONLYOFFICE DocsAPI.DocEditor 所需配置（JWT 已签名，绑定文件）

    需要该文件的有效编辑会话（与 multipart 保存同一文件级单写约束）；
    未配置编辑服务时返回 editor_available=false，前端走下载→本机编辑
    →上传降级。
    """

    @auth('institution.manual.draft_edit')
    def get(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not services.can_edit_draft(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        if manual.status != Manual.STATUS_ACTIVE:
            return json_response(error='手册已归档，不能编辑')
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        draft, err = _draft_or_error(file_entry)
        if err:
            return err
        session_key = request.GET.get('session_key', '')
        session, err = services.get_active_session(
            file_entry, request.user, session_key)
        if err:
            return json_response(error=err)
        if not editor_services.is_editor_configured():
            return json_response(data={
                'editor_available': False,
                'note': 'ONLYOFFICE 文档服务未配置（ONLYOFFICE_DOCS_URL / '
                        'ONLYOFFICE_JWT_SECRET），请使用下载→本机编辑→上传保存。',
            })
        data = editor_services.build_editor_config(
            request, manual, file_entry, draft, session)
        data['session_key'] = session.session_key
        data['file_id'] = file_entry.id
        data['revision'] = draft.revision
        return json_response(data=data)


class OoEditorFileView(View):
    """DS 取草稿文件：editor_token 自认证（不依赖 x-token/preview_token）

    令牌绑定 制度+文件+草稿修订序号+签发人；URL 中的文件 ID 与令牌
    object_id 中的文件 ID 交叉核对，草稿在令牌签发后被保存过（修订号
    变化）则拒绝，DS 须让前端重新取编辑配置。
    """

    def get(self, request, pk, fid):
        token = request.GET.get('token', '')
        token_data = validate_attachment_preview_token(
            token, max_age=getattr(settings, 'ONLYOFFICE_EDITOR_TOKEN_TTL_SECONDS', 3600))
        if not token_data or token_data['module'] != storage.PREVIEW_MODULE:
            return JsonResponse({'error': 1}, status=403)
        if token_data['object_type'] != 'editor_draft':
            return JsonResponse({'error': 1}, status=403)
        manual = Manual.objects.filter(pk=pk).first()
        file_entry = ManualFile.objects.filter(pk=fid, manual=manual).first() if manual else None
        if not file_entry:
            return JsonResponse({'error': 1}, status=404)
        try:
            token_manual_id, token_file_id, token_revision = str(
                token_data['object_id']).split('-', 2)
        except ValueError:
            return JsonResponse({'error': 1}, status=403)
        if (int(token_manual_id) != manual.id or
                int(token_file_id) != file_entry.id):
            return JsonResponse({'error': 1}, status=403)
        draft = ManualDraft.objects.filter(file=file_entry).first()
        if not draft or str(draft.revision) != token_revision:
            return JsonResponse({'error': 1}, status=409)
        try:
            abs_path = storage.resolve_absolute_path(draft.file_path)
        except ValueError:
            return JsonResponse({'error': 1}, status=400)
        if not os.path.exists(abs_path):
            return JsonResponse({'error': 1}, status=404)
        response = FileResponse(open(abs_path, 'rb'))
        response['Content-Disposition'] = 'inline'
        return response


class OoEditorCallbackView(View):
    """DS 保存回调（官方 JSON 回调协议，绑定具体制度文件）

    校验链：回调 JWT（Authorization: Bearer 或 body.token）→ 载荷必须含
    status → 权威回调内容一律取自 JWT 载荷 → 载荷 key 解析出的
    制度/文件必须与路由一致 → users 数组归属账号 → 编制角色 + 该文件
    活跃编辑会话 → 回调 key 等于会话当前签发 key（迟到/旧实例拒绝）→
    修订号行锁复核落盘。
    返回 {"error": 0} 表示已处理；非 0 时 DS 会重试。

    注意：本视图在 urls.py 以 transaction.non_atomic_requests(as_view())
    注册——回调需先从 DS 下载文件（长阻塞外部调用），不得占用
    ATOMIC_REQUESTS 的事务；落盘原子性由 save_file_draft 自身的
    transaction.atomic 保证。
    """

    def post(self, request, pk, fid):
        manual = Manual.objects.filter(pk=pk).first()
        file_entry = ManualFile.objects.filter(pk=fid, manual=manual).first() \
            if manual else None
        if not file_entry:
            return JsonResponse({'error': 1}, status=404)
        payload, body, err = editor_services.parse_callback_request(request)
        if err:
            return err
        # status 冲突（未签名 body 与签名载荷不一致）先于 key 路由校验，
        # 维持既有 400 语义
        _, err = editor_services.authoritative_callback_body(payload, body)
        if err:
            return err
        # 载荷 key 解析出的制度/文件必须与路由一致，防止跨文件冒用；
        # key 缺失/不可解析 = 伪造或非回调语义，403 拒绝
        parsed = editor_services.parse_document_key(str(payload.get('key') or ''))
        if not parsed:
            logger.warning('[InstitutionEditor] callback key unparseable: %s',
                           str(payload.get('key'))[:40])
            return JsonResponse({'error': 1}, status=403)
        key_manual_id, key_file_id, _ = parsed
        if key_manual_id != manual.id or key_file_id != file_entry.id:
            logger.warning('[InstitutionEditor] callback key route mismatch '
                           'manual=%s file=%s key=(%s,%s)',
                           manual.id, file_entry.id, key_manual_id, key_file_id)
            return JsonResponse({'error': 1}, status=409)
        return editor_services.process_editor_callback(
            manual, file_entry, payload, body)


# ---------------------------------------------------------------------------
# preview-file 文件流（preview_token 认证；视图内二次校验绑定与角色）


def _token_matches(token_data, expect_type, obj_id):
    """校验 token 的 module/object_type/object_id 与请求对象一致"""
    if token_data['module'] != storage.PREVIEW_MODULE:
        return False
    if token_data['object_type'] != expect_type:
        return False
    if str(token_data['object_id']) != str(obj_id):
        return False
    return True


def _resolve_preview_object(kind, obj_id, manual, user):
    """按文件类别取预览对象并做角色与归属校验；无权/不存在返回 None

    draft/vfile 归属校验以对象自身的 file/version 链反查手册，防止
    改文件 ID 后读取别的制度。
    """
    if kind == storage.FILE_KIND_ORIGINAL:
        obj = ManualOriginal.objects.filter(pk=obj_id, manual=manual).first()
        if obj and not services.can_view_manual(user, manual):
            obj = None
        return obj
    if kind == storage.FILE_KIND_VERSION:
        obj = ManualVersion.objects.filter(pk=obj_id, manual=manual).first()
        if obj and not services.can_view_published(user, manual):
            obj = None
        return obj
    if kind == storage.FILE_KIND_VERSION_FILE:
        obj = ManualVersionFile.objects.filter(
            pk=obj_id, version__manual=manual).first()
        if obj and not services.can_view_published(user, manual):
            obj = None
        return obj
    if kind == storage.FILE_KIND_DRAFT:
        obj = ManualDraft.objects.filter(
            pk=obj_id, file__manual=manual).first()
        if obj and not services.can_edit_draft(user, manual):
            obj = None
        return obj
    return None


class ManualFilePreviewFileView(View):
    """原稿/版本/版本快照/草稿文件流；kkFileView 回源与浏览器原生预览共用"""

    def get(self, request, pk, key):
        token = request.GET.get('preview_token', '')
        token_data = validate_attachment_preview_token(token)
        if not token_data or token_data['module'] != storage.PREVIEW_MODULE:
            return json_response(error='预览令牌无效或已过期')
        manual = Manual.objects.filter(pk=pk).first()
        if not manual:
            return json_response(error='预览对象不存在')
        parts = key.split('-', 1)
        if len(parts) != 2 or not parts[1].isdigit():
            return json_response(error='预览对象不存在')
        kind, obj_id = parts[0], int(parts[1])
        if kind not in (storage.FILE_KIND_ORIGINAL, storage.FILE_KIND_VERSION,
                        storage.FILE_KIND_DRAFT,
                        storage.FILE_KIND_VERSION_FILE):
            return json_response(error='预览对象不存在')
        if not _token_matches(token_data, kind, obj_id):
            return json_response(error='预览令牌与对象不匹配')
        obj = _resolve_preview_object(kind, obj_id, manual, request.user)
        if not obj:
            return json_response(error='预览对象不存在或无权限访问')
        if kind == storage.FILE_KIND_ORIGINAL and obj.cleaned_at:
            return json_response(error=storage.ORIGINAL_CLEANED_ERROR)
        if (kind in (storage.FILE_KIND_VERSION, storage.FILE_KIND_VERSION_FILE)
                and obj.cleaned_at):
            return json_response(error='该文件已按保留策略清理，仅存清单与哈希元数据')
        try:
            abs_path = storage.resolve_absolute_path(obj.file_path)
        except ValueError:
            return json_response(error='文件路径非法')
        if not os.path.exists(abs_path):
            return json_response(error='文件不存在或已被清理')
        response = FileResponse(open(abs_path, 'rb'))
        response['Content-Disposition'] = 'inline'
        return response
