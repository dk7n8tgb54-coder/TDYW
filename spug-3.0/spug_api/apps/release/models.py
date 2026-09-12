# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""系统版本更新日志模型

设计要点：
1. 与公告（Announcement）解耦：公告面向业务通知，更新日志面向平台版本，
   需要 version / title / is_required（强制确认）等版本语义字段，故独立建模。
2. 可见范围固定为全平台所有用户，不按租户隔离；仅超级管理员可管理。
3. 角色范围：ReleaseNoteRole 为空表示全部角色，否则仅命中角色可见。
4. 已读/确认：ReleaseNoteRead 唯一约束 (note, user)，
   is_required=True 的日志必须 is_acknowledged=True 才算处理完成。
"""
import json
import logging

from django.db import models
from django.db.models import Q
from django.utils import timezone

from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id

logger = logging.getLogger(__name__)

# ==================== 常量 ====================
VERSION_MAX_LEN = 50
TITLE_MAX_LEN = 200
CONTENT_MAX_LEN = 20000
SUMMARY_LEN = 200

# 未读接口单次最多返回的条数（避免历史日志堆积导致响应过大）
UNREAD_MAX_ITEMS = 10


class ReleaseNote(models.Model, TenantModelMixin):
    """版本更新日志（tdyw_release_notes）"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    version = models.CharField(max_length=VERSION_MAX_LEN, default='', help_text='版本号')
    title = models.CharField(max_length=TITLE_MAX_LEN, default='', help_text='更新标题')
    content = models.TextField(default='', help_text='更新内容')
    is_published = models.BooleanField(default=False, help_text='是否发布')
    is_required = models.BooleanField(default=False, help_text='是否必须确认')
    publish_at = models.DateTimeField(null=True, blank=True, help_text='发布时间')

    created_at = models.DateTimeField(auto_now_add=True, help_text='创建时间')
    created_by_id = models.IntegerField(null=True, blank=True, help_text='创建人ID')
    created_by_name = models.CharField(max_length=100, default='', help_text='创建人姓名快照')
    updated_at = models.DateTimeField(null=True, blank=True, help_text='更新时间')
    updated_by_id = models.IntegerField(null=True, blank=True, help_text='更新人ID')
    updated_by_name = models.CharField(max_length=100, default='', help_text='更新人姓名快照')

    def _role_ids(self):
        return [r.role_id for r in self.roles.all()]

    def to_view(self, user=None, include_content=False):
        now = timezone.now()
        data = {
            'id': self.id,
            'version': self.version,
            'title': self.title,
            'is_published': self.is_published,
            'is_required': self.is_required,
            'publish_at': self.publish_at,
            'is_new': bool(self.publish_at and (now - self.publish_at).days <= 7),
            'created_at': self.created_at,
            'created_by_name': self.created_by_name,
            'updated_at': self.updated_at,
            'updated_by_name': self.updated_by_name,
            '_role_ids': self._role_ids(),
        }
        if include_content:
            data['content'] = self.content
        else:
            data['summary'] = (self.content or '')[:SUMMARY_LEN]
        if user is not None:
            read = ReleaseNoteRead.objects.filter(note_id=self.id, user_id=user.id).first()
            data['is_read'] = read is not None
            data['is_acknowledged'] = bool(read and read.is_acknowledged)
            data['read_at'] = read.read_at if read else None
        return data

    def __repr__(self):
        return '<ReleaseNote %s %s>' % (self.id, self.version)

    class Meta:
        db_table = 'tdyw_release_notes'
        verbose_name = '版本更新日志'
        verbose_name_plural = '版本更新日志'
        ordering = ('-publish_at', '-id')
        indexes = [
            models.Index(fields=['is_published', 'publish_at', 'id'], name='rel_pub_time_idx'),
            models.Index(fields=['version', 'publish_at'], name='rel_version_idx'),
            models.Index(fields=['tenant_id', 'is_published'], name='rel_tenant_idx'),
        ]


