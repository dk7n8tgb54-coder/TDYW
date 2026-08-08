"""跨租户 CRUD 测试

覆盖模块: home/navigation, home/notice, reminder, runlog, fault, account
覆盖操作: 列表查询、详情、修改、删除、租户字段伪造
"""
import json
from datetime import date
from django.test import Client

from factories.tenants import make_tenant_pair, cleanup_tenants
from factories.users import make_user_pair, cleanup_users
from factories.business_objects import make_all_business_objects, cleanup_business_objects, make_regulation_category, make_regulation
from helpers.api_assertions import get_body, get_items, assert_no_cross_tenant, assert_object_not_modified, assert_object_exists


def run(context):
    """执行所有 CRUD 跨租户测试

    Args:
        context: 共享上下文 dict，用于传递 setup_data

    Returns:
        list: 测试结果列表
    """
    results = []
    bootstrap = context['bootstrap_user']
    tenants = make_tenant_pair(bootstrap)
    users = make_user_pair(tenants, bootstrap)
    biz = make_all_business_objects(tenants, users)

    # 全局规章（用于 global_data_boundaries 测试）
    biz['reg_cat'] = make_regulation_category(bootstrap)
    biz['reg'] = make_regulation(biz['reg_cat'])

    tid_a = tenants['tid_a']
    tid_b = tenants['tid_b']
    tk_ua = users['tk_ua']
    tk_ub = users['tk_ub']
    ua = users['ua']
    ub = users['ub']

    try:
        _test_navigation(results, tk_ua, biz)
        _test_notice(results, tk_ua, biz)
        _test_reminder(results, tk_ua, tid_b, ua, biz)
        _test_runlog(results, tk_ua, biz)
        _test_fault(results, tk_ua, biz)
        _test_account(results, tk_ua, biz, ub)
    finally:
        cleanup_business_objects(biz, tid_a, tid_b)
        cleanup_users(users)
        cleanup_tenants(tid_a, tid_b)

    return results


def _rec(results, module, test, passed, detail='', sev='info'):
    results.append({'module': module, 'test': test, 'passed': passed,
                     'detail': detail, 'severity': sev})


# ==================== Navigation ====================

def _test_navigation(results, tk_ua, biz):
    """NavView 跨租户测试"""
    c = Client()

    # 列表
    r = c.get('/home/navigation/', **{'HTTP_X_TOKEN': tk_ua})
    items = get_items(get_body(r))
    passed, msg = assert_no_cross_tenant(items, 'NB_', 'title')
    _rec(results, 'home/navigation', 'Nav列表跨租户', passed, msg,
         'critical' if not passed else 'info')

    # 修改
    bid = biz['nav_b'].id
    c.post('/home/navigation/', data=json.dumps({'id': bid, 'title': 'HACKED'}),
           content_type='application/json', **{'HTTP_X_TOKEN': tk_ua})
    from apps.home.models import Navigation
    nav_b = Navigation.objects.get(pk=bid)
    passed, msg = assert_object_not_modified(nav_b, 'title', 'HACKED')
    _rec(results, 'home/navigation', 'Nav修改跨租户', passed, msg,
         'critical' if not passed else 'info')

    # 删除
    bid = biz['nav_b'].id
    c.delete(f'/home/navigation/?id={bid}', **{'HTTP_X_TOKEN': tk_ua})
    passed, msg = assert_object_exists(Navigation, bid)
    _rec(results, 'home/navigation', 'Nav删除跨租户', passed, msg,
         'critical' if not passed else 'info')
    if not passed:
        Navigation.objects.filter(pk=bid).update(is_deleted=False)


# ==================== Notice ====================

def _test_notice(results, tk_ua, biz):
    """NoticeView 跨租户测试"""
    c = Client()

    # 列表
    r = c.get('/home/notice/', **{'HTTP_X_TOKEN': tk_ua})
    items = get_items(get_body(r))
    passed, msg = assert_no_cross_tenant(items, 'PB_', 'title')
    _rec(results, 'home/notice', 'Notice列表跨租户', passed, msg,
         'critical' if not passed else 'info')

    # 修改
    bid = biz['notice_b'].id
    c.post('/home/notice/', data=json.dumps({'id': bid, 'title': 'HACKED'}),
           content_type='application/json', **{'HTTP_X_TOKEN': tk_ua})
    from apps.home.models import Notice
    notice_b = Notice.objects.get(pk=bid)
    passed, msg = assert_object_not_modified(notice_b, 'title', 'HACKED')
    _rec(results, 'home/notice', 'Notice修改跨租户', passed, msg,
         'critical' if not passed else 'info')

    # 删除
    bid = biz['notice_b'].id
    c.delete(f'/home/notice/?id={bid}', **{'HTTP_X_TOKEN': tk_ua})
    passed, msg = assert_object_exists(Notice, bid)
    _rec(results, 'home/notice', 'Notice删除跨租户', passed, msg,
         'critical' if not passed else 'info')
    if not passed:
        Notice.objects.filter(pk=bid).update(is_deleted=False)


