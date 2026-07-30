# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import models
from django.core.cache import cache
from libs import ModelMixin
from django.contrib.auth.hashers import make_password, check_password
import json

# 权限缓存兜底 TTL（秒）。与 Django CACHES 默认 TIMEOUT 一致。
# 正常情况下靠 Role.perms_version 版本校验决定是否重算，TTL 仅作最终兜底。
PERMS_CACHE_TTL = 300


class User(models.Model, ModelMixin):
    username = models.CharField(max_length=100)
    nickname = models.CharField(max_length=100)
    password_hash = models.CharField(max_length=100)  # hashed password
    type = models.CharField(max_length=20, default='default')
    is_supper = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    access_token = models.CharField(max_length=32, unique=True)
    token_expired = models.IntegerField(null=True)
    last_login = models.DateTimeField(null=True, blank=True)
    last_ip = models.CharField(max_length=50)
    wx_token = models.CharField(max_length=50, default='', blank=True)
    tenant_id = models.CharField(max_length=50, default='admin', db_index=True)
    roles = models.ManyToManyField('Role', db_table='user_role_rel')

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey('User', models.PROTECT, related_name='+', null=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey('User', models.PROTECT, related_name='+', null=True)

    @staticmethod
    def make_password(plain_password: str) -> str:
        return make_password(plain_password, hasher='pbkdf2_sha256')

    def verify_password(self, plain_password: str) -> bool:
        return check_password(plain_password, self.password_hash)

    def get_perms_cache(self):
        """读取权限缓存。返回 (version, perms) tuple 或 None。

        旧格式缓存（set 实例）会被 page_perms 识别为失效并重算。
        """
        return cache.get(f'perms_{self.id}')

    def set_perms_cache(self, value=None, version=None):
        """写入/清除权限缓存。

        - 不传 value：删除缓存（失效信号，向后兼容旧调用 user.set_perms_cache()）
        - 传 value + version：写入 (version, value)，TTL=PERMS_CACHE_TTL
        """
        key = f'perms_{self.id}'
        if value is None:
            cache.delete(key)
        else:
            cache.set(key, (version, value), PERMS_CACHE_TTL)

    def _get_roles_perms_version(self):
        """获取用户所有角色 perms_version 的最大值，作为缓存新鲜度指纹。

        只查询整数字段，避免读取 page_perms 大文本，保持轻量。
        """
        versions = list(self.roles.values_list('perms_version', flat=True))
        return max(versions) if versions else 0

    @property
    def page_perms(self):
        cached = self.get_perms_cache()
        current_version = self._get_roles_perms_version()
        # 命中条件：缓存为 (version, perms) tuple 且 version 与当前一致。
        # 旧格式缓存（set 实例）或 version 不匹配 → 视为失效，重算。
        # 这样可根治迁移/SQL/竞态等任何漏失效路径写入的残缺缓存：
        # 只要 Role.page_perms 被修改并 save，perms_version 自增，
        # 用户下次读取时 version 不匹配即自动重算。
        if cached and isinstance(cached, tuple) and cached[0] == current_version:
            return cached[1]
        data = set()
        for item in self.roles.all():
            if item.page_perms:
                perms = json.loads(item.page_perms)
                for m, v in perms.items():
                    for p, d in v.items():
                        data.update(f'{m}.{p}.{x}' for x in d)
        self.set_perms_cache(data, current_version)
        return data

    @property
    def group_perms(self):
        data = set()
        for item in self.roles.all():
            if item.group_perms:
                data.update(json.loads(item.group_perms))
        return list(data)

    def has_perms(self, codes):
        if self.is_supper:
            return True
        return bool(self.page_perms.intersection(codes))

    @property
    def is_global_admin(self):
        """
        判断用户是否拥有全局管理员角色
        """
        if self.is_supper:
            return True
        return self.roles.filter(is_global_admin=True).exists()

    @property
    def is_authenticated(self):
        """
        兼容 Django 认证系统
        通过中间件验证的用户视为已认证
        """
        return True

    @property
    def is_anonymous(self):
        """
        兼容 Django 认证系统
        """
        return False

    def __repr__(self):
        return '<User %r>' % self.username

    class Meta:
        db_table = 'users'
        ordering = ('-id',)


class Role(models.Model, ModelMixin):
    name = models.CharField(max_length=50)
    desc = models.CharField(max_length=255, default='')
    page_perms = models.TextField(default='')
    deploy_perms = models.TextField(default='')
    group_perms = models.TextField(default='')
    is_global_admin = models.BooleanField(default=False, help_text='全局管理员角色')
    # 角色归属与系统标识（用户角色委派权限边界）
    # tenant_id 为 null 表示平台级角色，仅超级管理员可管理和分配
    # is_system=True 表示系统内置角色，普通管理员不可编辑/删除/分配
    tenant_id = models.CharField(max_length=50, blank=True, db_index=True, default='')
    is_system = models.BooleanField(default=False, db_index=True)
    # 权限版本号：每次 page_perms 变更并 save 时自增。
    # User.page_perms 缓存以用户所有角色的 max(perms_version) 作为新鲜度指纹，
    # 版本不一致即重算，从而无需依赖各变更路径主动调用 clear_perms_cache。
    # migration 0007 将历史角色初始化为 1，0 仅表示尚未 save 的新实例。
    perms_version = models.PositiveIntegerField(default=0, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='+')

    def to_dict(self, *args, **kwargs):
        tmp = super().to_dict(*args, **kwargs)
        tmp['page_perms'] = json.loads(self.page_perms) if self.page_perms else {}
        tmp['deploy_perms'] = json.loads(self.deploy_perms) if self.deploy_perms else {}
        tmp['group_perms'] = json.loads(self.group_perms) if self.group_perms else []
        tmp['is_global_admin'] = self.is_global_admin
        tmp['is_system'] = self.is_system
        tmp['tenant_id'] = self.tenant_id
        tmp['used'] = self.user_set.filter(deleted_by_id__isnull=True).count()
        return tmp

    def add_deploy_perm(self, target, value):
        perms = {'apps': [], 'envs': []}
        if self.deploy_perms:
            perms.update(json.loads(self.deploy_perms))
        perms[target].append(value)
        self.deploy_perms = json.dumps(perms)
        self.save()

    # 触发 perms_version 自增的权限相关字段。
    # 仅 page_perms 参与 User.page_perms 缓存，故只在 page_perms 变化时 bump。
    # deploy_perms/group_perms 不被 User 缓存（group_perms property 每次现算），无需 bump。
    PERM_CACHE_RELEVANT_FIELDS = ('page_perms',)

    def save(self, *args, **kwargs):
        """重写 save：检测 page_perms 变化时自增 perms_version。

        覆盖所有通过 ORM 修改 page_perms 的路径（API patch、迁移 RunPython
        里的 role.save(update_fields=['page_perms'])、add_deploy_perm 等），
        无需各调用方显式 bump。Role.objects.filter().update() 批量更新不走
        save，但当前代码中 .update() 不修改 page_perms，故无需处理。
        """
        update_fields = kwargs.get('update_fields')
        if self.pk is None:
            if not self.perms_version:
                self.perms_version = 1
        else:
            relevant = self.PERM_CACHE_RELEVANT_FIELDS
            if update_fields is None:
                check_fields = relevant
            else:
                check_fields = tuple(f for f in relevant if f in update_fields)
            if check_fields:
                old = Role.objects.filter(pk=self.pk).only(*check_fields).first()
                if old is None or any(
                    getattr(self, f) != getattr(old, f) for f in check_fields
                ):
                    self.perms_version = (self.perms_version or 0) + 1
                    if update_fields is not None and 'perms_version' not in update_fields:
                        kwargs['update_fields'] = list(update_fields) + ['perms_version']
        super().save(*args, **kwargs)

    def clear_perms_cache(self):
        """立即清除该角色所有关联用户的权限缓存。

        新机制下 User.page_perms 靠 perms_version 版本校验自动失效，
        此方法作为"立即失效"优化保留（不必等下次读取才发现版本不匹配），
        并向后兼容现有调用点。
        """
        for item in self.user_set.all():
            item.set_perms_cache()

    def __repr__(self):
        return '<Role name=%r>' % self.name

    class Meta:
        db_table = 'roles'
        ordering = ('-id',)
        unique_together = (('tenant_id', 'name'),)


class History(models.Model, ModelMixin):
    username = models.CharField(max_length=100, default='')
    type = models.CharField(max_length=20, default='default')
    ip = models.CharField(max_length=50)
    agent = models.CharField(max_length=255, default='', blank=True)
    message = models.CharField(max_length=255, default='')
    is_success = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'login_histories'
        ordering = ('-id',)


class Tenant(models.Model, ModelMixin):
    """租户模型"""
    id = models.CharField(max_length=50, primary_key=True, help_text='租户标识')
    name = models.CharField(max_length=100, help_text='租户名称')
    description = models.TextField(default='', blank=True, help_text='租户描述')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<Tenant %r>' % self.id

    class Meta:
        db_table = 'tenants'
        verbose_name = '租户'
        verbose_name_plural = '租户'
        ordering = ('id',)
