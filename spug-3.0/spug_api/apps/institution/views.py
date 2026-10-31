# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度管理视图：类别、手册、密码、原稿、旧章节（只读）、操作记录

接口约定（nginx 对外前缀 /api/institution/）：
  GET    /categories/                        查看类别（institution.manual.view）
  POST   /categories/                        新建类别（institution.manual.config）
  PUT    /categories/<pk>/                   编辑类别（institution.manual.config）
  DELETE /categories/<pk>/                   删除类别（institution.manual.config）
  GET    /manuals/                           手册列表（所有者/逐本授权过滤）
  POST   /manuals/create/                    新建手册（institution.manual.add；创建人=所有者）
  GET    /manuals/<pk>/                      手册详情
  PUT    /manuals/<pk>/                      编辑手册元数据/状态（institution.manual.edit）
  DELETE /manuals/<pk>/                      删除手册（institution.manual.delete）
  PUT    /manuals/<pk>/password/             设置/重置编辑密码（institution.manual.config）
  GET    /manuals/<pk>/originals/            原稿列表
  POST   /manuals/<pk>/originals/upload/     上传原稿（institution.manual.upload；所有者/管理员）
  GET    /manuals/<pk>/originals/<oid>/download/   下载原稿（institution.manual.download）
  GET    /manuals/<pk>/originals/<oid>/preview-url/ 预览原稿
  GET    /manuals/<pk>/chapters/             旧章节分工清单（遗留只读，供人工核对）
  POST   /manuals/<pk>/chapters/create/      已关闭（章节分工改为文件分工，见文件级接口）
  PUT    /manuals/<pk>/chapters/<cid>/       已关闭
  DELETE /manuals/<pk>/chapters/<cid>/       已关闭
  POST   /manuals/<pk>/chapters/<cid>/progress/  已关闭
  POST   /manuals/<pk>/files/<fid>/assignment/  指定/改派/清空文件负责人（文件分工）
  POST   /manuals/<pk>/files/<fid>/submit/      提交编制（记录草稿修订号与时间）
  GET    /manuals/<pk>/operation-logs/       操作记录

