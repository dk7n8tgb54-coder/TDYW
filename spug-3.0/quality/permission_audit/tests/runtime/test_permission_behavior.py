"""
运行时权限行为测试
在 Docker 环境中运行，验证权限校验的真实行为。

运行方式:
  docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
    python -m quality.permission_audit.tests.runtime.test_permission_behavior

或（如果 quality 目录不在 Python path 中）:
  docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
    python /data/spug/spug_api/../spug_web/../quality/permission_audit/tests/runtime/test_permission_behavior.py

注意：此测试会创建测试用户和角色，测试完成后自动清理。
"""
import os
import sys
import json
import secrets

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

from django.test import Client
from django.core.cache import cache
from django.db import transaction
from apps.account.models import User, Role


# ─── 测试辅助 ──────────────────────────────────────────

def make_test_user(username='perm_test_user', perms_json=None, tenant_id='test_tenant',
                   is_supper=False):
    """创建测试用户和角色"""
    token = secrets.token_hex(16)
    user = User.objects.create(
        username=username,
        nickname=username,
        password_hash=User.make_password('test123'),
        access_token=token,
        tenant_id=tenant_id,
        is_supper=is_supper,
    )
    if perms_json is None:
        perms_json = json.dumps({'system': {'account': ['view']}})

    role = Role.objects.create(
        name=f'test_role_{username}',
        page_perms=perms_json,
        perms_version=1,
        tenant_id=tenant_id,
    )
    user.roles.add(role)
    return user, role, token


def cleanup_test_user(user, role):
    """清理测试数据"""
    cache.delete(f'perms_{user.id}')
    try:
        user.delete()
    except Exception:
        pass
    try:
        role.delete()
    except Exception:
        pass


def make_client(token):
    """创建带认证 token 的测试客户端"""
    client = Client(HTTP_X_REAL_IP='127.0.0.1')
    client.defaults['HTTP_X_TOKEN'] = token
    return client


# ─── 权限行为测试 ─────────────────────────────────────

def test_no_permission_user_denied():
    """测试1：无权限用户被拒绝"""
    user, role, token = make_test_user(
        'perm_test_no_perm',
        perms_json=json.dumps({}),  # 空权限
    )
    try:
        client = make_client(token)
        resp = client.get('/api/account/user/')
        # AdminView.dispatch 应拒绝（PERM_MAP 检查失败）
        result = 'pass' if resp.status_code in (200,) and b'\xe6\x9d\x83\xe9\x99\x90\xe6\x8b\x92\xe7\xbb\x9d' in resp.content else 'fail'
        # 权限拒绝返回 HTTP 200 + error
        try:
            data = json.loads(resp.content)
            if data.get('error') == '权限拒绝':
                result = 'pass'
                msg = 'No-permission user correctly denied'
            else:
                result = 'fail'
                msg = f'Expected 权限拒绝, got: {data}'
        except:
            result = 'fail'
            msg = f'Cannot parse response: {resp.content[:200]}'
        return result, msg
    except Exception as e:
        return 'error', str(e)
    finally:
        cleanup_test_user(user, role)


def test_view_only_user_cannot_post():
    """测试2：只有 view 权限的用户不能 POST"""
    user, role, token = make_test_user(
        'perm_test_view_only',
        perms_json=json.dumps({'system': {'account': ['view']}}),
    )
    try:
        client = make_client(token)
        # GET 应该成功
        resp_get = client.get('/api/account/user/')
        # POST 应该被拒绝（需要 system.account.add）
        resp_post = client.post('/api/account/user/', data=json.dumps({
            'username': 'test_target',
            'password': 'pass123',
            'nickname': 'Test',
        }), content_type='application/json')

        try:
            get_data = json.loads(resp_get.content)
            post_data = json.loads(resp_post.content)
        except:
            return 'error', f'Cannot parse responses'

        if get_data.get('error') == '权限拒绝':
            return 'fail', f'GET should succeed for view-only user, but got 权限拒绝'

        if post_data.get('error') != '权限拒绝':
            return 'fail', f'POST should be denied for view-only user, got: {post_data}'

        return 'pass', 'View-only user can GET but cannot POST'
    except Exception as e:
        return 'error', str(e)
    finally:
        cleanup_test_user(user, role)


