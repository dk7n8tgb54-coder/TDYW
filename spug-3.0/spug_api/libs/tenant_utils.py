# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
租户工具类
提供租户查询、过滤、管理等辅助功能
"""
from django.db.models import Q
import logging

logger = logging.getLogger(__name__)


# 定义需要租户隔离的模型
TENANT_MODELS = [
    'RunLog',
    'FaultRecord',
    'FaultPart',
    'Interference',
    'UpgradeRecord',
    'UpgradeTemplate',
    'DutyRecord',
    'ScheduleStaff',
    'ScheduleShift',
    'ScheduleShiftTime',
    'Schedule',
    'ScheduleSwap',
    'ScheduleSubstitute',
    'DocumentFolderPrivate',
    'DocumentFilePrivate',
]


def get_tenant_filter(request_user):
    """
    获取租户过滤条件
    如果是超级管理员,返回空条件(查询所有数据)
    如果是普通用户,返回租户过滤条件
    """
    if getattr(request_user, 'is_supper', False):
        return Q()  # 空条件,不限制
    tenant_id = getattr(request_user, 'tenant_id', 'admin')
    return Q(tenant_id=tenant_id)


def apply_tenant_filter(queryset, request_user, strict_mode=False):
    """
    应用租户过滤到QuerySet
    返回过滤后的QuerySet

    Args:
        queryset: 要过滤的QuerySet
        request_user: 当前请求用户
        strict_mode: 严格模式（资料库私有空间使用）
                    True: 超级管理员和全局管理员都按租户过滤
                    False: 超级管理员和全局管理员都不过滤
    """
    username = getattr(request_user, 'username', 'Unknown')
    is_supper = getattr(request_user, 'is_supper', False)

    # 尝试直接访问 is_global_admin 属性（它是一个 @property）
    try:
        is_global_admin = request_user.is_global_admin if hasattr(request_user, 'is_global_admin') else False
    except:
        is_global_admin = False

    # 【修改】严格模式下，超级管理员也按租户过滤
    if is_supper:
        if strict_mode:
            # 严格模式：超级管理员也按租户过滤
            tenant_id = getattr(request_user, 'tenant_id', 'admin')
            filtered_queryset = queryset.filter(tenant_id=tenant_id)
            logger.debug(f'[TENANT FILTER] 超级管理员 {username} (租户:{tenant_id}) - 严格模式，应用租户过滤')
            return filtered_queryset
        else:
            # 非严格模式：超级管理员不过滤
            logger.debug(f'[TENANT FILTER] 超级管理员 {username} - 不应用租户过滤')
            return queryset

    # 【修改】全局管理员在非严格模式下可查看所有租户数据（与超管相同的数据可见性）
    if is_global_admin and not strict_mode:
        logger.debug(f'[TENANT FILTER] 全局管理员 {username} - 不应用租户过滤')
        return queryset

    # 严格模式下的全局管理员 或 普通用户，都按租户过滤
    tenant_id = getattr(request_user, 'tenant_id', 'admin')
    filtered_queryset = queryset.filter(tenant_id=tenant_id)
    count_before = queryset.count() if hasattr(queryset, 'count') else '?'
    count_after = filtered_queryset.count() if hasattr(filtered_queryset, 'count') else '?'

    user_type = "全局管理员(严格)" if is_global_admin else "普通用户"
    logger.debug(f'[TENANT FILTER] {user_type} {username} (租户:{tenant_id}) - 过滤前:{count_before}, 过滤后:{count_after}')

    # 告警：如果过滤拦截了所有数据，可能是越权尝试或配置错误
    if count_before > 0 and count_after == 0:
        logger.warning(
            f'[TENANT FILTER] ⚠️ 潜在越权拦截！'
            f'用户={username}, 租户={tenant_id}, '
            f'拦截记录数={count_before}, 过滤后=0'
        )

    return filtered_queryset


def set_instance_tenant(instance, request_user):
    """
    设置模型实例的tenant_id
    共享租户场景：所有用户（包括超管）都设置tenant_id，确保创建的数据属于其租户
    """
    if hasattr(instance, 'tenant_id'):
        instance.tenant_id = getattr(request_user, 'tenant_id', 'admin')
        logger.debug(f'[TENANT SET] {request_user.username} 设置 {instance.__class__.__name__} 租户ID为: {instance.tenant_id}')
    return instance


def assign_tenant_id(data_dict, request_user):
    """
    为创建数据的字典/表单对象赋值tenant_id
    统一替代各views中重复的 if not getattr(request.user, 'is_supper', False): form.tenant_id = ...

    Args:
        data_dict: 包含创建数据的字典或JsonParser的Form对象
        request_user: 当前请求用户

    Returns:
        传入的data_dict（已设置tenant_id）
    """
    tenant_id = getattr(request_user, 'tenant_id', 'admin')
    if isinstance(data_dict, dict):
        data_dict['tenant_id'] = tenant_id
    else:
        data_dict.tenant_id = tenant_id
    return data_dict


def is_superuser(user):
    """
    判断是否是超级管理员
    """
    return getattr(user, 'is_supper', False)


def is_global_admin(user):
    """
    判断是否是全局管理员（可查看所有租户数据）
    """
    return getattr(user, 'is_global_admin', False)


def can_view_all_tenants(user):
    """
    判断用户是否可以查看所有租户数据
    """
    return getattr(user, 'is_supper', False) or getattr(user, 'is_global_admin', False)


def get_user_tenant(user):
    """
    获取用户的租户ID
    """
    if is_superuser(user):
        return None  # 超级管理员可以访问所有租户
    return getattr(user, 'tenant_id', 'admin')


def filter_by_tenant(queryset, user):
    """
    根据用户过滤QuerySet
    这是便捷方法,直接调用apply_tenant_filter
    """
    return apply_tenant_filter(queryset, user)


def get_all_tenant_users(tenant_id):
    """
    获取指定租户的所有用户
    """
    from apps.account.models import User
    return User.objects.filter(tenant_id=tenant_id, is_active=True)


def get_tenant_stats():
    """
    获取各租户的统计信息(仅超级管理员可用)
    """
    from apps.account.models import User
    from django.db.models import Count

    stats = User.objects.values('tenant_id').annotate(
        user_count=Count('id')
    ).order_by('tenant_id')

    return list(stats)


def check_tenant_unique_name(model, filter_kwargs, request_user, is_public=False):
    """
    检查当前租户内资源名称是否唯一

    Args:
        model: 模型类（DocumentFolder或DocumentFile）
        filter_kwargs: 基础过滤条件（如 folder_id、name）
        request_user: 当前请求用户
        is_public: 是否为公共空间

    Returns:
        tuple: (是否唯一, 匹配的资源QuerySet)
    """
    username = getattr(request_user, 'username', 'Unknown')

    queryset = model.objects.filter(**filter_kwargs)

    # 私有空间应用租户过滤
    if not is_public:
        queryset = apply_tenant_filter(queryset, request_user)

    # 使用 exists() 提升性能，仅判断是否存在无需统计数量
    is_unique = not queryset.exists()

    if not is_unique:
        logger.debug(
            f'[TENANT CHECK] {model.__name__} 名称重复检查: '
            f'user={username}, is_public={is_public}, '
            f'conditions={filter_kwargs}, 匹配数量={queryset.count()}'
        )

    return is_unique, queryset


def migrate_existing_data(tenant_id_map):
    """
    迁移现有数据到指定租户
    tenant_id_map: 字典, {'username': 'tenant_id'}
    用于初始化时给现有数据分配租户ID
    """
    from apps.account.models import User
    from apps.fault.models import FaultRecord, FaultPart
    from apps.duty.models import DutyRecord
    from apps.interference.models import Interference
    from apps.runlog.models import RunLog
    from apps.schedule.models import (
        ScheduleStaff, ScheduleShift, ScheduleShiftTime,
        Schedule, ScheduleSwap, ScheduleSubstitute
    )
    from apps.upgrade.models import UpgradeRecord

    # 为用户分配租户
    for username, tenant_id in tenant_id_map.items():
        User.objects.filter(username=username).update(tenant_id=tenant_id)
        logger.info(f'[TENANT MIGRATION] 用户 {username} 分配到租户 {tenant_id}')

    # 为现有数据分配租户(根据created_by的用户租户)
    models_to_migrate = [
        RunLog, FaultRecord, FaultPart, Interference, UpgradeRecord,
        DutyRecord, ScheduleStaff, ScheduleShift,
        ScheduleShiftTime, Schedule, ScheduleSwap, ScheduleSubstitute
    ]

    for model in models_to_migrate:
        # 获取所有没有tenant_id的记录（包括空字符串和NULL）
        from django.db.models import Q
        records = model.objects.filter(Q(tenant_id='') | Q(tenant_id__isnull=True)).select_related('created_by')

        for record in records:
            if record.created_by and hasattr(record.created_by, 'tenant_id'):
                record.tenant_id = record.created_by.tenant_id
                record.save()
                logger.info(f'[TENANT MIGRATION] {model.__name__} ID:{record.id} 分配到租户 {record.tenant_id}')

    logger.info('[TENANT MIGRATION] 数据迁移完成')
