#!/usr/bin/env python
"""
WP5 租户隔离修复 - 定向行为测试

测试三个发现：
1. NavView 已删除确认 (REMEDIATED_BY_REMOVAL)
2. NoticeView 已删除确认 (NOT_APPLICABLE)
3. ReminderUsersView 跨租户隔离

运行方式（Docker 内）:
  python run_wp5_tests.py
"""
import json
import uuid
import time
import traceback
from datetime import date
from django.test import Client
from django.conf import settings

# 允许测试 Client 的默认 host
if 'testserver' not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ['testserver', '*']

# Monkey-patch Client to always set REMOTE_ADDR
_orig_request = Client.request
def _patched_request(self, **request):
    request.setdefault('HTTP_X_REAL_IP', '127.0.0.1')
    return _orig_request(self, **request)
Client.request = _patched_request

RESULTS = []


def rec(test_id, passed, detail='', sev='info'):
    RESULTS.append({
        'test_id': test_id,
        'passed': passed,
        'detail': detail,
        'severity': sev
    })
    status = 'PASS' if passed else 'FAIL'
    print(f"  [{status}] {test_id}: {detail}")


def _uid():
    return uuid.uuid4().hex[:12]


def _body(resp):
    try:
        return resp.json()
    except Exception:
        return {'raw': resp.content[:300].decode('utf-8', 'ignore')}


def _items(body):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        if body.get('error'):
            return []
        return body.get('data', body.get('items', []))
    return []


def setup_data():
    """创建两个租户、两个用户、各自的数据"""
    from apps.account.models import User, Role, Tenant
    from apps.reminder.models import Reminder

    bootstrap_user = User.objects.first()
    d = {}
    d['tid_a'] = f'wp5_a_{_uid()}'
    d['tid_b'] = f'wp5_b_{_uid()}'
    d['tenant_a'] = Tenant.objects.create(
        id=d['tid_a'], name='WP5测试A', created_by=bootstrap_user
    )
    d['tenant_b'] = Tenant.objects.create(
        id=d['tid_b'], name='WP5测试B', created_by=bootstrap_user
    )

    perms = json.dumps({
        "home": {
            "announcement": ["view", "add", "edit", "del"],
            "reminder": ["view", "add", "edit", "delete"]
        },
        "reminder": {
            "reminder": ["view", "add", "edit", "delete"]
        }
    })

    for lbl, tid, uname in [
        ('ua', d['tid_a'], f'wp5_a_{_uid()}'),
        ('ub', d['tid_b'], f'wp5_b_{_uid()}'),
    ]:
        r = Role.objects.create(
            name=f'r_{uname}', tenant_id=tid,
            page_perms=perms, created_by=bootstrap_user
        )
        u = User(
            username=uname, nickname=f'昵称_{uname}',
            password_hash=User.make_password('t'),
            tenant_id=tid, is_supper=False, is_active=True,
            access_token=uuid.uuid4().hex,
            last_ip='127.0.0.1',
            token_expired=time.time() + 86400,
            type='default',
        )
        u.save()
        u.roles.add(r)
        d[lbl] = u
        d[f'tk_{lbl}'] = u.access_token

    # 创建超管用户
    super_name = f'wp5_sup_{_uid()}'
    d['sup'] = User(
        username=super_name, nickname=f'超管_{super_name}',
        password_hash=User.make_password('t'),
        is_supper=True, is_active=True,
        access_token=uuid.uuid4().hex,
        last_ip='127.0.0.1',
        token_expired=time.time() + 86400,
        type='default',
    )
    d['sup'].save()
    d['tk_sup'] = d['sup'].access_token

    # Reminder 数据
    d['rem_a'] = Reminder.objects.create(
        name=f'RA_{_uid()}', target_date=date.today(),
        repeat_type='none', content='c', enabled=True,
        recipient_users='[]', tenant_id=d['tid_a'],
        created_by_id=d['ua'].id, created_by_name=d['ua'].nickname
    )
    d['rem_b'] = Reminder.objects.create(
        name=f'RB_{_uid()}', target_date=date.today(),
        repeat_type='none', content='c', enabled=True,
        recipient_users='[]', tenant_id=d['tid_b'],
        created_by_id=d['ub'].id, created_by_name=d['ub'].nickname
    )

    return d