def test_add_user_cannot_delete():
    """测试3：有 add 权限的用户不能 DELETE"""
    user, role, token = make_test_user(
        'perm_test_add_only',
        perms_json=json.dumps({'system': {'account': ['view', 'add']}}),
    )
    try:
        client = make_client(token)
        resp = client.delete('/api/account/user/', data=json.dumps({'id': 99999}),
                             content_type='application/json')
        try:
            data = json.loads(resp.content)
        except:
            return 'error', f'Cannot parse response'

        if data.get('error') == '权限拒绝':
            return 'pass', 'Add-only user correctly denied DELETE'
        return 'fail', f'DELETE should be denied for add-only user, got: {data}'
    except Exception as e:
        return 'error', str(e)
    finally:
        cleanup_test_user(user, role)


def test_super_user_bypass():
    """测试4：超级管理员绕过权限检查"""
    user, role, token = make_test_user(
        'perm_test_super',
        is_supper=True,
    )
    try:
        client = make_client(token)
        resp = client.get('/api/account/user/')
        try:
            data = json.loads(resp.content)
        except:
            return 'error', f'Cannot parse response'

        if data.get('error') == '权限拒绝':
            return 'fail', 'Super user should bypass permission checks'
        return 'pass', 'Super user correctly bypasses permission checks'
    except Exception as e:
        return 'error', str(e)
    finally:
        cleanup_test_user(user, role)


def test_setting_view_super_only():
    """测试5：系统设置仅超管可访问"""
    # 普通用户
    user, role, token = make_test_user(
        'perm_test_setting_normal',
        perms_json=json.dumps({'system': {'setting': ['view']}}),
    )
    try:
        client = make_client(token)
        resp = client.get('/api/setting/')
        try:
            data = json.loads(resp.content)
        except:
            return 'error', f'Cannot parse response'

        # SettingView 继承 AdminView 但无 PERM_MAP -> dispatch 拒绝非超管
        if data.get('error') == '权限拒绝':
            return 'pass', 'Setting view correctly denies non-super user'
        return 'fail', f'Setting view should deny non-super user, got: {data}'
    except Exception as e:
        return 'error', str(e)
    finally:
        cleanup_test_user(user, role)


def test_permission_cache_invalidation():
    """测试6：权限缓存失效"""
    user, role, token = make_test_user(
        'perm_test_cache',
        perms_json=json.dumps({'system': {'account': ['view']}}),
    )
    try:
        # 首次读取建立缓存
        perms1 = user.page_perms
        assert 'system.account.view' in perms1
        cached1 = cache.get(f'perms_{user.id}')
        version1 = cached1[0]

        # 修改角色权限
        role.page_perms = json.dumps({'system': {'account': ['view', 'add']}})
        role.save()
        role.refresh_from_db()
        assert role.perms_version > version1

        # 重新读取
        user2 = User.objects.get(pk=user.id)
        perms2 = user2.page_perms
        assert 'system.account.add' in perms2

        cached2 = cache.get(f'perms_{user.id}')
        assert cached2[0] == role.perms_version

        return 'pass', 'Permission cache correctly invalidated after role change'
    except AssertionError as e:
        return 'fail', str(e)
    except Exception as e:
        return 'error', str(e)
    finally:
        cleanup_test_user(user, role)


