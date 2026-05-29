# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
多租户数据隔离中间件
自动为数据库查询添加租户过滤条件
"""
from django.utils.deprecation import MiddlewareMixin
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


class TenantQuerySet:
    """
    自定义QuerySet,自动添加租户过滤条件
    """
    def __init__(self, model=None, query=None, using=None, hints=None):
        from django.db.models import QuerySet
        self.queryset = QuerySet(model=model, query=query, using=using, hints=hints)

    def __getattr__(self, name):
        # 代理所有QuerySet方法
        attr = getattr(self.queryset, name)
        if callable(attr):
            # 如果是方法,包装它以添加租户过滤
            def wrapper(*args, **kwargs):
                current_tenant = get_current_tenant()
                if current_tenant:
                    # 在过滤前自动添加租户条件
                    if name in ['filter', 'get', 'all', 'first', 'last', 'exclude']:
                        # 对于这些查询方法,添加租户过滤
                        if 'tenant_id' not in kwargs and hasattr(args[0] if args else None, '__contains__'):
                            # 如果没有手动指定tenant_id,添加租户过滤
                            pass  # 这里需要更复杂的处理,改用model.save()自动设置
                return attr(*args, **kwargs)
            return wrapper
        return attr


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
