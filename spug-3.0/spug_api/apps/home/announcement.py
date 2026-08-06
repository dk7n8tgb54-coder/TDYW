# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""公告发布模块接口

管理端（需 home.announcement.* 权限码，超管自动放行）：
  /api/home/announcement/admin/                      GET 列表 / POST 新增编辑
  /api/home/announcement/admin/                      DELETE 删除（自动先撤回）
  /api/home/announcement/admin/departments/          GET 可选发布部门（Tenant 列表）
  /api/home/announcement/admin/<id>/                 GET 详情
  /api/home/announcement/admin/<id>/publish/         POST 发布
  /api/home/announcement/admin/<id>/withdraw/        POST 撤回
  /api/home/announcement/admin/<id>/attachments/     GET 列表 / POST 上传
  /api/home/announcement/admin/attachments/<id>/     DELETE 删除附件

用户端（已登录即可，按可见性规则过滤）：
  /api/home/announcement/                            GET 可见公告列表
  /api/home/announcement/<id>/                       GET 详情（自动标记已读）
  /api/home/announcement/<id>/read/                  POST 标记已读
  /api/home/announcement/<id>/attachments/           GET 详情页附件列表
  /api/home/announcement/unread-count/               GET 未读数量
  /api/home/announcement/reminders/                  GET 未读提醒（前 5 条）
  /api/home/announcement/attachments/<id>/download/  GET 下载（可见性校验）
  /api/home/announcement/attachments/<id>/preview-url/ GET 在线预览地址
  /api/home/announcement/attachments/<id>/preview-file/ GET kkFileView 回调（preview_token 鉴权）