def test_announcement_view_permission():
    """测试7：公告查看权限"""
    user, role, token = make_test_user(
        'perm_test_announcement',
        perms_json=json.dumps({'home': {'announcement': ['view']}}),
    )
    try:
        client = make_client(token)
        # GET 应该成功
        resp = client.get('/api/home/announcement/')
        try:
            data = json.loads(resp.content)
        except:
            return 'error', f'Cannot parse response'

        if data.get('error') == '权限拒绝':
            return 'fail', 'User with home.announcement.view should be able to GET /api/home/announcement/'

        # POST 应该被拒绝（需要 home.announcement.add|home.announcement.edit）
        resp_post = client.post('/api/home/announcement/', data=json.dumps({
            'title': 'test',
            'content': 'test',
        }), content_type='application/json')
        try:
            post_data = json.loads(resp_post.content)
        except:
            return 'error', f'Cannot parse POST response'

        if post_data.get('error') != '权限拒绝':
            return 'fail', f'POST should be denied for view-only user, got: {post_data}'

        return 'pass', 'Announcement view permission correctly enforced'
    except Exception as e:
        return 'error', str(e)
    finally:
        cleanup_test_user(user, role)


def test_multi_role_merge():
    """测试8：多角色权限合并"""
    user, role, token = make_test_user(
        'perm_test_multi_role',
        perms_json=json.dumps({'system': {'account': ['view']}}),
    )
    try:
        role2 = Role.objects.create(
            name=f'test_role_extra_{user.username}',
            page_perms=json.dumps({'home': {'navigation': ['view', 'add']}}),
            perms_version=1,
            tenant_id='test_tenant',
        )
        user.roles.add(role2)

        perms = user.page_perms
        assert 'system.account.view' in perms, f"Role 1 perm missing: {perms}"
        assert 'home.navigation.view' in perms, f"Role 2 perm missing: {perms}"
        assert 'home.navigation.add' in perms, f"Role 2 perm missing: {perms}"

        role2.delete()
        return 'pass', 'Multi-role permissions correctly merged'
    except AssertionError as e:
        return 'fail', str(e)
    except Exception as e:
        return 'error', str(e)
    finally:
        cleanup_test_user(user, role)


# ─── 主函数 ───────────────────────────────────────────

def run_all_tests():
    """运行所有测试"""
    tests = [
        ('no_perm_denied', '无权限用户被拒绝', test_no_permission_user_denied, 'high'),
        ('view_cannot_post', 'view权限用户不能POST', test_view_only_user_cannot_post, 'high'),
        ('add_cannot_delete', 'add权限用户不能DELETE', test_add_user_cannot_delete, 'high'),
        ('super_bypass', '超管绕过权限', test_super_user_bypass, 'low'),
        ('setting_super_only', '系统设置仅超管', test_setting_view_super_only, 'high'),
        ('cache_invalidation', '权限缓存失效', test_permission_cache_invalidation, 'high'),
        ('announcement_permission', '公告权限校验', test_announcement_view_permission, 'medium'),
        ('multi_role_merge', '多角色权限合并', test_multi_role_merge, 'medium'),
    ]

    results = []
    for test_id, desc, func, risk in tests:
        try:
            result, msg = func()
            results.append({
                'test_id': test_id,
                'description': desc,
                'result': result,
                'message': msg,
                'risk_level': risk,
            })
            status = 'PASS' if result == 'pass' else 'FAIL' if result == 'fail' else 'ERROR'
            print(f"[{status}] {test_id}: {msg}")
        except Exception as e:
            results.append({
                'test_id': test_id,
                'description': desc,
                'result': 'error',
                'message': str(e),
                'risk_level': risk,
            })
            print(f"[ERROR] {test_id}: {e}")

    # 输出 JSON
    print("\n=== JSON RESULTS ===")
    print(json.dumps(results, ensure_ascii=False, indent=2))

    # 输出 CSV
    print("\n=== CSV RESULTS ===")
    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['test_id', 'description', 'result', 'message', 'risk_level'])
    for r in results:
        writer.writerow([r['test_id'], r['description'], r['result'], r['message'], r['risk_level']])
    print(output.getvalue())

    # 统计
    passed = sum(1 for r in results if r['result'] == 'pass')
    failed = sum(1 for r in results if r['result'] == 'fail')
    errors = sum(1 for r in results if r['result'] == 'error')

    print(f"\n=== SUMMARY ===")
    print(f"Total: {len(results)}, Pass: {passed}, Fail: {failed}, Error: {errors}")

    return results


if __name__ == '__main__':
    run_all_tests()