逐本账号授权与所有者管理端点见 views_authorization.py；草稿、会话、
发布、版本与 preview-file 见 views_draft.py。
"""
import logging
import os

from django.db import transaction
from django.db.models import Prefetch
from django.views.generic import View
from urllib.parse import quote

from apps.logs.audit import record_audit_event
from libs import Argument, JsonParser, auth, json_response
from libs.idempotency import check_recent_duplicate
from libs.pagination import paginate

from . import authorization_services, serializers, services, storage, \
    version_compare
from .models import Manual, ManualAuthorization, ManualCategory, \
    ManualOriginal

logger = logging.getLogger(__name__)

PAGE_PERM_PREFIX = 'institution.manual'


def _request_grant(manual, user):
    """当前账号在该手册的授权行（列表/详情序列化用；预取缓存优先）"""
    cached = getattr(manual, '_user_grants', None)
    if cached is not None:
        return cached[0] if cached else None
    return authorization_services.get_manual_grant(manual, user)


def _workspace_visible_with_grant(user, manual, grant, is_admin):
    """工作区可见判定（列表批量口径）：管理员/所有者/编制或发布授权"""
    if is_admin or authorization_services.is_manual_owner(user, manual):
        return True
    return bool(grant and (grant.can_edit or grant.can_publish))


def _manual_from_request(request, pk, require_visible=True):
    """取手册并做可见性校验；失败返回 (None, 响应)"""
    manual, err = authorization_services.get_manual_for_user(pk, request.user)
    if err:
        return None, json_response(error=err)
    return manual, None


def _get_manage_manual(request, pk):
    """管理操作取手册（要求模块权限已由 @auth 校验，这里仅要求可见）"""
    return _manual_from_request(request, pk)


def _check_owner_or_admin(manual, user):
    """文件条目/原稿/分工等维护操作：手册所有者或制度管理员"""
    if (authorization_services.is_manual_owner(user, manual) or
            authorization_services.is_institution_admin(user)):
        return None
    return json_response(error='手册不存在或无权限访问')


def _log_and_audit(request, manual, action, detail=None, before=None, after=None):
    services.log_operation(manual, request.user, action, **(detail or {}))
    record_audit_event(
        request, 'update' if action != services.ACTION_CREATE else 'create',
        services.AUDIT_TARGET_TYPE, target_id=manual.id, target_name=manual.name,
        detail={'action_kind': action, 'module': 'institution'},
        before_value=before, after_value=after,
    )


# ---------------------------------------------------------------------------
# 类别字典


class CategoryView(View):
    @auth('institution.manual.view')
    def get(self, request):
        qs = ManualCategory.objects.all()
        with_inactive = request.GET.get('with_inactive') == '1' and authorization_services.can_manage_manual(request.user)
        if not with_inactive:
            qs = qs.filter(is_active=True)
        return json_response(data=[
            serializers.to_category_dict(x, with_inactive=with_inactive) for x in qs
        ])

    @auth('institution.manual.config')
    @transaction.atomic
    def post(self, request):
        form, error = JsonParser(
            Argument('name', type=str, required=True, help='类别名称不能为空'),
            Argument('sort_order', type=int, default=0),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        name = form.name.strip()
        if not name:
            return json_response(error='类别名称不能为空')
        if ManualCategory.objects.filter(name=name).exists():
            return json_response(error='同名类别已存在')
        obj = ManualCategory.objects.create(
            name=name, sort_order=form.sort_order, created_by=request.user)
        record_audit_event(
            request, 'create', services.AUDIT_TARGET_TYPE,
            target_id=obj.id, target_name=f'类别:{obj.name}',
            detail={'action_kind': 'category_create', 'module': 'institution'})
        return json_response(data=serializers.to_category_dict(obj))


class CategoryDetailView(View):
    @auth('institution.manual.config')
    @transaction.atomic
    def put(self, request, pk):
        obj = ManualCategory.objects.filter(pk=pk).first()
        if not obj:
            return json_response(error='类别不存在')
        form, error = JsonParser(
            Argument('name', type=str, required=True, help='类别名称不能为空'),
            Argument('sort_order', type=int, default=0),
            Argument('is_active', type=bool, default=True),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        name = form.name.strip()
        if not name:
            return json_response(error='类别名称不能为空')
        exists = ManualCategory.objects.filter(name=name).exclude(pk=pk).exists()
        if exists:
            return json_response(error='同名类别已存在')
        before = {'name': obj.name, 'sort_order': obj.sort_order, 'is_active': obj.is_active}
        obj.name = name
        obj.sort_order = form.sort_order
        obj.is_active = form.is_active
        obj.save(update_fields=['name', 'sort_order', 'is_active'])
        record_audit_event(
            request, 'update', services.AUDIT_TARGET_TYPE,
            target_id=obj.id, target_name=f'类别:{obj.name}',
            detail={'action_kind': 'category_update', 'module': 'institution'},
            before_value=before,
            after_value={'name': obj.name, 'sort_order': obj.sort_order, 'is_active': obj.is_active})
        return json_response(data=serializers.to_category_dict(obj))

    @auth('institution.manual.config')
    @transaction.atomic
    def delete(self, request, pk):
        obj = ManualCategory.objects.filter(pk=pk).first()
        if not obj:
            return json_response(error='类别不存在')
        if Manual.objects.filter(category_id=obj.id).exists():
            return json_response(error='该类别下仍有手册，请先调整手册类别或停用该类别')
        name = obj.name
        obj.delete()
        record_audit_event(
            request, 'delete', services.AUDIT_TARGET_TYPE,
            target_id=pk, target_name=f'类别:{name}',
            detail={'action_kind': 'category_delete', 'module': 'institution'})
        return json_response()


# ---------------------------------------------------------------------------
# 手册


def _validate_org_fields(form):
    if form.org_type not in (Manual.OWNER_DEPARTMENT, Manual.OWNER_SECTION):
        return '归属类型必须是 department 或 section'
    return None


def _serialize_manual(request, manual, include_draft):
    """手册 dict 组装（授权行/所有者/管理员标志统一在这里算）"""
    user = request.user
    return serializers.to_manual_detail(
        manual,
        grant=_request_grant(manual, user),
        is_owner=authorization_services.is_manual_owner(user, manual),
        is_admin=authorization_services.is_institution_admin(user),
        include_draft=include_draft)


class ManualListView(View):
    @auth('institution.manual.view')
    def get(self, request):
        from django.db.models import Count, Q
        user = request.user
        qs = Manual.objects.all().select_related(
            'category', 'current_version', 'created_by',
        ).prefetch_related(Prefetch(
            'account_grants',
            queryset=ManualAuthorization.objects.filter(account=user),
            to_attr='_user_grants',
        )).annotate(_active_file_count=Count(
            'files', filter=Q(files__is_removed=False), distinct=True))
        form, error = JsonParser(
            Argument('keyword', type=str, required=False, default=''),
            Argument('category_id', type=int, required=False, default=None),
            Argument('org_type', type=str, required=False, default=''),
            Argument('status', type=str, required=False, default=''),
        ).parse(request.GET, clear=False)
        if error:
            return json_response(error=error)
        if form.keyword:
            qs = qs.filter(name__icontains=form.keyword) | \
                qs.filter(code__icontains=form.keyword) | \
                qs.filter(org_name__icontains=form.keyword)
        if form.category_id:
            qs = qs.filter(category_id=form.category_id)
        if form.org_type:
            qs = qs.filter(org_type=form.org_type)
        if form.status:
            qs = qs.filter(status=form.status)
        qs = authorization_services.filter_visible_manuals(
            qs.distinct(), user)
        page, page_size = paginate(request, default_page_size=20, max_page_size=100)
        total = qs.count()
        page_items = list(qs[(page - 1) * page_size: page * page_size])
        is_admin = authorization_services.is_institution_admin(user)
        include_draft = is_admin
        # 整套工作状态（列表页"打开即知下一步"）：仅对具备草稿访问权的
        # 账号逐手册下发（工作区可见口径 = 管理员/所有者/编制或发布授权；
        # 授权行已 prefetch，就地取值无额外查询）；仅查看授权行内
        # work_status 为 None，不得经列表泄漏草稿信息
        workspace_manuals = [
            m for m in page_items
            if _workspace_visible_with_grant(
                user, m, _request_grant(m, user), is_admin)
        ]
        work_status_map = version_compare.build_manuals_work_status(
            workspace_manuals) if workspace_manuals else {}
        return json_response(data={
            'total': total, 'page': page, 'page_size': page_size,
            'items': [
                serializers.to_manual_list_item(
                    m,
                    grant=_request_grant(m, user),
                    is_owner=authorization_services.is_manual_owner(user, m),
                    is_admin=is_admin,
                    include_draft=include_draft,
                    work_status=work_status_map.get(m.id))
                for m in page_items
            ],
        })


class ManualCreateView(View):
    @auth('institution.manual.add')
    @transaction.atomic
    def post(self, request):
        form, error = JsonParser(
            Argument('name', type=str, required=True, help='手册名称不能为空'),
            Argument('code', type=str, required=False, default=''),
            Argument('category_id', type=int, required=False, default=None),
            Argument('org_type', type=str, default=Manual.OWNER_DEPARTMENT),
            Argument('org_name', type=str, required=False, default=''),
            Argument('editor_can_view_published', type=bool, default=True),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        name = form.name.strip()
        if not name:
            return json_response(error='手册名称不能为空')
        err = _validate_org_fields(form)
        if err:
            return json_response(error=err)
        if check_recent_duplicate(Manual, {'name': name}):
            return json_response(error='检测到重复提交，请勿重复操作')
        category = None
        if form.category_id:
            category = ManualCategory.objects.filter(
                pk=form.category_id, is_active=True).first()
            if not category:
                return json_response(error='所选类别不存在或已停用')
        # 创建人即所有者：持 add 权限码者创建手册后负责其账号授权与分工
        manual = Manual.objects.create(
            name=name, code=(form.code or '').strip(),
            category=category, org_type=form.org_type,
            org_name=(form.org_name or '').strip(),
            editor_can_view_published=form.editor_can_view_published,
            owner=request.user,
            created_by=request.user,
        )
        services.log_operation(manual, request.user, services.ACTION_CREATE)
        record_audit_event(
            request, 'create', services.AUDIT_TARGET_TYPE,
            target_id=manual.id, target_name=manual.name,
            detail={'action_kind': services.ACTION_CREATE, 'module': 'institution'})
        return json_response(data=_serialize_manual(request, manual, True))


class ManualDetailView(View):
    @auth('institution.manual.view')
    def get(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        from django.db.models import Count, Q
        manual = Manual.objects.filter(pk=manual.pk).annotate(
            _active_file_count=Count(
                'files', filter=Q(files__is_removed=False), distinct=True),
        ).select_related('category', 'current_version', 'created_by', 'owner').get(
            pk=manual.pk)
        include_draft = authorization_services.can_view_workspace(request.user, manual)
        return json_response(data=_serialize_manual(request, manual, include_draft))

    @auth('institution.manual.edit')
    @transaction.atomic
    def put(self, request, pk):
        manual, resp = _get_manage_manual(request, pk)
        if resp:
            return resp
        form, error = JsonParser(
            Argument('name', type=str, required=True, help='手册名称不能为空'),
            Argument('code', type=str, required=False, default=''),
            Argument('category_id', type=int, required=False, default=None),
            Argument('org_type', type=str, default=manual.org_type),
            Argument('org_name', type=str, required=False, default=''),
            Argument('status', type=str, default=manual.status),
            Argument('editor_can_view_published', type=bool,
                     default=manual.editor_can_view_published),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        name = form.name.strip()
        if not name:
            return json_response(error='手册名称不能为空')
        if form.status not in (Manual.STATUS_ACTIVE, Manual.STATUS_ARCHIVED):
            return json_response(error='状态必须是 active 或 archived')
        err = _validate_org_fields(form)
        if err:
            return json_response(error=err)
        category = None
        if form.category_id:
            category = ManualCategory.objects.filter(pk=form.category_id).first()
            if not category:
                return json_response(error='所选类别不存在')
        before = {
            'name': manual.name, 'code': manual.code,
            'category_id': manual.category_id, 'org_type': manual.org_type,
            'org_name': manual.org_name, 'status': manual.status,
            'editor_can_view_published': manual.editor_can_view_published,
        }
        manual.name = name
        manual.code = (form.code or '').strip()
        manual.category = category
        manual.org_type = form.org_type
        manual.org_name = (form.org_name or '').strip()
        manual.status = form.status
        manual.editor_can_view_published = form.editor_can_view_published
        manual.save()
        _log_and_audit(request, manual, services.ACTION_CONFIG_CHANGE,
                       detail={'fields': ['name', 'code', 'category', 'org',
                                          'status', 'editor_can_view_published']},
                       before=before, after=before | {
                           'name': manual.name, 'code': manual.code,
                           'category_id': manual.category_id,
                           'org_type': manual.org_type,
                           'org_name': manual.org_name,
                           'status': manual.status,
                           'editor_can_view_published': manual.editor_can_view_published})
        return json_response(data=_serialize_manual(request, manual, True))

    @auth('institution.manual.delete')
    @transaction.atomic
    def delete(self, request, pk):
        manual, resp = _get_manage_manual(request, pk)
        if resp:
            return resp
        if manual.versions.exists():
            return json_response(error='已有发布版本的手册不可删除，请使用归档保留历史')
        # 第十二节：先删物理文件，成功后才删数据库记录。清理失败直接拒绝，
        # 不产生"记录已删、文件树残留"的孤儿目录（重试幂等：目录已清则直接过）
        removed, err = storage.safe_delete_manual_dir(manual.id)
        if not removed:
            logger.error('[Institution] manual delete aborted, file cleanup '
                         'failed: manual=%s error=%s', manual.id, err)
            return json_response(error='手册文件清理失败，请稍后重试或联系管理员')
        manual_id = manual.id
        manual_name = manual.name
        manual.delete()
        record_audit_event(
            request, 'delete', services.AUDIT_TARGET_TYPE,
            target_id=manual_id, target_name=manual_name,
            detail={'action_kind': services.ACTION_DELETE, 'module': 'institution'})
        return json_response()


class ManualPasswordView(View):
    """设置/重置编辑密码（重置使所有有效编辑会话失效）"""

    @auth('institution.manual.config')
    @transaction.atomic
    def put(self, request, pk):
        manual, resp = _get_manage_manual(request, pk)
        if resp:
            return resp
        form, error = JsonParser(
            Argument('password', type=str, required=True, help='密码不能为空'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        password = form.password
        if len(password) < 4:
            return json_response(error='密码长度至少 4 位')
        services.set_manual_password(
            manual, password, request.user,
            reason=f'由 {request.user.username} 重置')
        record_audit_event(
            request, 'update', services.AUDIT_TARGET_TYPE,
            target_id=manual.id, target_name=manual.name,
            detail={'action_kind': services.ACTION_PASSWORD_RESET,
                    'module': 'institution'})
        return json_response()


# ---------------------------------------------------------------------------
# 原稿


class OriginalListView(View):
    """过渡期旧接口：委托唯一启用文件的原稿列表，多文件制度明确拒绝"""

    @auth('institution.manual.view')
    def get(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        file_entry, err = services.get_single_active_file(manual)
        if err:
            return json_response(error=err)
        originals = file_entry.originals.select_related('uploaded_by').all()
        return json_response(data=[
            serializers.to_original_dict(x) for x in originals])


class OriginalUploadView(View):
    """过渡期旧接口：上传原稿并绑定唯一启用文件，多文件制度明确拒绝"""

    @auth('institution.manual.upload')
    def post(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        deny = _check_owner_or_admin(manual, request.user)
        if deny:
            return deny
        file_entry, err = services.get_single_active_file(manual)
        if err:
            return json_response(error=err)
        upload = request.FILES.get('file')
        if not upload:
            return json_response(error='请选择要上传的文件')
        ext = storage.extract_extension(upload.name)
        if ext not in storage.ALLOWED_EXTENSIONS:
            return json_response(error='仅支持 .doc / .docx 文件')
        if upload.size > storage.MAX_FILE_SIZE:
            return json_response(error='文件大小超过限制（100MB）')
        stored_name = storage.build_stored_name(upload.name)
        rel_path = storage.build_relative_path(
            storage.FILE_KIND_ORIGINAL, manual.id, stored_name)
        abs_path = storage.resolve_absolute_path(rel_path)
        file_hash = storage.save_upload_file(upload, abs_path)
        try:
            with transaction.atomic():
                original = ManualOriginal.objects.create(
                    manual=manual, file=file_entry, file_path=rel_path,
                    original_name=upload.name, ext=ext,
                    file_size=upload.size, file_hash=file_hash,
                    uploaded_by=request.user)
                services.log_operation(
                    manual, request.user, services.ACTION_UPLOAD_ORIGINAL,
                    file=file_entry, file_id=file_entry.id,
                    original_id=original.id, file_name=upload.name)
                record_audit_event(
                    request, 'create', services.AUDIT_TARGET_TYPE,
                    target_id=manual.id, target_name=manual.name,
                    detail={'action_kind': services.ACTION_UPLOAD_ORIGINAL,
                            'file_id': file_entry.id, 'file_name': upload.name,
                            'module': 'institution'})
        except Exception:
            storage.safe_delete_file(abs_path)
            raise
        return json_response(data=serializers.to_original_dict(original))


def _download_response(request, abs_path, filename):
    from django.http import FileResponse
    if not os.path.exists(abs_path):
        return json_response(error='文件不存在或已被清理')
    response = FileResponse(open(abs_path, 'rb'))
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(filename)}"
    return response


class OriginalDownloadView(View):
    @auth('institution.manual.download')
    def get(self, request, pk, oid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        original = ManualOriginal.objects.filter(
            pk=oid, manual=manual).first()
        if not original:
            return json_response(error='原稿不存在或无权限访问')
        if original.cleaned_at:
            return json_response(error=storage.ORIGINAL_CLEANED_ERROR)
        services.log_operation(
            manual, request.user, 'download',
            file_name=original.original_name, file_kind='original')
        try:
            abs_path = storage.resolve_absolute_path(original.file_path)
        except ValueError:
            return json_response(error='文件路径非法')
        return _download_response(request, abs_path, original.original_name)


# ---------------------------------------------------------------------------
# 章节分工（遗留只读，2026-10-29 起由文件分工替代）
#
# 分工单位已改为整份制度文件（ManualFile 的负责人/分工说明与提交编制，
# 见 views_files.ManualFileAssignmentView / ManualFileSubmitView）。旧
# ManualChapter 记录只关联制度、无法按章节名称猜测所属文件，在人工核对
# 完成前保留：GET 清单继续开放供过渡展示与核对，全部写接口（新增/编辑/
# 删除/进度）关闭并返回明确业务错误，绝不静默删除或改写旧记录。

LEGACY_CHAPTER_READONLY_ERROR = (
    '章节分工已改为按文件分工维护：请在文件清单中指定各文件的负责人；'
    '旧章节记录仅供查阅与人工核对，不再支持新增或修改')


class ChapterListView(View):
    @auth('institution.manual.view')
    def get(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        chapters = manual.chapters.select_related('owner').all()
        return json_response(data=[
            serializers.to_chapter_dict(x) for x in chapters])

    @auth('institution.manual.draft_edit')
    def post(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        return json_response(error=LEGACY_CHAPTER_READONLY_ERROR)


class ChapterDetailView(View):
    @auth('institution.manual.draft_edit')
    def put(self, request, pk, cid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        return json_response(error=LEGACY_CHAPTER_READONLY_ERROR)

    @auth('institution.manual.draft_edit')
    def delete(self, request, pk, cid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        return json_response(error=LEGACY_CHAPTER_READONLY_ERROR)


class ChapterProgressView(View):
    @auth('institution.manual.view')
    def post(self, request, pk, cid):
        return json_response(error=LEGACY_CHAPTER_READONLY_ERROR)


# ---------------------------------------------------------------------------
# 操作记录


class OperationLogListView(View):
    @auth('institution.manual.view')
    def get(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        qs = manual.operation_logs.select_related('user').all()
        # 按文件过滤（文件变更记录页签）；非法值明确拒绝
        file_id = request.GET.get('file_id', '')
        if file_id:
            if not file_id.isdigit():
                return json_response(error='文件参数非法')
            qs = qs.filter(file_id=int(file_id))
        page, page_size = paginate(request, default_page_size=20, max_page_size=100)
        total = qs.count()
        items = qs[(page - 1) * page_size: page * page_size]
        return json_response(data={
            'total': total, 'page': page, 'page_size': page_size,
            'items': [serializers.to_oplog_dict(x) for x in items],
        })
