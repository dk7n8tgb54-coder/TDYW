# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
多租户数据隔离中间件
自动为数据库查询添加租户过滤条件
"""
from django.utils.deprecation import MiddlewareMixin
from django.db import models
import threading
import logging

logger = logging.getLogger(__name__)

# 线程本地变量存储当前租户ID
_tenant_local = threading.local()


def set_current_tenant(tenant_id):
    """设置当前请求的租户ID"""
    _tenant_local.tenant_id = tenant_id


def get_current_tenant():
    """获取当前请求的租户ID"""
    return getattr(_tenant_local, 'tenant_id', None)


def clear_tenant():
    """清除当前租户"""
    if hasattr(_tenant_local, 'tenant_id'):
        delattr(_tenant_local, 'tenant_id')


class TenantMiddleware(MiddlewareMixin):
    """
    多租户中间件
    从用户信息中提取租户ID并存储到线程本地变量中
    """

    def process_request(self, request):
        # 如果请求中已有用户信息,提取租户ID
        if hasattr(request, 'user') and request.user:
            # 超级管理员可以查看所有租户数据,不设置租户限制
            if getattr(request.user, 'is_supper', False):
                set_current_tenant(None)
                logger.debug(f'[TENANT] 超级管理员 {request.user.username} 不设置租户限制')
            else:
                tenant_id = getattr(request.user, 'tenant_id', 'admin')
                set_current_tenant(tenant_id)
                logger.debug(f'[TENANT] 用户 {request.user.username} 租户ID: {tenant_id}')
        else:
            # 没有用户信息时,不设置租户限制
            clear_tenant()

    def process_response(self, request, response):
        # 请求处理完成后清除租户信息
        clear_tenant()
        return response


class TenantManager(models.Manager):
    """
    Custom Manager that automatically applies tenant filtering.

    Usage in models:
        class MyModel(models.Model):
            tenant_id = models.CharField(max_length=50, db_index=True)
            objects = TenantManager()           # Auto-filtered by tenant
            all_objects = models.Manager()      # No filtering (admin use)
    """

    def get_queryset(self):
        qs = super().get_queryset()
        tenant_id = get_current_tenant()
        if tenant_id and hasattr(self.model, 'tenant_id'):
            return qs.filter(tenant_id=tenant_id)
        return qs


class TenantModel(models.Model):
    """
    Abstract base model with tenant isolation.
    Inherit from this for automatic tenant filtering.
    """
    tenant_id = models.CharField(max_length=50, db_index=True, default='default')

    objects = TenantManager()
    all_objects = models.Manager()  # Unfiltered for admin operations

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.tenant_id:
            current_tenant = get_current_tenant()
            if current_tenant:
                self.tenant_id = current_tenant
        super().save(*args, **kwargs)


def auto_set_tenant(sender, instance, **kwargs):
    """
    信号处理器:保存模型时自动设置tenant_id
    """
    current_tenant = get_current_tenant()
    if current_tenant and hasattr(instance, 'tenant_id'):
        # 如果有当前租户且模型有tenant_id字段,自动设置
        if not instance.tenant_id:
            instance.tenant_id = current_tenant
            logger.debug(f'[TENANT] 自动设置租户ID: {current_tenant} for {instance.__class__.__name__}')


def auto_add_tenant_filter(sender, request, **kwargs):
    """
    信号处理器:获取数据时自动添加租户过滤
    注意:这个方案更复杂,暂时使用在Views中手动过滤的方式
    """
    pass