"""
import logging

from django.db import transaction
from django.db.models import Q
from django.views import View

from django.utils import timezone
from libs import json_response, JsonParser, Argument, parse_time
from apps.logs.audit import record_audit_event
from apps.account.models import Tenant
from apps.evidence.models import EvidenceAttachment
from apps.evidence.attachment_service import (
    AttachmentService, AttachmentConfig, PREVIEWABLE_EXTENSIONS,
)

from .models import (
    Announcement, AnnouncementScope, AnnouncementRead,
    visible_announcements_for_user,
    SCOPE_ALL, SCOPE_TENANT,
    STATUS_UNPUBLISHED, STATUS_PUBLISHED, STATUS_EXPIRED,
    ANN_CONTENT_MAX_LEN, TITLE_MAX_LEN,
)

logger = logging.getLogger(__name__)

# 公告附件配置（复用默认）
AnnouncementAttachmentConfig = AttachmentConfig()

MODULE = 'announcement'
OBJECT_TYPE = 'announcement'


# ==================== 公共工具 ====================

def ensure_announcement_perm(user, code):
    """校验公告管理权限码 home.announcement.<code>，超管自动放行，其余按角色权限码判定"""
    return user.has_perms(['home.announcement.%s' % code])


def _normalize_datetime(value, required=True, field='时间'):
    """校验并规范化时间，返回 (datetime|None, error)"""
    if not value:
        if required:
            return None, '请填写%s' % field
        return None, None
    try:
        dt = parse_time(value)
    except (TypeError, ValueError):
        return None, '%s格式错误' % field
    return dt, None


def _range_bound(value, is_end):
    """范围筛选边界：纯日期补全天/末时刻，保证字符串比较正确"""
    if not value:
        return value
    v = value.strip()
    if len(v) == 10:
        v = v + (' 23:59:59' if is_end else ' 00:00:00')
    return v


def _set_publish_department(ann, form, request):
    """设置发布部门快照（缺省取当前用户所属租户）"""
    pid = form.publish_department_id or getattr(request.user, 'tenant_id', '')
    pname = form.publish_department_name or ''
    if not pname and pid:
        t = Tenant.objects.filter(id=pid).first()
        pname = t.name if t else pid
    ann.publish_department_id = pid or ''
    ann.publish_department_name = pname


def _sync_scopes(ann, scope_type, tids, tenants):
    """重建发布范围（先清空再写入，事务保证原子性）"""
    with transaction.atomic():
        ann.scopes.all().delete()
        if scope_type == SCOPE_TENANT and tids:
            for tid in tids:
                AnnouncementScope.objects.create(
                    announcement=ann,
                    tenant_id=tid,
                    tenant_name=tenants.get(tid, tid),
                )


def _mark_read(ann, user):
    """标记已读（并发安全，重复不报错）"""
    AnnouncementRead.objects.get_or_create(
        announcement=ann,
        user_id=user.id,
        defaults={
            'tenant_id': getattr(user, 'tenant_id', ''),
            'username': user.username,
            'nickname': user.nickname or user.username,
            'read_at': timezone.now(),
        },
    )


# ==================== 管理端 ====================

def _validate_title_content(form):
    """校验标题和内容，返回 (title, content, error)"""
    title = (form.title or '').strip()
    if not title:
        return None, None, '请输入标题'
    if len(title) > TITLE_MAX_LEN:
        return None, None, '标题长度不能超过 %d 个字符' % TITLE_MAX_LEN
    content = form.content or ''
    if not content.strip():
        return None, None, '请输入内容'
    if len(content) > ANN_CONTENT_MAX_LEN:
        return None, None, '内容长度不能超过 %d 个字符' % ANN_CONTENT_MAX_LEN
    return title, content, None


def _validate_effective_times(form):
    """校验生效时间区间，返回 (start_dt, end_dt|None, error)"""
    start_dt, err = _normalize_datetime(form.effective_start_at, required=True, field='生效开始时间')
    if err:
        return None, None, err
    end_dt = None
    if form.effective_end_at:
        end_dt, err = _normalize_datetime(form.effective_end_at, required=False, field='生效结束时间')
        if err:
            return None, None, err
        if end_dt and end_dt < start_dt:
            return None, None, '生效结束时间不能早于开始时间'
    return start_dt, end_dt, None


def _validate_scope(form):
    """校验发布范围，返回 (tids, tenants, error)"""
    tids = form.target_tenant_ids or []
    tenants = {}
    if form.scope_type == SCOPE_TENANT:
        if not tids:
            return None, None, '请选择发布部门'
        tenants = {t.id: t.name for t in Tenant.objects.filter(id__in=tids)}
        missing = [t for t in tids if t not in tenants]
        if missing:
            return None, None, '存在无效的发布部门'
    return tids, tenants, None


def _validate_announcement_form(form):
    """校验公告表单，返回 (title, content, start_dt, end_dt, tids, tenants, error)"""
    title, content, err = _validate_title_content(form)
    if err:
        return None, None, None, None, None, None, err
    start_dt, end_dt, err = _validate_effective_times(form)
    if err:
        return None, None, None, None, None, None, err
    tids, tenants, err = _validate_scope(form)
    if err:
        return None, None, None, None, None, None, err
    return title, content, start_dt, end_dt, tids, tenants, None


def _update_announcement(form, title, content, start_dt, end_dt, tids, tenants, request):
    """更新已有公告，返回 (ann, error)"""
    ann = Announcement.objects.filter(pk=form.id, is_deleted=False).first()
    if not ann:
        return None, '公告不存在'
    if ann.status == STATUS_PUBLISHED:
        return None, '已发布公告请先撤回再编辑'
    now = timezone.now()
    user = request.user
    ann.title = title
    ann.content = content
    ann.scope_type = form.scope_type
    ann.effective_start_at = start_dt
    ann.effective_end_at = end_dt
    ann.is_important = form.is_important
    ann.updated_at = now
    ann.updated_by_id = user.id
    ann.updated_by_name = user.nickname or user.username
    _set_publish_department(ann, form, request)
    with transaction.atomic():
        ann.save()
        _sync_scopes(ann, form.scope_type, tids, tenants)
    record_audit_event(request, 'update', target_type='home', target_id=ann.id, target_name=ann.title)
    return ann, None


def _create_announcement(form, title, content, start_dt, end_dt, tids, tenants, request):
    """创建新公告，返回 ann"""
    user = request.user
    ann = Announcement(
        tenant_id=getattr(user, 'tenant_id', ''),
        title=title,
        content=content,
        scope_type=form.scope_type,
        effective_start_at=start_dt,
        effective_end_at=end_dt,
        is_important=form.is_important,
        status=STATUS_UNPUBLISHED,
        created_by_id=user.id,
        created_by_name=user.nickname or user.username,
    )
    _set_publish_department(ann, form, request)
    with transaction.atomic():
        ann.save()
        _sync_scopes(ann, form.scope_type, tids, tenants)
    record_audit_event(request, 'create', target_type='home', target_id=ann.id, target_name=ann.title)
    return ann


class AnnouncementAdminListView(View):
    """管理端公告列表 / 新增编辑"""

    def get(self, request):
        if not ensure_announcement_perm(request.user, 'view'):
            return json_response(error='权限拒绝')
        form, error = JsonParser(
            Argument('status', required=False),
            Argument('publish_department_id', required=False),
            Argument('scope_type', required=False),
            Argument('start_at', required=False),
            Argument('end_at', required=False),
            Argument('keyword', required=False),
            Argument('page', type=int, default=1),
            Argument('page_size', type=int, default=20),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        qs = Announcement.objects.filter(is_deleted=False)
        if form.status:
            qs = qs.filter(status=form.status)
        if form.publish_department_id:
            qs = qs.filter(publish_department_id=form.publish_department_id)
        if form.scope_type:
            qs = qs.filter(scope_type=form.scope_type)
        if form.start_at:
            qs = qs.filter(published_at__gte=_range_bound(form.start_at, False))
        if form.end_at:
            qs = qs.filter(published_at__lte=_range_bound(form.end_at, True))
        if form.keyword:
            qs = qs.filter(Q(title__contains=form.keyword) | Q(content__contains=form.keyword))
        total = qs.count()
        qs = qs.order_by('-published_at', '-id')
        page_size = min(form.page_size, 100)
        start = (form.page - 1) * page_size
        items = qs[start:start + page_size]
        return json_response({'results': [x.to_view() for x in items], 'total': total})

    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('title', help='请输入标题'),
            Argument('content', help='请输入内容'),
            Argument('scope_type', filter=lambda x: x in (SCOPE_ALL, SCOPE_TENANT), help='发布范围错误'),
            Argument('target_tenant_ids', type=list, required=False),
            Argument('publish_department_id', required=False),
            Argument('publish_department_name', required=False),
            Argument('effective_start_at', required=False),
            Argument('effective_end_at', required=False),
            Argument('is_important', type=bool, default=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        needed_perm = 'edit' if form.id else 'add'
        if not ensure_announcement_perm(request.user, needed_perm):
            return json_response(error='权限拒绝')
        title, content, start_str, end_str, tids, tenants, err = _validate_announcement_form(form)
        if err:
            return json_response(error=err)
        if form.id:
            ann, err = _update_announcement(form, title, content, start_str, end_str, tids, tenants, request)
            if err:
                return json_response(error=err)
        else:
            ann = _create_announcement(form, title, content, start_str, end_str, tids, tenants, request)
        return json_response(ann.to_view())


class AnnouncementAdminDetailView(View):
    """管理端详情 / 删除"""

    def get(self, request, pk):
        if not ensure_announcement_perm(request.user, 'view'):
            return json_response(error='权限拒绝')
        ann = Announcement.objects.filter(pk=pk, is_deleted=False).first()
        if not ann:
            return json_response(error='公告不存在')
        return json_response(ann.to_view(include_content=True))

    def delete(self, request, pk):
        if not ensure_announcement_perm(request.user, 'delete'):
            return json_response(error='权限拒绝')
        with transaction.atomic():
            ann = Announcement.objects.select_for_update().filter(
                pk=pk, is_deleted=False).first()
            if not ann:
                return json_response(error='公告不存在')
            # 已发布先自动撤回，保证用户端不可见
            if ann.status == STATUS_PUBLISHED:
                ann.status = STATUS_UNPUBLISHED
                ann.withdrawn_at = timezone.now()
                ann.withdrawn_by_id = request.user.id
                ann.withdrawn_by_name = request.user.nickname or request.user.username
            # 软删除
            ann.is_deleted = True
            ann.deleted_at = timezone.now()
            ann.deleted_by_id = request.user.id
            ann.deleted_by_name = request.user.nickname or request.user.username
            ann.save()
        # 联动软删除附件
        AttachmentService.soft_delete_by_object(request.user, MODULE, OBJECT_TYPE, ann.id)
        record_audit_event(request, 'delete', target_type='home', target_id=ann.id, target_name=ann.title)
        return json_response()


class AnnouncementDepartmentsView(View):
    """可选发布部门（Tenant 列表）"""

    def get(self, request):
        if not ensure_announcement_perm(request.user, 'view'):
            return json_response(error='权限拒绝')
        tenants = Tenant.objects.all().order_by('id')
        return json_response([{'id': t.id, 'name': t.name} for t in tenants])


class AnnouncementPublishView(View):
    """发布公告"""

    def post(self, request, pk):
        if not ensure_announcement_perm(request.user, 'publish'):
            return json_response(error='权限拒绝')
        ann = Announcement.objects.filter(pk=pk, is_deleted=False).first()
        if not ann:
            return json_response(error='公告不存在')
        if ann.status == STATUS_PUBLISHED:
            return json_response(error='公告已发布，请勿重复发布')
        now = timezone.now()
        ann.status = STATUS_PUBLISHED
        ann.published_at = now
        ann.published_by_id = request.user.id
        ann.published_by_name = request.user.nickname or request.user.username
        ann.withdrawn_at = None
        ann.withdrawn_by_id = None
        ann.withdrawn_by_name = ''
        # 保留用户填写的生效时间，compute_status 会按时间区间自然判定可见性
        ann.save()
        record_audit_event(request, 'update', target_type='home', target_id=ann.id, target_name=ann.title)
        return json_response({'id': ann.id, 'status': ann.status, 'published_at': ann.published_at})


class AnnouncementWithdrawView(View):
    """撤回公告"""

    def post(self, request, pk):
        if not ensure_announcement_perm(request.user, 'withdraw'):
            return json_response(error='权限拒绝')
        ann = Announcement.objects.filter(pk=pk, is_deleted=False).first()
        if not ann:
            return json_response(error='公告不存在')
        if ann.status != STATUS_PUBLISHED:
            return json_response(error='仅已发布公告可撤回')
        ann.status = STATUS_UNPUBLISHED
        ann.withdrawn_at = timezone.now()
        ann.withdrawn_by_id = request.user.id
        ann.withdrawn_by_name = request.user.nickname or request.user.username
        ann.save()
        record_audit_event(request, 'update', target_type='home', target_id=ann.id, target_name=ann.title)
        return json_response({'id': ann.id, 'status': ann.status})


# ==================== 管理端附件 ====================

class AnnouncementAttachmentListView(View):
    """管理端附件列表 / 上传"""

    def get(self, request, pk):
        if not ensure_announcement_perm(request.user, 'view'):
            return json_response(error='权限拒绝')
        ann = Announcement.objects.filter(pk=pk, is_deleted=False).first()
        if not ann:
            return json_response(error='公告不存在')
        data = AttachmentService.list(request.user, MODULE, OBJECT_TYPE, pk)
        return json_response(data)

    def post(self, request, pk):
        if not ensure_announcement_perm(request.user, 'edit'):
            return json_response(error='权限拒绝')
        ann = Announcement.objects.filter(pk=pk, is_deleted=False).first()
        if not ann:
            return json_response(error='公告不存在')
        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的文件')
        att, error = AttachmentService.upload(
            file=file, user=request.user,
            module=MODULE, object_type=OBJECT_TYPE, object_id=pk,
            config=AnnouncementAttachmentConfig,
        )
        if error:
            return json_response(error=error)
        result = att.to_view()
        result['uploaded_by_name'] = request.user.nickname
        result['created_at'] = att.uploaded_at
        result['previewable'] = att.file_ext in PREVIEWABLE_EXTENSIONS
        record_audit_event(request, 'create', target_type='home', target_id=ann.id, target_name=att.file_name)
        return json_response(result)


class AnnouncementAttachmentDeleteView(View):
    """管理端删除附件（软删除，附件ID通过query参数id传递，对齐公共组件）"""

    def delete(self, request):
        if not ensure_announcement_perm(request.user, 'delete'):
            return json_response(error='权限拒绝')
        form, error = JsonParser(
            Argument('id', type=int, help='请指定附件ID'),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        error = AttachmentService.soft_delete(request.user, form.id, delete_file=True)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'delete', target_type='home', target_name='删除附件 ID=%s' % form.id)
        return json_response()


# ==================== 用户端 ====================

class AnnouncementListView(View):
    """当前用户可见公告列表"""

    def get(self, request):
        form, error = JsonParser(
            Argument('publish_department_id', required=False),
            Argument('start_at', required=False),
            Argument('end_at', required=False),
            Argument('keyword', required=False),
            Argument('read_status', required=False, filter=lambda x: x in ('read', 'unread', '')),
            Argument('page', type=int, default=1),
            Argument('page_size', type=int, default=20),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        qs = visible_announcements_for_user(request.user)
        if form.publish_department_id:
            qs = qs.filter(publish_department_id=form.publish_department_id)
        if form.start_at:
            qs = qs.filter(published_at__gte=_range_bound(form.start_at, False))
        if form.end_at:
            qs = qs.filter(published_at__lte=_range_bound(form.end_at, True))
        if form.keyword:
            qs = qs.filter(Q(title__contains=form.keyword) | Q(content__contains=form.keyword))
        if form.read_status == 'read':
            qs = qs.filter(reads__user_id=request.user.id)
        elif form.read_status == 'unread':
            qs = qs.exclude(reads__user_id=request.user.id)
        qs = qs.distinct()
        total = qs.count()
        qs = qs.order_by('-published_at', '-id')
        page_size = min(form.page_size, 100)
        start = (form.page - 1) * page_size
        items = qs[start:start + page_size]
        return json_response({'results': [x.to_view(request.user) for x in items], 'total': total})


class AnnouncementDetailView(View):
    """公告详情（自动标记已读）"""

    def get(self, request, pk):
        ann = Announcement.objects.filter(pk=pk, is_deleted=False).first()
        if not ann or not ann.is_visible_to(request.user):
            return json_response(error='公告不存在或无权限访问')
        _mark_read(ann, request.user)
        return json_response(ann.to_view(request.user, include_content=True))


class AnnouncementReadView(View):
    """手动标记已读"""

    def post(self, request, pk):
        ann = Announcement.objects.filter(pk=pk, is_deleted=False).first()
        if not ann or not ann.is_visible_to(request.user):
            return json_response(error='公告不存在或无权限访问')
        _mark_read(ann, request.user)
        return json_response()


class AnnouncementUserAttachmentListView(View):
    """用户端详情页附件列表（跨租户可见，需跳过租户过滤）"""

    def get(self, request, pk):
        ann = Announcement.objects.filter(pk=pk, is_deleted=False).first()
        if not ann or not ann.is_visible_to(request.user):
            return json_response(error='公告不存在或无权限访问')
        data = AttachmentService.list(
            request.user, MODULE, OBJECT_TYPE, pk, skip_tenant_filter=True)
        return json_response(data)


class AnnouncementUnreadCountView(View):
    """当前用户未读公告数量"""

    def get(self, request):
        qs = visible_announcements_for_user(request.user)
        visible_ids = list(qs.values_list('id', flat=True))
        read_set = set(AnnouncementRead.objects.filter(
            user_id=request.user.id, announcement_id__in=visible_ids
        ).values_list('announcement_id', flat=True))
        count = len([i for i in visible_ids if i not in read_set])
        return json_response({'count': count})


class AnnouncementRemindersView(View):
    """未读提醒（前 5 条）"""

    def get(self, request):
        qs = visible_announcements_for_user(request.user).order_by('-published_at', '-id')
        results = []
        visible_ids = list(qs.values_list('id', flat=True))
        if visible_ids:
            read_ids = set(AnnouncementRead.objects.filter(
                announcement_id__in=visible_ids, user_id=request.user.id
            ).values_list('announcement_id', flat=True))
            unread_ids = [i for i in visible_ids if i not in read_ids][:5]
            if unread_ids:
                results = [ann.to_view(request.user) for ann in qs.filter(id__in=unread_ids)]
        return json_response(results)


# ==================== 用户端附件下载 / 预览 ====================

class AnnouncementAttachmentDownloadView(View):
    """附件下载（校验可见性 + 跳过租户过滤）"""

    def get(self, request, pk):
        att = EvidenceAttachment.objects.filter(
            pk=pk, module=MODULE, is_deleted=False).first()
        if not att:
            return json_response(error='附件不存在')
        ann = Announcement.objects.filter(pk=att.object_id, is_deleted=False).first()
        if not (ensure_announcement_perm(request.user, 'view') or (ann and ann.is_visible_to(request.user))):
            return json_response(error='无权限访问该附件')
        inline = request.GET.get('inline') in ('1', 'true', 'True')
        response, error = AttachmentService.download_response(
            request.user, pk, inline=inline, skip_tenant_filter=True)
        if error:
            return json_response(error=error)
        return response


class AnnouncementAttachmentPreviewUrlView(View):
    """获取在线预览地址（跨租户用附件真实 tenant_id 绑定令牌）"""

    def get(self, request, pk):
        att = EvidenceAttachment.objects.filter(
            pk=pk, module=MODULE, is_deleted=False).first()
        if not att:
            return json_response(error='附件不存在')
        ann = Announcement.objects.filter(pk=att.object_id, is_deleted=False).first()
        if not (ensure_announcement_perm(request.user, 'view') or (ann and ann.is_visible_to(request.user))):
            return json_response(error='无权限访问该附件')
        preview_file_api_path = '/api/home/announcement/attachments/%s/preview-file/' % pk
        data, error = AttachmentService.get_preview_url(
            request.user, pk, preview_file_api_path,
            skip_tenant_filter=True, token_tenant_id=att.tenant_id)
        if error:
            return json_response(error=error)
        return json_response(data)


class AnnouncementAttachmentPreviewFileView(View):
    """kkFileView 回调读取文件流（preview_token 鉴权）"""

    def get(self, request, pk):
        preview_token = request.GET.get('preview_token')
        if not preview_token:
            return json_response(error='缺少 preview_token 参数')
        response, error = AttachmentService.preview_file_response(preview_token, pk)
        if error:
            return json_response(error=error)
        return response
