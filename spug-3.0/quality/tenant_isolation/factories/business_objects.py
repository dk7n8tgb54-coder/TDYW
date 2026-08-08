"""业务对象工厂 - 创建各模块的跨租户测试数据"""
import uuid
import json
from datetime import date

_uid = lambda: uuid.uuid4().hex[:12]


def make_navigation(tenant_id, label='A'):
    """创建导航记录"""
    from apps.home.models import Navigation
    return Navigation.objects.create(
        title=f'N{label}_{_uid()}', desc='测试导航', logo='logo',
        links=json.dumps([{'name': 'test', 'url': '/test'}]),
        tenant_id=tenant_id, sort_id=1,
    )


def make_notice(tenant_id, label='A'):
    """创建公告"""
    from apps.home.models import Notice
    return Notice.objects.create(
        title=f'P{label}_{_uid()}', content='测试公告内容',
        sort_id=1, tenant_id=tenant_id,
    )


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


def make_runlog(tenant_id, user, label='A'):
    """创建跨日事项"""
    from apps.runlog.models import RunLog
    return RunLog.objects.create(
        event_title=f'L{label}_{_uid()}', event_type='运行异常',
        system_name=f'S{label}', severity='P2', status='in_progress',
        created_by=user, tenant_id=tenant_id,
    )


def make_fault_record(tenant_id, user, label='A'):
    """创建故障记录"""
    from apps.fault.models import FaultRecord
    return FaultRecord.objects.create(
        system_name=f'F{label}_{_uid()}', device_code=f'D{label}',
        handler=user.nickname, recorder=user.nickname,
        fault_level='一般', fault_phenomenon='测试故障现象',
        handling_process='测试处理过程',
        created_by=user, tenant_id=tenant_id,
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
    # Navigation
    data['nav_a'] = make_navigation(tid_a, 'A')
    data['nav_b'] = make_navigation(tid_b, 'B')
    # Notice
    data['notice_a'] = make_notice(tid_a, 'A')
    data['notice_b'] = make_notice(tid_b, 'B')
    # Reminder
    data['rem_a'] = make_reminder(tid_a, ua, 'A')
    data['rem_b'] = make_reminder(tid_b, ub, 'B')
    # RunLog
    data['rl_a'] = make_runlog(tid_a, ua, 'A')
    data['rl_b'] = make_runlog(tid_b, ub, 'B')
    # Fault
    data['ft_a'] = make_fault_record(tid_a, ua, 'A')
    data['ft_b'] = make_fault_record(tid_b, ub, 'B')
    return data


def cleanup_business_objects(data, tid_a, tid_b):
    """清理所有业务对象"""
    from apps.home.models import Navigation, Notice
    from apps.reminder.models import Reminder
    from apps.runlog.models import RunLog
    from apps.fault.models import FaultRecord
    from apps.regulation.models import Regulation, RegulationCategory

    for model in [Navigation, Notice, Reminder, RunLog, FaultRecord]:
        model.objects.filter(tenant_id__in=[tid_a, tid_b]).delete()

    if 'reg' in data:
        Regulation.objects.filter(pk=data['reg'].pk).delete()
    if 'reg_cat' in data:
        RegulationCategory.objects.filter(pk=data['reg_cat'].pk).delete()
