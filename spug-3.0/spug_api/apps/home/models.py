# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import models
from django.db.models import Q
from libs.mixins import ModelMixin
from django.utils import timezone
from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id
from datetime import timedelta
import json
import logging

logger = logging.getLogger(__name__)


# ==================== 公告发布模块 ====================
SCOPE_ALL = 'all'
SCOPE_TENANT = 'tenant'

STATUS_UNPUBLISHED = 'unpublished'
STATUS_PUBLISHED = 'published'
STATUS_EXPIRED = 'expired'

SCOPE_CHOICES = (
    (SCOPE_ALL, '全平台'),
    (SCOPE_TENANT, '指定部门'),
)

STATUS_CHOICES = (
    (STATUS_UNPUBLISHED, '未发布'),
    (STATUS_PUBLISHED, '已发布'),
    (STATUS_EXPIRED, '已过期'),
)

ANN_CONTENT_MAX_LEN = 20000
TITLE_MAX_LEN = 200


class Notice(models.Model, ModelMixin):
    title = models.CharField(max_length=100)
    content = models.TextField()
    is_stress = models.BooleanField(default=False)
    read_ids = models.TextField(default='[]')
    sort_id = models.IntegerField(default=0, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def to_view(self):
        tmp = self.to_dict()
        tmp['read_ids'] = json.loads(self.read_ids)
        return tmp

    class Meta:
        db_table = 'notices'
        ordering = ('-sort_id',)


class Navigation(models.Model, ModelMixin):
    title = models.CharField(max_length=64)
    desc = models.CharField(max_length=128)
    logo = models.TextField()
    links = models.TextField()
    sort_id = models.IntegerField(default=0, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def to_view(self):
        tmp = self.to_dict()
        tmp['links'] = json.loads(self.links)
        return tmp

    class Meta:
        db_table = 'navigations'
        ordering = ('-sort_id',)


class Announcement(models.Model, TenantModelMixin):
    """公告主表（tdyw_announcements）

    状态三态：unpublished / published / expired。
    - status 存储状态（撤回回到 unpublished；定时任务将过期置为 expired）
    - 接口同时实时计算 computed_status 兜底定时任务延迟
    tenant_id 为创建人所属租户（owner），可见性由 scope_type + AnnouncementScope 决定。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    title = models.CharField(max_length=TITLE_MAX_LEN, help_text='公告标题')
    content = models.TextField(help_text='公告内容（首期纯文本）')
    scope_type = models.CharField(max_length=20, choices=SCOPE_CHOICES, default=SCOPE_ALL, help_text='发布范围')
    publish_department_id = models.CharField(max_length=50, default='', help_text='发布部门ID（首期对应 Tenant.id）')
    publish_department_name = models.CharField(max_length=100, default='', help_text='发布部门名称快照')

    effective_start_at = models.DateTimeField(default=timezone.now, help_text='生效开始时间')
    effective_end_at = models.DateTimeField(null=True, blank=True, help_text='生效结束时间，空表示长期有效')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_UNPUBLISHED, help_text='存储状态')
    published_at = models.DateTimeField(null=True, blank=True, help_text='实际发布时间')
    published_by_id = models.IntegerField(null=True, blank=True, help_text='发布人ID')
    published_by_name = models.CharField(max_length=100, default='', help_text='发布人姓名快照')

    withdrawn_at = models.DateTimeField(null=True, blank=True, help_text='撤回时间')
    withdrawn_by_id = models.IntegerField(null=True, blank=True, help_text='撤回人ID')
    withdrawn_by_name = models.CharField(max_length=100, default='', help_text='撤回人姓名快照')

    is_important = models.BooleanField(default=False, help_text='是否重要')
    is_deleted = models.BooleanField(default=False, help_text='软删除标识')

    # 操作人快照（姓名只展示，身份以账号ID为准；不使用FK避免跨库删除约束）
    created_at = models.DateTimeField(auto_now_add=True, help_text='创建时间')
    created_by_id = models.IntegerField(null=True, blank=True, help_text='创建人ID')
    created_by_name = models.CharField(max_length=100, default='', help_text='创建人姓名快照')
    updated_at = models.DateTimeField(null=True, blank=True, help_text='更新时间')
    updated_by_id = models.IntegerField(null=True, blank=True, help_text='更新人ID')
    updated_by_name = models.CharField(max_length=100, default='', help_text='更新人姓名快照')
    deleted_at = models.DateTimeField(null=True, blank=True, help_text='删除时间')
    deleted_by_id = models.IntegerField(null=True, blank=True, help_text='删除人ID')
    deleted_by_name = models.CharField(max_length=100, default='', help_text='删除人姓名快照')

    def compute_status(self, now=None):
        """实时计算展示状态（兜底定时任务延迟）"""
        now = now or timezone.now()
        if self.is_deleted:
            return STATUS_UNPUBLISHED
        if self.status == STATUS_UNPUBLISHED:
            return STATUS_UNPUBLISHED
        start = self.effective_start_at
        end = self.effective_end_at
        if start and now < start:
            return STATUS_UNPUBLISHED
        if end and now > end:
            return STATUS_EXPIRED
        return STATUS_PUBLISHED

    def is_visible_to(self, user, now=None):
        """当前用户是否可见（严格按方案 6.1 规则）"""
        now = now or timezone.now()
        if self.is_deleted:
            return False
        if self.compute_status(now) != STATUS_PUBLISHED:
            return False
        if self.scope_type == SCOPE_ALL:
            return True
        tenant_id = getattr(user, 'tenant_id', '')
        return self.scopes.filter(tenant_id=tenant_id).exists()

    def _is_new(self, now):
        if not self.published_at:
            return False
        return (now - self.published_at) <= timedelta(days=3)

    def _attachment_count(self):
        from apps.evidence.models import EvidenceAttachment
        return EvidenceAttachment.objects.filter(
            module='announcement', object_id=str(self.id), is_deleted=False
        ).count()

    def to_view(self, user=None, include_content=False):
        now = timezone.now()
        data = {
            'id': self.id,
            'title': self.title,
            'scope_type': self.scope_type,
            'scope_label': '全平台' if self.scope_type == SCOPE_ALL else '指定部门',
            'publish_department_id': self.publish_department_id,
            'publish_department_name': self.publish_department_name,
            'effective_start_at': self.effective_start_at,
            'effective_end_at': self.effective_end_at,
            'status': self.status,
            'computed_status': self.compute_status(now),
            'is_important': self.is_important,
            'is_new': self._is_new(now),
            'published_at': self.published_at,
            'published_by_name': self.published_by_name,
            'withdrawn_at': self.withdrawn_at,
            'withdrawn_by_name': self.withdrawn_by_name,
            'created_at': self.created_at,
            'created_by_name': self.created_by_name,
            'updated_at': self.updated_at,
            'updated_by_name': self.updated_by_name,
            'attachment_count': self._attachment_count(),
        }
        if include_content:
            data['content'] = self.content
        else:
            data['summary'] = (self.content or '')[:120]
        if user is not None:
            data['is_read'] = AnnouncementRead.objects.filter(
                announcement_id=self.id, user_id=user.id
            ).exists()
        return data

    def __repr__(self):
        return '<Announcement %s %s>' % (self.id, self.title)

    class Meta:
        db_table = 'tdyw_announcements'
        verbose_name = '公告'
        verbose_name_plural = '公告'
        ordering = ('-published_at', '-id')
        indexes = [
            models.Index(fields=['status', 'published_at', 'id'], name='ann_status_time_idx'),
            models.Index(fields=['scope_type', 'status'], name='ann_scope_idx'),
            models.Index(fields=['publish_department_id', 'published_at'], name='ann_pub_dept_idx'),
            models.Index(fields=['effective_start_at', 'effective_end_at'], name='ann_effective_idx'),
            models.Index(fields=['is_deleted', 'status'], name='ann_deleted_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(status__in=['unpublished', 'published', 'expired']),
                name='ann_status_valid',
            ),
            models.CheckConstraint(
                check=models.Q(scope_type__in=['all', 'tenant']),
                name='ann_scope_type_valid',
            ),
            models.CheckConstraint(
                check=models.Q(effective_end_at__gte=models.F('effective_start_at'))
                      | models.Q(effective_end_at__isnull=True),
                name='ann_end_after_start',
            ),
        ]


class AnnouncementScope(models.Model, TenantModelMixin):
    """发布范围表（tdyw_announcement_scopes）

    scope_type=tenant 时，写入一个或多个目标租户。
    注意：tenant_id 此处表示“目标部门/租户”，由调用方显式写入，
    不会被 pre_save 信号覆盖（信号仅在 tenant_id 为空时填充）。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    announcement = models.ForeignKey(Announcement, models.CASCADE, related_name='scopes', help_text='公告')
    tenant_name = models.CharField(max_length=100, default='', help_text='目标部门/租户名称快照')
    created_at = models.DateTimeField(auto_now_add=True, help_text='创建时间')

    def __repr__(self):
        return '<AnnouncementScope %s->%s>' % (self.announcement_id, self.tenant_id)

    class Meta:
        db_table = 'tdyw_announcement_scopes'
        verbose_name = '公告发布范围'
        verbose_name_plural = '公告发布范围'
        ordering = ('id',)
        constraints = [
            models.UniqueConstraint(
                fields=['announcement_id', 'tenant_id'],
                name='uniq_announcement_scope_tenant',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id'], name='ann_scope_tenant_idx'),
        ]


class AnnouncementRead(models.Model, TenantModelMixin):
    """已读表（tdyw_announcement_reads）

    替代旧 Notice.read_ids JSON，便于未读统计与并发标记。
    tenant_id 表示读者所属租户，由调用方显式写入。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    announcement = models.ForeignKey(Announcement, models.CASCADE, related_name='reads', help_text='公告')
    user_id = models.IntegerField(help_text='用户ID')
    username = models.CharField(max_length=100, default='', help_text='登录账号快照')
    nickname = models.CharField(max_length=100, default='', help_text='姓名快照')
    read_at = models.DateTimeField(auto_now_add=True, help_text='阅读时间')

    def __repr__(self):
        return '<AnnouncementRead %s/%s>' % (self.announcement_id, self.user_id)

    class Meta:
        db_table = 'tdyw_announcement_reads'
        verbose_name = '公告已读'
        verbose_name_plural = '公告已读'
        ordering = ('-read_at', '-id')
        constraints = [
            models.UniqueConstraint(
                fields=['announcement_id', 'user_id'],
                name='uniq_announcement_read_user',
            ),
        ]
        indexes = [
            models.Index(fields=['user_id', 'announcement_id'], name='ann_read_user_idx'),
            models.Index(fields=['announcement_id', 'user_id'], name='ann_read_notice_idx'),
        ]


def visible_announcements_for_user(user, now=None):
    """封装用户可见公告 QuerySet（方案 9.2）

    可见条件：未删除 + 已发布 + 生效开始 <= now + (无结束 或 结束 >= now)
              + (全平台 或 用户租户在范围表)
    """
    now = now or timezone.now()
    tenant_id = getattr(user, 'tenant_id', '')
    qs = Announcement.objects.filter(
        is_deleted=False,
        status=STATUS_PUBLISHED,
        effective_start_at__lte=now,
    ).filter(
        Q(effective_end_at__isnull=True) | Q(effective_end_at__gte=now)
    ).filter(
        Q(scope_type=SCOPE_ALL) | Q(scopes__tenant_id=tenant_id)
    ).distinct()
    return qs
