"""业务对象工厂 - 创建各模块的跨租户测试数据"""
import uuid
import json
from datetime import date

_uid = lambda: uuid.uuid4().hex[:12]


def make_reminder(tenant_id, user, label='A'):
    """创建提醒"""
    from apps.reminder.models import Reminder
    recipients = json.dumps([{'id': user.id, 'nickname': user.nickname}])
    return Reminder.objects.create(
        name=f'R{label}_{_uid()}', target_date=date.today(),
        repeat_type='none', content='测试提醒', enabled=True,
        recipient_users=recipients,
        tenant_id=tenant_id,
        created_by_id=user.id, created_by_name=user.nickname,
    )


def make_regulation_category(bootstrap_user):
    """创建规章分类（全局，无租户字段）"""
    from apps.regulation.models import RegulationCategory
    return RegulationCategory.objects.create(
        name=f'RC_{_uid()}', created_by=bootstrap_user,
    )


def make_regulation(category):
    """创建规章（全局，无租户字段）"""
    from apps.regulation.models import Regulation
    return Regulation.objects.create(
        title=f'RG_{_uid()}', rule_no=f'NO_{_uid()}', category=category,
    )


def make_all_business_objects(tenants, users):
    """创建租户 A/B 的全套业务对象

    Args:
        tenants: make_tenant_pair() 的返回值
        users: make_user_pair() 的返回值

    Returns:
        dict: 所有业务对象的引用
    """
    tid_a = tenants['tid_a']
    tid_b = tenants['tid_b']
    ua = users['ua']
    ub = users['ub']

    data = {}
    # Reminder
    data['rem_a'] = make_reminder(tid_a, ua, 'A')
    data['rem_b'] = make_reminder(tid_b, ub, 'B')
    return data


def cleanup_business_objects(data, tid_a, tid_b):
    """清理所有业务对象"""
    from apps.reminder.models import Reminder
    from apps.regulation.models import Regulation, RegulationCategory

    Reminder.objects.filter(tenant_id__in=[tid_a, tid_b]).delete()

    if 'reg' in data:
        Regulation.objects.filter(pk=data['reg'].pk).delete()
    if 'reg_cat' in data:
        RegulationCategory.objects.filter(pk=data['reg_cat'].pk).delete()