# ==================== Reminder ====================

def _test_reminder(results, tk_ua, tid_b, ua, biz):
    """ReminderView 跨租户测试"""
    c = Client()

    # 列表
    r = c.get('/reminder/', **{'HTTP_X_TOKEN': tk_ua})
    items = get_items(get_body(r))
    passed, msg = assert_no_cross_tenant(items, 'RB_', 'name')
    _rec(results, 'reminder', 'Reminder列表跨租户', passed, msg,
         'high' if not passed else 'info')

    # 用户列表泄露
    r = c.get('/reminder/users/', **{'HTTP_X_TOKEN': tk_ua})
    users = get_items(get_body(r))
    found_b = any(u.get('id') == biz['rem_b'].created_by_id for u in users)
    _rec(results, 'reminder', 'ReminderUsers跨租户泄露',
         not found_b,
         f'看到B用户: {found_b}, 共 {len(users)} 用户',
         'high' if found_b else 'info')

    # 修改
    bid = biz['rem_b'].id
    ru = json.dumps([{'id': ua.id, 'nickname': ua.nickname}])
    c.post('/reminder/', data=json.dumps({
        'id': bid, 'name': 'HACKED', 'target_date': str(date.today()),
        'repeat_type': 'none', 'content': 'c', 'recipient_users': ru,
    }), content_type='application/json', **{'HTTP_X_TOKEN': tk_ua})
    from apps.reminder.models import Reminder
    rem_b = Reminder.objects.get(pk=bid)
    passed, msg = assert_object_not_modified(rem_b, 'name', 'HACKED')
    _rec(results, 'reminder', 'Reminder修改跨租户', passed, msg,
         'high' if not passed else 'info')

    # 删除
    bid = biz['rem_b'].id
    c.delete(f'/reminder/?id={bid}', **{'HTTP_X_TOKEN': tk_ua})
    passed, msg = assert_object_exists(Reminder, bid)
    _rec(results, 'reminder', 'Reminder删除跨租户', passed, msg,
         'high' if not passed else 'info')
    if not passed:
        Reminder.objects.filter(pk=bid).update(is_deleted=False)

    # 租户伪造
    r = c.post('/reminder/', data=json.dumps({
        'name': 'FORGE', 'target_date': str(date.today()),
        'repeat_type': 'none', 'content': 'c', 'recipient_users': ru,
        'tenant_id': tid_b,
    }), content_type='application/json', **{'HTTP_X_TOKEN': tk_ua})
    body = get_body(r)
    if body and not body.get('error') and body.get('id'):
        obj = Reminder.objects.get(pk=body['id'])
        forged = obj.tenant_id == tid_b
        _rec(results, 'reminder', 'Reminder租户伪造', not forged,
             f'伪造 tid_b, 实际={obj.tenant_id}',
             'critical' if forged else 'info')
        obj.delete()
    else:
        _rec(results, 'reminder', 'Reminder租户伪造', True, f'创建失败: {body}')


# ==================== RunLog ====================

