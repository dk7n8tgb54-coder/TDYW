# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""系统版本与更新日志接口

用户端（已登录即可，按可见性规则过滤）：
  GET  /api/system/version/                        当前版本信息
  GET  /api/system/release-notes/                  已发布更新日志列表（分页）
  GET  /api/system/release-notes/unread/           当前用户未读/待确认更新
  GET  /api/system/release-notes/settings/         「每次更新后自动弹出更新日志」个人偏好（读取）
  PUT  /api/system/release-notes/settings/         「每次更新后自动弹出更新日志」个人偏好（本人设置）
  GET  /api/system/release-notes/<id>/             更新详情
  POST /api/system/release-notes/<id>/read/        标记已读
  POST /api/system/release-notes/<id>/ack/         重要更新确认

管理端（权限 system.release_note.*，超管自动放行；更新日志面向全平台所有用户，
新增/编辑/删除/发布仅超级管理员可操作）：
  GET    /api/system/release-notes/admin/                 列表
  POST   /api/system/release-notes/admin/                 新建/编辑
  GET    /api/system/release-notes/admin/<id>/            详情
  DELETE /api/system/release-notes/admin/<id>/            删除
  POST   /api/system/release-notes/admin/<id>/publish/    发布/撤回
"""
import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.views import View

from libs import json_response, JsonParser, Argument
from libs.pagination import paginate, paginate_response
from libs.tenant_utils import apply_tenant_filter
from apps.account.models import Role
from apps.logs.audit import record_audit_event
from apps.setting.models import UserSetting

from .models import (
    ReleaseNote, ReleaseNoteRead, ReleaseNoteRole,
    visible_release_notes_for_user, unread_release_notes_for_user,
    parse_role_ids, CONTENT_MAX_LEN, TITLE_MAX_LEN,
    VERSION_MAX_LEN, UNREAD_MAX_ITEMS,
)

logger = logging.getLogger(__name__)

PERM_PREFIX = 'system.release_note'

# 「每次更新后自动弹出更新日志」用户偏好的存储键（apps.setting.UserSetting）
POPUP_PREF_KEY = 'release_note_popup'


# ==================== 公共工具 ====================

def get_user_show_after_update(user):
    """读取用户的「每次更新后自动弹出更新日志」偏好（未设置或值异常时默认开启）"""
    item = UserSetting.objects.filter(user=user, key=POPUP_PREF_KEY).first()
    if item is None:
        return True
    return item.value != 'false'

def _has_perm(user, code):
    """校验 system.release_note.<code> 权限，超管放行"""
    return user.has_perms(['%s.%s' % (PERM_PREFIX, code)])


def _deny(message='权限拒绝'):
    return json_response(error=message)


def _visible_note_or_none(user, pk):
    """用户可见的日志，不存在则 None（不泄露跨租户/未发布信息）"""
    return visible_release_notes_for_user(user).filter(pk=pk).first()


def _mark_read(note, user, acknowledged=False):
    """标记已读/确认（并发安全，重复调用不报错）"""
    now = timezone.now()
    with transaction.atomic():
        read, created = ReleaseNoteRead.objects.get_or_create(
            note=note,
            user_id=user.id,
            defaults={
                'tenant_id': getattr(user, 'tenant_id', ''),
                'username': user.username,
                'nickname': user.nickname or user.username,
                'is_acknowledged': acknowledged,
                'acknowledged_at': now if acknowledged else None,
            },
        )
        if not created and acknowledged and not read.is_acknowledged:
            read.is_acknowledged = True
            read.acknowledged_at = now
            read.save(update_fields=['is_acknowledged', 'acknowledged_at'])
    return read


# ==================== 版本信息 ====================

class SystemVersionView(View):
    """当前系统版本（版本号唯一来源：settings.SPUG_VERSION，可由环境变量覆盖）"""

    def get(self, request):
        return json_response({
            'version': getattr(settings, 'SPUG_VERSION', ''),
            'build_number': getattr(settings, 'SPUG_BUILD_NUMBER', ''),
            'release_date': getattr(settings, 'SPUG_RELEASE_DATE', ''),
        })


# ==================== 用户端 ====================

class ReleaseNoteListView(View):
    """已发布更新日志列表"""

    def get(self, request):
        form, error = JsonParser(
            Argument('version', required=False),
            Argument('only_current', type=bool, required=False, default=False),
            Argument('with_content', type=bool, required=False, default=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        qs = visible_release_notes_for_user(request.user)
        if form.version:
            qs = qs.filter(version=form.version)
        if form.only_current:
            qs = qs.filter(version=getattr(settings, 'SPUG_VERSION', ''))

        page, page_size = paginate(request)
        data = paginate_response(
            qs, page, page_size,
            serialize_fn=lambda x: x.to_view(
                user=request.user, include_content=form.with_content),
        )
        data['current_version'] = getattr(settings, 'SPUG_VERSION', '')
        return json_response(data)


class ReleaseNoteUnreadView(View):
    """当前用户未读（含待确认）更新"""

    def get(self, request):
        notes = unread_release_notes_for_user(request.user)
        unread_count = notes.count()
        items = [x.to_view(user=request.user, include_content=True)
                 for x in notes[:UNREAD_MAX_ITEMS]]
        return json_response({
            'unread_count': unread_count,
            'has_required': any(x['is_required'] for x in items),
            'current_version': getattr(settings, 'SPUG_VERSION', ''),
            'show_after_update': get_user_show_after_update(request.user),
            'items': items,
        })


class ReleaseNoteSettingsView(View):
    """「每次更新后自动弹出更新日志」用户偏好

    每个用户独立控制自己的更新弹窗：勾选时系统更新后自动弹出更新说明；
    取消后不再自动弹窗，用户可从头像菜单「更新日志」随时查看与重新开启。
    GET/PUT 均面向当前登录用户，仅作用于本人。
    """

    def get(self, request):
        return json_response({'show_after_update': get_user_show_after_update(request.user)})

    def put(self, request):
        form, error = JsonParser(
            Argument('show_after_update', type=bool, help='参数错误')
        ).parse(request.body)
        if error:
            return json_response(error=error)

        UserSetting.objects.update_or_create(
            user=request.user,
            key=POPUP_PREF_KEY,
            defaults={'value': 'true' if form.show_after_update else 'false'},
        )
        return json_response({'show_after_update': bool(form.show_after_update)})


class ReleaseNoteDetailView(View):
    """更新详情（仅已发布且对当前用户可见）"""

    def get(self, request, pk):
        note = _visible_note_or_none(request.user, pk)
        if not note:
            return json_response(error='更新日志不存在或无权限访问')
        return json_response(note.to_view(user=request.user, include_content=True))


class ReleaseNoteReadView(View):
    """标记已读"""

    def post(self, request, pk):
        note = _visible_note_or_none(request.user, pk)
        if not note:
            return json_response(error='更新日志不存在或无权限访问')
        _mark_read(note, request.user)
        return json_response()


class ReleaseNoteAckView(View):
    """重要更新确认"""

    def post(self, request, pk):
        note = _visible_note_or_none(request.user, pk)
        if not note:
            return json_response(error='更新日志不存在或无权限访问')
        _mark_read(note, request.user, acknowledged=True)
        return json_response()


# ==================== 管理端 ====================

def _validate_note_form(form):
    """校验更新日志表单，返回 (data, error)"""
    version = (form.version or '').strip()
    if not version:
        return None, '请输入版本号'
    if len(version) > VERSION_MAX_LEN:
        return None, '版本号长度不能超过 %d 个字符' % VERSION_MAX_LEN
    title = (form.title or '').strip()
    if not title:
        return None, '请输入更新标题'
    if len(title) > TITLE_MAX_LEN:
        return None, '标题长度不能超过 %d 个字符' % TITLE_MAX_LEN
    content = form.content or ''
    if not content.strip():
        return None, '请输入更新内容'
    if len(content) > CONTENT_MAX_LEN:
        return None, '内容长度不能超过 %d 个字符' % CONTENT_MAX_LEN
    return {
        'version': version,
        'title': title,
        'content': content,
        'is_required': bool(form.is_required),
    }, None


def _sync_roles(note, role_ids):
    """重建适用角色（空列表表示不限制角色）"""
    with transaction.atomic():
        note.roles.all().delete()
        if not role_ids:
            return
        names = {r.id: r.name for r in Role.objects.filter(id__in=role_ids)}
        for rid in role_ids:
            ReleaseNoteRole.objects.create(
                note=note,
                role_id=rid,
                role_name=names.get(rid, ''),
                tenant_id=getattr(note, 'tenant_id', ''),
            )


class ReleaseNoteAdminListView(View):
    """管理端列表"""

    def get(self, request):
        if not _has_perm(request.user, 'view'):
            return _deny()
        form, error = JsonParser(
            Argument('version', required=False),
            Argument('keyword', required=False),
            Argument('is_published', type=bool, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        qs = apply_tenant_filter(ReleaseNote.objects.all(), request.user)
        if form.keyword:
            qs = qs.filter(Q(version__icontains=form.keyword)
                           | Q(title__icontains=form.keyword)
                           | Q(content__icontains=form.keyword))
        if form.version:
            qs = qs.filter(version=form.version)
        if form.is_published is not None:
            qs = qs.filter(is_published=form.is_published)

        page, page_size = paginate(request)
        data = paginate_response(
            qs.order_by('-publish_at', '-id'), page, page_size,
            serialize_fn=lambda x: x.to_view(),
        )
        return json_response(data)

    def post(self, request):
        # 更新日志面向全平台所有用户，仅超级管理员可管理，避免租户管理员影响其他租户
        if not getattr(request.user, 'is_supper', False):
            return json_response(error='仅超级管理员可管理更新日志')
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('version', required=False),
            Argument('title', required=False),
            Argument('content', required=False),
            Argument('is_required', type=bool, required=False, default=False),
            Argument('role_ids', type=list, required=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        data, error = _validate_note_form(form)
        if error:
            return json_response(error=error)

        role_ids, error = parse_role_ids(form.role_ids)
        if error:
            return json_response(error=error)
        if role_ids:
            exists = Role.objects.filter(id__in=role_ids).count()
            if exists != len(set(role_ids)):
                return json_response(error='存在无效的角色')

        user = request.user
        now = timezone.now()
        if form.id:
            note = apply_tenant_filter(
                ReleaseNote.objects.filter(pk=form.id), user
            ).first()
            if not note:
                return json_response(error='更新日志不存在或无权限访问')
            if not _has_perm(user, 'edit'):
                return _deny()
            for key, value in data.items():
                setattr(note, key, value)
            note.updated_at = now
            note.updated_by_id = user.id
            note.updated_by_name = user.nickname or user.username
            with transaction.atomic():
                note.save()
                _sync_roles(note, role_ids)
            record_audit_event(
                request, 'update', target_type='release', target_id=note.id,
                target_name='%s %s' % (note.version, note.title),
                detail={'action_kind': 'release_note_update'},
            )
            return json_response(note.to_view())

        if not _has_perm(user, 'add'):
            return _deny()
        note = ReleaseNote(
            tenant_id=getattr(user, 'tenant_id', ''),
            created_by_id=user.id,
            created_by_name=user.nickname or user.username,
            **data,
        )
        with transaction.atomic():
            note.save()
            _sync_roles(note, role_ids)
        record_audit_event(
            request, 'create', target_type='release', target_id=note.id,
            target_name='%s %s' % (note.version, note.title),
            detail={'action_kind': 'release_note_create'},
        )
        return json_response(note.to_view())

    def delete(self, request):
        # 删除影响全平台读者，仅超级管理员可操作
        if not getattr(request.user, 'is_supper', False):
            return json_response(error='仅超级管理员可管理更新日志')
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误')
        ).parse(request.body)
        if error:
            return json_response(error=error)
        if not _has_perm(request.user, 'del'):
            return _deny()
        note = apply_tenant_filter(
            ReleaseNote.objects.filter(pk=form.id), request.user
        ).first()
        if not note:
            return json_response(error='更新日志不存在或无权限访问')
        target_name = '%s %s' % (note.version, note.title)
        with transaction.atomic():
            note.roles.all().delete()
            note.reads.all().delete()
            note.delete()
        record_audit_event(
            request, 'delete', target_type='release', target_id=form.id,
            target_name=target_name, detail={'action_kind': 'release_note_delete'},
        )
        return json_response()


class ReleaseNoteAdminDetailView(View):
    """管理端详情"""

    def get(self, request, pk):
        if not _has_perm(request.user, 'view'):
            return _deny()
        note = apply_tenant_filter(
            ReleaseNote.objects.filter(pk=pk), request.user
        ).first()
        if not note:
            return json_response(error='更新日志不存在或无权限访问')
        return json_response(note.to_view(include_content=True))


class ReleaseNoteAdminPublishView(View):
    """发布 / 撤回"""

    def post(self, request, pk):
        # 发布/撤回影响全平台读者，仅超级管理员可操作
        if not getattr(request.user, 'is_supper', False):
            return json_response(error='仅超级管理员可管理更新日志')
        if not _has_perm(request.user, 'publish'):
            return _deny()
        form, error = JsonParser(
            Argument('is_published', type=bool, help='参数错误')
        ).parse(request.body)
        if error:
            return json_response(error=error)

        note = apply_tenant_filter(
            ReleaseNote.objects.filter(pk=pk), request.user
        ).first()
        if not note:
            return json_response(error='更新日志不存在或无权限访问')
        if form.is_published:
            if not note.content.strip():
                return json_response(error='更新内容为空，无法发布')
            note.is_published = True
            note.publish_at = note.publish_at or timezone.now()
        else:
            note.is_published = False
        note.updated_at = timezone.now()
        note.updated_by_id = request.user.id
        note.updated_by_name = request.user.nickname or request.user.username
        note.save()
        record_audit_event(
            request, 'update', target_type='release', target_id=note.id,
            target_name='%s %s' % (note.version, note.title),
            detail={'action_kind': 'release_note_publish', 'is_published': form.is_published},
        )
        return json_response(note.to_view())
