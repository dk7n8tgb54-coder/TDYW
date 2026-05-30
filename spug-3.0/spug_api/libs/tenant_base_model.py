# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
租户模型抽象基类
为所有需要租户隔离的业务模型提供统一的 tenant_id 字段和 TENANT_TYPE 常量

子类模型使用方式：
    class FaultRecord(models.Model, TenantModelMixin):
        objects = TenantModelManager()
        tenant_id = make_tenant_id()
        ...

设计说明：
- TenantModelMixin 不继承 models.Model，避免 Django 元类在应用加载时的循环导入
- make_tenant_id() 确保所有模型使用一致的字段定义
- TenantQuerySet / TenantModelManager 提供 .for_user() 便捷过滤方法
- 通过 class_prepared 信号自动为所有子类注册 pre_save 信号
"""
from django.db import models
from django.db.models.signals import class_prepared
from libs import ModelMixin


TENANT_TYPE_PRIVATE = 'PRIVATE'
TENANT_TYPE_PUBLIC = 'PUBLIC'


def make_tenant_id():
    """生成统一的 tenant_id 字段定义"""
    return models.CharField(max_length=50, default='', help_text='租户标识')


class TenantQuerySet(models.QuerySet):
    """租户感知的 QuerySet，提供便捷的租户过滤方法"""

    def for_user(self, user, strict_mode=False):
        """
        按用户的租户过滤 QuerySet
        等价于 apply_tenant_filter(self, user, strict_mode=strict_mode)
        """
        from libs.tenant_utils import apply_tenant_filter
        return apply_tenant_filter(self, user, strict_mode=strict_mode)


class TenantModelManager(models.Manager):
    """租户感知的 Manager"""

    def get_queryset(self):
        return TenantQuerySet(self.model, using=self._db)

    def for_user(self, user, strict_mode=False):
        """便捷方法：从 Manager 直接过滤"""
        return self.get_queryset().for_user(user, strict_mode=strict_mode)


class TenantModelMixin(ModelMixin):
    """
    租户隔离模型的混合类
    - 提供 TENANT_TYPE 常量、to_dict()、update_by_dict() 等方法
    - 提供 TenantModelManager 默认 Manager（支持 .for_user()）
    - 子类同时继承 models.Model + TenantModelMixin 即可
    """
    TENANT_TYPE = TENANT_TYPE_PRIVATE
    objects = TenantModelManager()


def _auto_register_tenant_signals(sender, **kwargs):
    """
    当每个模型类被创建时，自动注册 pre_save 信号
    避免 AppConfig.ready() 时序问题
    """
    meta = getattr(sender, '_meta', None)
    if meta is None or getattr(meta, 'abstract', False):
        return
    if issubclass(sender, TenantModelMixin) and sender is not TenantModelMixin:
        try:
            from django.db.models.signals import pre_save
            from libs.tenant_middleware import auto_set_tenant
            pre_save.connect(auto_set_tenant, sender=sender, weak=False)
        except ImportError:
            pass  # 初始化阶段


class_prepared.connect(_auto_register_tenant_signals)