def cleanup(d):
    from apps.account.models import User, Role, Tenant
    from apps.reminder.models import Reminder

    Reminder.objects.filter(
        tenant_id__in=[d['tid_a'], d['tid_b']]
    ).delete()
    for key in ['ua', 'ub', 'sup']:
        if key in d:
            u = d[key]
            u.roles.clear()
            u.delete()
    Role.objects.filter(
        tenant_id__in=[d['tid_a'], d['tid_b']]
    ).delete()
    Tenant.objects.filter(
        id__in=[d['tid_a'], d['tid_b']]
    ).delete()


# ============================================================
# Finding 1: NavView 已删除确认 (REMEDIATED_BY_REMOVAL)
# ============================================================

def test_nav_view_removed(d):
    """NAV-01: NavView 路由不可达 (404)"""
    c = Client()
    r = c.get('/home/navigation/', **{'HTTP_X_TOKEN': d['tk_ua']})
    is_404 = r.status_code == 404
    rec('NAV-01', is_404,
        f'status={r.status_code}(应为404)',
        sev='critical' if not is_404 else 'info')


def test_nav_model_removed(d):
    """NAV-02: Navigation 模型已从 models.py 中移除"""
    try:
        from apps.home.models import Navigation
        rec('NAV-02', False, 'Navigation 模型仍然存在',
            sev='high')
    except ImportError:
        rec('NAV-02', True, 'Navigation 模型已移除')


def test_nav_module_removed(d):
    """NAV-03: navigation.py 模块已删除"""
    import importlib
    try:
        importlib.import_module('apps.home.navigation')
        rec('NAV-03', False, 'apps.home.navigation 模块仍然存在',
            sev='high')
    except ImportError:
        rec('NAV-03', True, 'apps.home.navigation 模块已删除')


def test_nav_url_removed(d):
    """NAV-04: urls.py 中无 navigation 路由"""
    from apps.home import urls
    has_nav = any('navigation' in str(p.pattern) for p in urls.urlpatterns)
    rec('NAV-04', not has_nav,
        f'urls.py 中 navigation 路由:{"仍存在" if has_nav else "已移除"}',
        sev='high' if has_nav else 'info')


# ============================================================
# Finding 2: NoticeView 已删除确认 (NOT_APPLICABLE)
# ============================================================

def test_notice_view_removed(d):
    """NOTICE-01: NoticeView 路由不可达"""
    c = Client()
    r = c.get('/home/notice/', **{'HTTP_X_TOKEN': d['tk_ua']})
    is_404 = r.status_code == 404
    rec('NOTICE-01', is_404,
        f'status={r.status_code}(应为404)',
        sev='critical' if not is_404 else 'info')


def test_notice_model_removed(d):
    """NOTICE-02: Notice 模型已从 models.py 中移除"""
    try:
        from apps.home.models import Notice
        rec('NOTICE-02', False, 'Notice 模型仍然存在',
            sev='high')
    except ImportError:
        rec('NOTICE-02', True, 'Notice 模型已移除')


def test_notice_import_removed(d):
    """NOTICE-03: notice.py 模块已删除"""
    import importlib
    try:
        importlib.import_module('apps.home.notice')
        rec('NOTICE-03', False, 'apps.home.notice 模块仍然存在',
            sev='high')
    except ImportError:
        rec('NOTICE-03', True, 'apps.home.notice 模块已删除')


def test_announcement_replaces_notice(d):
    """NOTICE-04: Announcement 模型存在且替代了 Notice"""
    try:
        from apps.home.models import Announcement
        rec('NOTICE-04', True, 'Announcement 模型存在')
    except ImportError:
        rec('NOTICE-04', False, 'Announcement 模型不存在',
            sev='high')


# ============================================================
# Finding 3: ReminderUsersView 租户隔离测试
# ============================================================

def test_remusers_list_success(d):
    """REMUSERS-01: 本租户用户列表访问成功"""
    c = Client()
    r = c.get('/reminder/users/', **{'HTTP_X_TOKEN': d['tk_ua']})
    b = _body(r)
    users = _items(b)
    has_self = any(u.get('id') == d['ua'].id for u in users)
    rec('REMUSERS-01', has_self,
        f'看到自己:{has_self},共{len(users)}用户')


def test_remusers_no_cross_tenant(d):
    """REMUSERS-02: 列表不包含其他租户用户"""
    c = Client()
    r = c.get('/reminder/users/', **{'HTTP_X_TOKEN': d['tk_ua']})
    b = _body(r)
    users = _items(b)
    found_b = any(u.get('id') == d['ub'].id for u in users)
    rec('REMUSERS-02', not found_b,
        f'看到B租户用户:{found_b},共{len(users)}用户',
        sev='critical' if found_b else 'info')