class ReleaseNoteRole(models.Model, TenantModelMixin):
    """更新日志适用角色（tdyw_release_note_roles）

    为空表示该日志对所有角色可见；否则仅列表中的角色可见。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    note = models.ForeignKey(ReleaseNote, models.CASCADE, related_name='roles', help_text='更新日志')
    role_id = models.IntegerField(help_text='角色ID')
    role_name = models.CharField(max_length=100, default='', help_text='角色名称快照')
    created_at = models.DateTimeField(auto_now_add=True, help_text='创建时间')

    def __repr__(self):
        return '<ReleaseNoteRole %s->%s>' % (self.note_id, self.role_id)

    class Meta:
        db_table = 'tdyw_release_note_roles'
        verbose_name = '更新日志适用角色'
        verbose_name_plural = '更新日志适用角色'
        ordering = ('id',)
        constraints = [
            models.UniqueConstraint(
                fields=['note_id', 'role_id'], name='uniq_release_note_role',
            ),
        ]
        indexes = [
            models.Index(fields=['role_id'], name='rel_role_idx'),
        ]


class ReleaseNoteRead(models.Model, TenantModelMixin):
    """更新日志已读/确认表（tdyw_release_note_reads）

    tenant_id 表示读者所属租户，由调用方显式写入。
    重要更新（is_required）需 is_acknowledged=True 才算处理完成。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    note = models.ForeignKey(ReleaseNote, models.CASCADE, related_name='reads', help_text='更新日志')
    user_id = models.IntegerField(help_text='用户ID')
    username = models.CharField(max_length=100, default='', help_text='登录账号快照')
    nickname = models.CharField(max_length=100, default='', help_text='姓名快照')
    is_acknowledged = models.BooleanField(default=False, help_text='是否已确认')
    read_at = models.DateTimeField(auto_now_add=True, help_text='阅读时间')
    acknowledged_at = models.DateTimeField(null=True, blank=True, help_text='确认时间')

    def __repr__(self):
        return '<ReleaseNoteRead %s/%s>' % (self.note_id, self.user_id)

    class Meta:
        db_table = 'tdyw_release_note_reads'
        verbose_name = '更新日志已读'
        verbose_name_plural = '更新日志已读'
        ordering = ('-read_at', '-id')
        constraints = [
            models.UniqueConstraint(
                fields=['note_id', 'user_id'], name='uniq_release_note_read_user',
            ),
        ]
        indexes = [
            models.Index(fields=['user_id', 'note_id'], name='rel_read_user_idx'),
        ]


# ==================== 可见性 ====================

def visible_release_notes_for_user(user, now=None):
    """当前用户可见的已发布更新日志

    可见条件：已发布 + 发布时间 <= now
              + (超管 或 无角色限制 或 命中角色)
    更新日志面向全平台所有用户，不按租户隔离。
    """
    now = now or timezone.now()
    qs = ReleaseNote.objects.filter(is_published=True, publish_at__lte=now)
    if getattr(user, 'is_supper', False):
        return qs.distinct()

    role_ids = _user_role_ids(user)
    qs = qs.filter(Q(roles__isnull=True) | Q(roles__role_id__in=role_ids))
    return qs.distinct()


def unread_release_notes_for_user(user, now=None):
    """当前用户尚未处理完的更新日志

    普通日志：无已读记录即为未读；
    重要日志（is_required）：已读但未确认仍视为未处理。
    """
    notes = visible_release_notes_for_user(user, now)
    reads = ReleaseNoteRead.objects.filter(user_id=user.id).select_related('note')
    done_ids = [
        r.note_id for r in reads
        if (not r.note.is_required) or r.is_acknowledged
    ]
    if done_ids:
        notes = notes.exclude(id__in=done_ids)
    return notes.order_by('-is_required', '-publish_at', '-id')


def _user_role_ids(user):
    """获取用户角色ID列表（无 roles 关系时返回空列表）"""
    try:
        return list(user.roles.values_list('id', flat=True))
    except Exception:  # pragma: no cover - 防御：匿名/自定义用户对象
        logger.debug('[RELEASE] 读取用户角色失败 user=%s', getattr(user, 'username', ''))
        return []


def parse_role_ids(raw):
    """解析角色ID参数，返回 (role_ids, error)"""
    if raw in (None, '', []):
        return [], None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return None, '适用角色参数格式错误'
    if not isinstance(raw, list):
        return None, '适用角色参数格式错误'
    role_ids = []
    for item in raw:
        try:
            role_ids.append(int(item))
        except (TypeError, ValueError):
            return None, '适用角色参数格式错误'
    return role_ids, None