def _test_runlog(results, tk_ua, biz):
    """RunLogView 跨租户测试"""
    c = Client()

    # 列表
    r = c.get('/runlog/', **{'HTTP_X_TOKEN': tk_ua})
    body = get_body(r)
    if isinstance(body, dict) and body.get('error'):
        _rec(results, 'runlog', 'RunLog列表跨租户', True, f'错误: {body}')
    else:
        items = get_items(body)
        passed, msg = assert_no_cross_tenant(items, 'LB_', 'event_title')
        _rec(results, 'runlog', 'RunLog列表跨租户', passed, msg,
             'high' if not passed else 'info')

    # 详情
    bid = biz['rl_b'].id
    r = c.get(f'/runlog/detail/?id={bid}', **{'HTTP_X_TOKEN': tk_ua})
    body = get_body(r)
    leaked = not body.get('error') and body.get('id') == bid
    _rec(results, 'runlog', 'RunLog详情跨租户', not leaked,
         f'resp={body}', 'high' if leaked else 'info')

    # 修改
    bid = biz['rl_b'].id
    c.post('/runlog/', data=json.dumps({'id': bid, 'event_title': 'HACKED'}),
           content_type='application/json', **{'HTTP_X_TOKEN': tk_ua})
    from apps.runlog.models import RunLog
    rl_b = RunLog.objects.get(pk=bid)
    passed, msg = assert_object_not_modified(rl_b, 'event_title', 'HACKED')
    _rec(results, 'runlog', 'RunLog修改跨租户', passed, msg,
         'high' if not passed else 'info')

    # 删除
    bid = biz['rl_b'].id
    c.delete(f'/runlog/?id={bid}', **{'HTTP_X_TOKEN': tk_ua})
    passed, msg = assert_object_exists(RunLog, bid)
    _rec(results, 'runlog', 'RunLog删除跨租户', passed, msg,
         'high' if not passed else 'info')
    if not passed:
        RunLog.objects.filter(pk=bid).update(is_deleted=False)


# ==================== Fault ====================

def _test_fault(results, tk_ua, biz):
    """FaultRecordView 跨租户测试"""
    c = Client()

    # 列表
    r = c.get('/fault/faultrecord/', **{'HTTP_X_TOKEN': tk_ua})
    body = get_body(r)
    if isinstance(body, dict) and body.get('error'):
        _rec(results, 'fault', 'Fault列表跨租户', True, f'错误: {body}')
    else:
        items = get_items(body)
        passed, msg = assert_no_cross_tenant(items, 'FB_', 'system_name')
        _rec(results, 'fault', 'Fault列表跨租户', passed, msg,
             'high' if not passed else 'info')

    # 修改
    bid = biz['ft_b'].id
    c.post('/fault/faultrecord/', data=json.dumps({'id': bid, 'system_name': 'HACKED'}),
           content_type='application/json', **{'HTTP_X_TOKEN': tk_ua})
    from apps.fault.models import FaultRecord
    ft_b = FaultRecord.objects.get(pk=bid)
    passed, msg = assert_object_not_modified(ft_b, 'system_name', 'HACKED')
    _rec(results, 'fault', 'Fault修改跨租户', passed, msg,
         'high' if not passed else 'info')

    # 删除
    bid = biz['ft_b'].id
    c.delete(f'/fault/faultrecord/?id={bid}', **{'HTTP_X_TOKEN': tk_ua})
    passed, msg = assert_object_exists(FaultRecord, bid)
    _rec(results, 'fault', 'Fault删除跨租户', passed, msg,
         'high' if not passed else 'info')
    if not passed:
        FaultRecord.objects.filter(pk=bid).update(is_deleted=False)


# ==================== Account ====================

def _test_account(results, tk_ua, biz, ub):
    """UserView 跨租户测试"""
    c = Client()

    # 列表
    r = c.get('/account/user/', **{'HTTP_X_TOKEN': tk_ua})
    body = get_body(r)
    if isinstance(body, dict) and body.get('error'):
        _rec(results, 'account', 'Account用户列表隔离', True, f'错误: {body}')
    else:
        items = get_items(body)
        found_b = any(u.get('id') == ub.id for u in items)
        _rec(results, 'account', 'Account用户列表跨租户',
             not found_b,
             f'看到B用户: {found_b}, 共 {len(items)} 用户',
             'critical' if found_b else 'info')

    # 修改
    bid = ub.id
    c.post('/account/user/', data=json.dumps({'id': bid, 'nickname': 'HACKED_USER'}),
           content_type='application/json', **{'HTTP_X_TOKEN': tk_ua})
    from apps.account.models import User
    ub.refresh_from_db()
    _rec(results, 'account', 'Account修改跨租户用户',
         ub.nickname != 'HACKED_USER',
         f'nickname={ub.nickname}',
         'critical' if ub.nickname == 'HACKED_USER' else 'info')

    # 删除
    bid = ub.id
    c.delete(f'/account/user/?id={bid}', **{'HTTP_X_TOKEN': tk_ua})
    ub.refresh_from_db()
    _rec(results, 'account', 'Account删除跨租户用户',
         ub.is_active,
         f'is_active={ub.is_active}',
         'critical' if not ub.is_active else 'info')