def test_remusers_no_cross_username(d):
    """REMUSERS-03: 响应体不包含其他租户用户的 username"""
    c = Client()
    r = c.get('/reminder/users/', **{'HTTP_X_TOKEN': d['tk_ua']})
    b = _body(r)
    users = _items(b)
    b_username = d['ub'].username
    found_username = any(u.get('username') == b_username for u in users)
    rec('REMUSERS-03', not found_username,
        f'泄露B用户名:{found_username}',
        sev='critical' if found_username else 'info')


def test_remusers_no_cross_nickname(d):
    """REMUSERS-04: 响应体不包含其他租户用户的 nickname"""
    c = Client()
    r = c.get('/reminder/users/', **{'HTTP_X_TOKEN': d['tk_ua']})
    b = _body(r)
    users = _items(b)
    b_nickname = d['ub'].nickname
    found_nickname = any(u.get('nickname') == b_nickname for u in users)
    rec('REMUSERS-04', not found_nickname,
        f'泄露B昵称:{found_nickname}',
        sev='critical' if found_nickname else 'info')


def test_remusers_no_tenant_id_field(d):
    """REMUSERS-05: 响应体不包含 tenant_id 字段"""
    c = Client()
    r = c.get('/reminder/users/', **{'HTTP_X_TOKEN': d['tk_ua']})
    b = _body(r)
    users = _items(b)
    has_tenant_id = any('tenant_id' in u for u in users)
    rec('REMUSERS-05', not has_tenant_id,
        f'响应含tenant_id字段:{has_tenant_id}',
        sev='high' if has_tenant_id else 'info')


def test_remusers_supercan_see_all(d):
    """REMUSERS-06: 超级管理员可以看到所有租户用户"""
    c = Client()
    r = c.get('/reminder/users/', **{'HTTP_X_TOKEN': d['tk_sup']})
    b = _body(r)
    users = _items(b)
    has_a = any(u.get('id') == d['ua'].id for u in users)
    has_b = any(u.get('id') == d['ub'].id for u in users)
    rec('REMUSERS-06', has_a and has_b,
        f'超管看到A:{has_a},B:{has_b},共{len(users)}用户')


def test_remusers_no_permission(d):
    """REMUSERS-07: 无权限用户不能通过直接请求绕过权限"""
    from apps.account.models import User, Role
    bootstrap = User.objects.first()
    no_perm_name = f'wp5_noperm_{_uid()}'
    no_perm_role = Role.objects.create(
        name=f'r_{no_perm_name}', tenant_id=d['tid_a'],
        page_perms=json.dumps({"home": {"announcement": ["view"]}}),
        created_by=bootstrap
    )
    no_perm_user = User(
        username=no_perm_name, nickname=no_perm_name,
        password_hash=User.make_password('t'),
        tenant_id=d['tid_a'], is_supper=False, is_active=True,
        access_token=uuid.uuid4().hex,
        last_ip='127.0.0.1',
        token_expired=time.time() + 86400,
        type='default',
    )
    no_perm_user.save()
    no_perm_user.roles.add(no_perm_role)

    c = Client()
    r = c.get('/reminder/users/', **{'HTTP_X_TOKEN': no_perm_user.access_token})
    b = _body(r)
    denied = bool(b.get('error'))
    rec('REMUSERS-07', denied,
        f'无权限访问被拒:{denied}, resp={b}',
        sev='high' if not denied else 'info')

    no_perm_user.roles.clear()
    no_perm_user.delete()
    no_perm_role.delete()


# ============================================================
# 补充：Reminder 本租户 CRUD 回归
# ============================================================

def test_rem_list_self_tenant(d):
    """REM-01: 本租户 Reminder 列表访问成功"""
    c = Client()
    r = c.get('/reminder/', **{'HTTP_X_TOKEN': d['tk_ua']})
    b = _body(r)
    items = _items(b)
    has_a = any('RA_' in str(i.get('name', '')) for i in items)
    rec('REM-01', has_a, f'看到本租户数据:{has_a},共{len(items)}条')


def test_rem_list_no_cross_tenant(d):
    """REM-02: Reminder 列表不包含其他租户数据"""
    c = Client()
    r = c.get('/reminder/', **{'HTTP_X_TOKEN': d['tk_ua']})
    b = _body(r)
    items = _items(b)
    has_b = any('RB_' in str(i.get('name', '')) for i in items)
    rec('REM-02', not has_b, f'看到B租户数据:{has_b}',
        sev='high' if has_b else 'info')


