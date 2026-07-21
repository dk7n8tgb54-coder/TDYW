# -*- coding: utf-8 -*-
"""跨模块集成测试 - 阶段 5

诚实测试，不绕过 bug。如果发现 bug 如实报告。

场景：
1. 多租户隔离（创建 + 列表 + 编辑 + 删除）
2. 权限缓存失效（改角色权限 → 用户权限变化）
3. 审计日志哈希链完整性
4. 登录 → 审计日志
5. 编辑部分字段更新（验证今天修的 bug 在集成场景下生效）
"""
import os
import sys
import json
import time
import tempfile

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

from django.test.utils import setup_test_environment, teardown_test_environment
from django.test.runner import DiscoverRunner
from django.test import Client

runner = DiscoverRunner(verbosity=0)
setup_test_environment()
old_config = runner.setup_databases()

results = []

def log(name, passed, detail=''):
    status = 'PASS' if passed else 'FAIL'
    results.append((name, passed, detail))
    print(f'  [{status}] {name}: {detail}')

try:
    from django.core.cache import cache
    from apps.account.models import User, Role, Tenant
    from apps.setting.utils import AppSetting
    from apps.logs.models import AuditLog
    from apps.interference.models import Interference

    cache.clear()
    AppSetting.set('bind_ip', False)
    AppSetting.get.cache_clear()

    def make_user(username, perms=None, is_supper=False, tenant_id='admin'):
        token = (username * 10)[:32]
        user = User.objects.create(
            username=username, nickname=username,
            password_hash='x', is_active=True, is_supper=is_supper,
            access_token=token, token_expired=int(time.time()) + 3600,
            last_login='2026-01-01', last_ip='127.0.0.1', type='default',
            tenant_id=tenant_id,
        )
        if not is_supper:
            user.set_perms_cache(set(perms or []), version=0)
        return user

    def make_client(user):
        c = Client()
        c.defaults['HTTP_X_TOKEN'] = user.access_token
        c.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
        return c

    INTERFERENCE_PERMS = [
        'interference.interference.view',
        'interference.interference.add',
        'interference.interference.edit',
        'interference.interference.del',
    ]

    VALID_DATA = {
        'frequency': '108.5 MHz',
        'report_dept': '技术部',
        'datetime': '2026-07-20 10:00:00',
        'coordinates': 'N39.9,E116.4',
        'interference_type': '信号干扰',
        'phenomenon': '测试现象',
        'is_reported': '否',
    }

    # ================================================================
    # 场景 1：多租户隔离
    # ================================================================
    print('\n===== 场景 1：多租户隔离 =====')
    cache.clear()

    supper = make_user('supper', is_supper=True)
    Tenant.objects.create(id='tenant-a', name='租户A', created_by=supper)
    Tenant.objects.create(id='tenant-b', name='租户B', created_by=supper)

    user_a = make_user('userAaaa', INTERFERENCE_PERMS, tenant_id='tenant-a')
    user_b = make_user('userBbbb', INTERFERENCE_PERMS, tenant_id='tenant-b')
    client_a = make_client(user_a)
    client_b = make_client(user_b)

    # 租户 A 创建记录
    resp = client_a.post('/interference/', data=VALID_DATA, content_type='application/json')
    log('租户A创建记录', not resp.json().get('error'), resp.json().get('error', '成功'))

    record_a = Interference.objects.filter(tenant_id='tenant-a').first()
    log('记录落库', record_a is not None, f'id={record_a.id if record_a else None}')

    # 租户 B 列表看不到 A 的数据
    resp_b = client_b.get('/interference/')
    b_total = resp_b.json()['data']['total']
    log('租户B列表看不到A的数据', b_total == 0, f'B看到{b_total}条')

    # 租户 B 尝试编辑 A 的记录
    resp_b_edit = client_b.post(
        '/interference/',
        data={'id': record_a.id, 'frequency': '999 MHz'},
        content_type='application/json',
    )
    log('租户B不能编辑A的记录', bool(resp_b_edit.json().get('error')),
        resp_b_edit.json().get('error', '编辑成功?!'))

    record_a.refresh_from_db()
    log('A的记录频率未被篡改', record_a.frequency == '108.5 MHz',
        f'frequency={record_a.frequency}')

    # 租户 B 尝试删除 A 的记录
    resp_b_del = client_b.delete(f'/interference/?id={record_a.id}')
    log('租户B不能删除A的记录', bool(resp_b_del.json().get('error')),
        resp_b_del.json().get('error', '删除成功?!'))

    log('A的记录仍存在', Interference.objects.filter(id=record_a.id).exists(), '')

    # ================================================================
    # 场景 2：权限缓存失效
    # ================================================================
    print('\n===== 场景 2：权限缓存失效 =====')
    cache.clear()
    AppSetting.get.cache_clear()

    # 创建角色（有 view 权限）
    role = Role.objects.create(
        name='集成测试角色', tenant_id='admin', created_by=supper,
        page_perms=json.dumps({
            'interference': {'interference': ['view', 'add', 'edit', 'del']}
        }),
    )

    # 创建用户绑定角色（不预设权限缓存，让 page_perms 自动重算）
    perm_user = make_user('permUser1', [], tenant_id='admin')
    perm_user.roles.add(role)
    perm_user.set_perms_cache()  # 清缓存，强制下次重算
    perm_client = make_client(perm_user)

    # 用户首次请求（page_perms 重算，缓存写入）
    resp1 = perm_client.get('/interference/')
    has_view_before = not resp1.json().get('error')
    log('用户初始有view权限', has_view_before,
        resp1.json().get('error', '成功'))

    # 超管修改角色权限（去掉 view）
    role.page_perms = json.dumps({
        'interference': {'interference': ['add', 'edit', 'del']}
    })
    role.save()  # save() 检测 page_perms 变化 → perms_version 自增

    # 用户再次请求（缓存 version 不匹配 → 重算 → 无 view 权限）
    resp2 = perm_client.get('/interference/')
    has_view_after = not resp2.json().get('error')
    log('修改权限后用户失去view权限', not has_view_after,
        resp2.json().get('error', '仍能访问?!'))

    # 超管恢复角色权限（加回 view）
    role.page_perms = json.dumps({
        'interference': {'interference': ['view', 'add', 'edit', 'del']}
    })
    role.save()

    # 用户第三次请求（缓存 version 不匹配 → 重算 → 有 view 权限）
    resp3 = perm_client.get('/interference/')
    has_view_restored = not resp3.json().get('error')
    log('恢复权限后用户重新获得view权限', has_view_restored,
        resp3.json().get('error', '无法恢复?!'))

    # ================================================================
    # 场景 3：审计日志哈希链完整性
    # ================================================================
    print('\n===== 场景 3：审计日志哈希链完整性 =====')

    # 收集所有审计日志
    all_logs = list(AuditLog.objects.all().order_by('id'))
    log('审计日志存在', len(all_logs) > 0, f'{len(all_logs)} 条')

    # 检查哈希链按租户分组连续（哈希链按租户隔离，不同租户独立成链）
    from collections import defaultdict
    tenant_logs = defaultdict(list)
    for l in all_logs:
        tenant_logs[l.tenant_id].append(l)

    chain_broken = []
    for tenant_id, logs in tenant_logs.items():
        prev_hash = ''
        for l in logs:
            if l.prev_hash != prev_hash:
                chain_broken.append((l.id, tenant_id, l.prev_hash, prev_hash))
            prev_hash = l.log_hash

    log('哈希链按租户连续', len(chain_broken) == 0,
        f'{len(chain_broken)} 处断裂' if chain_broken else
        f'{len(tenant_logs)} 个租户链全连续')

    if chain_broken:
        for log_id, tid, got, expected in chain_broken[:3]:
            print(f'    断裂: log_id={log_id}, tenant={tid}, prev_hash={got}, 期望={expected}')

    # 检查每条日志都有 log_hash 和 request_hash
    missing_hash = AuditLog.objects.filter(log_hash='').count()
    log('无空log_hash', missing_hash == 0, f'{missing_hash} 条空log_hash')

    # ================================================================
    # 场景 4：登录 → 审计日志
    # ================================================================
    print('\n===== 场景 4：登录 → 审计日志 =====')
    cache.clear()

    from apps.account.utils import verify_password
    # 创建真实密码用户
    login_user = User.objects.create(
        username='loginTest1',
        nickname='LoginTest',
        password_hash=User.make_password('Test1234!'),
        is_active=True,
        access_token=('loginTest1' * 10)[:32],
        token_expired=int(time.time()) + 3600,
        last_login='2026-01-01', last_ip='127.0.0.1', type='default',
        tenant_id='admin',
    )

    login_client = Client()
    login_client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
    login_client.defaults['HTTP_USER_AGENT'] = 'Mozilla/5.0 Test'

    login_resp = login_client.post(
        '/account/login/',
        data=json.dumps({'username': 'loginTest1', 'password': 'Test1234!'}),
        content_type='application/json',
    )
    login_body = login_resp.json()
    log('登录成功', not login_body.get('error'), login_body.get('error', '成功'))

    # 验证审计日志记录了登录
    login_audit = AuditLog.objects.filter(
        action='login', target_type='auth', is_success=True
    ).first()
    log('登录审计日志记录', login_audit is not None,
        f'username={login_audit.username if login_audit else None}')

    # 登出
    auth_client = make_client(login_user)
    # 登录后 token 已刷新，需要用新 token
    login_user.refresh_from_db()
    auth_client.defaults['HTTP_X_TOKEN'] = login_user.access_token
    logout_resp = auth_client.post(
        '/account/logout/', data='{}', content_type='application/json')
    log('登出成功', not logout_resp.json().get('error'),
        logout_resp.json().get('error', '成功'))

    logout_audit = AuditLog.objects.filter(
        action='logout', target_type='auth'
    ).first()
    log('登出审计日志记录', logout_audit is not None, '')

    # 验证登出后 token 失效
    login_user.refresh_from_db()
    log('登出后token_expired=0', login_user.token_expired == 0,
        f'token_expired={login_user.token_expired}')

    # ================================================================
    # 场景 5：编辑部分字段更新（验证 bug 修复在集成场景下生效）
    # ================================================================
    print('\n===== 场景 5：编辑部分字段更新（跨模块验证） =====')
    cache.clear()

    editor = make_user('editor001', INTERFERENCE_PERMS, tenant_id='admin')
    editor_client = make_client(editor)

    # 创建记录
    resp = editor_client.post(
        '/interference/', data=VALID_DATA, content_type='application/json')
    log('创建记录', not resp.json().get('error'), resp.json().get('error', '成功'))

    record = Interference.objects.filter(tenant_id='admin').first()

    # 编辑：只传 id + frequency
    resp = editor_client.post(
        '/interference/',
        data={'id': record.id, 'frequency': '200 MHz'},
        content_type='application/json',
    )
    log('部分字段编辑成功', not resp.json().get('error'),
        resp.json().get('error', '成功'))

    record.refresh_from_db()
    log('frequency已更新', record.frequency == '200 MHz',
        f'frequency={record.frequency}')
    log('report_dept未被覆盖', record.report_dept == '技术部',
        f'report_dept={record.report_dept}')
    log('interference_type未被覆盖', record.interference_type == '信号干扰',
        f'interference_type={record.interference_type}')
    log('phenomenon未被覆盖', record.phenomenon == '测试现象',
        f'phenomenon={record.phenomenon}')

    # ================================================================
    # 汇总
    # ================================================================
    print('\n===== 汇总 =====')
    passed = sum(1 for _, p, _ in results if p)
    failed = sum(1 for _, p, _ in results if not p)
    total = len(results)
    print(f'  PASS: {passed}/{total}, FAIL: {failed}/{total}')

    if failed > 0:
        print('\n  失败项:')
        for name, p, detail in results:
            if not p:
                print(f'    ✗ {name}: {detail}')
    else:
        print('\n  全部通过 ✓')

    sys.exit(1 if failed > 0 else 0)

except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(2)
finally:
    runner.teardown_databases(old_config)
    teardown_test_environment()