def test_rem_cross_edit_blocked(d):
    """REM-03: 跨租户更新 Reminder 失败"""
    from apps.reminder.models import Reminder
    bid = d['rem_b'].id
    original_name = d['rem_b'].name
    c = Client()
    r = c.put(
        '/reminder/',
        data=json.dumps({'id': bid, 'name': 'HACKED'}),
        content_type='application/json',
        **{'HTTP_X_TOKEN': d['tk_ua']}
    )
    n = Reminder.objects.get(pk=bid)
    unchanged = n.name == original_name
    rec('REM-03', unchanged,
        f'name={n.name}, resp={_body(r)}',
        sev='high' if not unchanged else 'info')


def test_rem_cross_delete_blocked(d):
    """REM-04: 跨租户删除 Reminder 失败"""
    from apps.reminder.models import Reminder
    bid = d['rem_b'].id
    c = Client()
    r = c.delete(
        f'/reminder/{bid}/',
        **{'HTTP_X_TOKEN': d['tk_ua']}
    )
    n = Reminder.objects.filter(pk=bid, is_deleted=False).first()
    still_exists = n is not None
    rec('REM-04', still_exists,
        f'记录仍存在:{still_exists}, resp={_body(r)}',
        sev='high' if not still_exists else 'info')


def test_rem_create_tenant_forgery(d):
    """REM-05: 创建 Reminder 时不能伪造 tenant_id"""
    from apps.reminder.models import Reminder
    c = Client()
    name = f'FORGE_{_uid()}'
    r = c.post(
        '/reminder/',
        data=json.dumps({
            'name': name, 'target_date': str(date.today()),
            'repeat_type': 'none', 'content': 'c',
            'recipient_users': json.dumps([{'id': d['ua'].id, 'nickname': d['ua'].nickname}]),
            'tenant_id': d['tid_b']
        }),
        content_type='application/json',
        **{'HTTP_X_TOKEN': d['tk_ua']}
    )
    b = _body(r)
    created = Reminder.objects.filter(name=name).first()
    if created:
        correct = created.tenant_id == d['tid_a']
        rec('REM-05', correct,
            f'tenant_id={created.tenant_id}(应为{d["tid_a"]})',
            sev='critical' if not correct else 'info')
        created.delete()
    else:
        rec('REM-05', False, f'创建失败: {b}', sev='error')


# ============================================================
# 主函数
# ============================================================

ALL_TESTS = [
    # NavView (REMEDIATED_BY_REMOVAL)
    test_nav_view_removed,
    test_nav_model_removed,
    test_nav_module_removed,
    test_nav_url_removed,
    # NoticeView (NOT_APPLICABLE)
    test_notice_view_removed,
    test_notice_model_removed,
    test_notice_import_removed,
    test_announcement_replaces_notice,
    # ReminderUsersView
    test_remusers_list_success,
    test_remusers_no_cross_tenant,
    test_remusers_no_cross_username,
    test_remusers_no_cross_nickname,
    test_remusers_no_tenant_id_field,
    test_remusers_supercan_see_all,
    test_remusers_no_permission,
    # Reminder regression
    test_rem_list_self_tenant,
    test_rem_list_no_cross_tenant,
    test_rem_cross_edit_blocked,
    test_rem_cross_delete_blocked,
    test_rem_create_tenant_forgery,
]


def main():
    print('=' * 70)
    print('  WP5 租户隔离修复 - 定向行为测试')
    print('  发现 1: NavView 已删除确认 (REMEDIATED_BY_REMOVAL)')
    print('  发现 2: NoticeView 已删除确认 (NOT_APPLICABLE)')
    print('  发现 3: ReminderUsersView 跨租户隔离')
    print('=' * 70)

    d = setup_data()
    try:
        for t in ALL_TESTS:
            try:
                t(d)
            except Exception as e:
                rec(t.__name__, False, f'异常: {e}', 'error')
                traceback.print_exc()
    finally:
        cleanup(d)

    print('\n' + '=' * 70)
    print('  测试汇总')
    print('=' * 70)
    passed = sum(1 for r in RESULTS if r['passed'])
    failed = sum(1 for r in RESULTS if not r['passed'])
    print(f'  总计: {len(RESULTS)} | 通过: {passed} | 失败: {failed}')
    if failed:
        print('\n  失败项:')
        for r in RESULTS:
            if not r['passed']:
                print(f"    [{r['severity'].upper()}] {r['test_id']}: {r['detail']}")

    print('\n__RESULTS_JSON__')
    print(json.dumps(RESULTS, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
