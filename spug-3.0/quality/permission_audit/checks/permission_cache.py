"""
权限缓存行为测试
生成运行时测试脚本，在 Docker 环境中执行。
"""
from dataclasses import dataclass


@dataclass
class CacheTestResult:
    test_name: str
    description: str
    expected: str
    actual: str
    result: str  # pass, fail, skip
    risk_level: str
    notes: str


class PermissionCacheCheck:
    """生成权限缓存行为测试描述"""

    def __init__(self):
        self.test_cases = [
            {
                'name': 'cache_first_read',
                'description': '首次读取权限建立缓存，后续读取命中缓存',
                'expected': '首次读取后 perms_{user_id} 在 Redis 中存在，第二次读取命中缓存',
                'risk_level': 'low',
            },
            {
                'name': 'cache_version_invalidation',
                'description': 'RolePolicy 修改后 perms_version 自增，缓存自动失效',
                'expected': '修改 Role.page_perms 并 save 后，perms_version 自增，用户下次读取权限时缓存失效并重算',
                'risk_level': 'high',
            },
            {
                'name': 'cache_role_change',
                'description': '用户角色变化后缓存是否更新',
                'expected': '用户添加/删除角色后，_get_roles_perms_version 返回值变化，缓存自动失效',
                'risk_level': 'high',
            },
            {
                'name': 'cache_multi_role_merge',
                'description': '多角色权限合并',
                'expected': '用户拥有多个角色时，page_perms 是所有角色权限的并集',
                'risk_level': 'medium',
            },
            {
                'name': 'cache_ttl_expiry',
                'description': '缓存 TTL 过期后重新计算',
                'expected': 'PERMS_CACHE_TTL=300 秒后缓存自动过期，下次读取重新计算',
                'risk_level': 'low',
            },
            {
                'name': 'cache_format_migration',
                'description': '旧格式缓存（set 实例）被识别为失效',
                'expected': '如果缓存中是旧格式（非 tuple），page_perms 属性会重新计算',
                'risk_level': 'medium',
            },
        ]

    def get_test_cases(self) -> list[dict]:
        """返回测试用例列表"""
        return self.test_cases

    def generate_runtime_test_script(self) -> str:
        """生成运行时测试脚本内容"""
        return '''
"""
权限缓存行为测试 - 在 Docker 环境中运行
"""
import os
import sys
import json
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

from django.core.cache import cache
from django.db import transaction
from apps.account.models import User, Role

def make_test_user(username='perm_test_user', tenant_id='test_tenant'):
    """创建测试用户和角色"""
    import secrets
    token = secrets.token_hex(16)
    user = User.objects.create(
        username=username,
        nickname=username,
        password_hash=User.make_password('test123'),
        access_token=token,
        tenant_id=tenant_id,
    )
    role = Role.objects.create(
        name=f'test_role_{username}',
        page_perms=json.dumps({'system': {'account': ['view']}}),
        perms_version=1,
        tenant_id=tenant_id,
    )
    user.roles.add(role)
    return user, role

def cleanup_test_user(user, role):
    """清理测试数据"""
    cache.delete(f'perms_{user.id}')
    user.delete()
    role.delete()

def test_cache_first_read():
    """测试1：首次读取权限建立缓存"""
    user, role = make_test_user('cache_test_1')
    try:
        # 清除缓存
        cache.delete(f'perms_{user.id}')
        # 首次读取
        perms = user.page_perms
        assert 'system.account.view' in perms, f"Expected system.account.view in {perms}"
        # 验证缓存已建立
        cached = cache.get(f'perms_{user.id}')
        assert cached is not None, "Cache should be populated after first read"
        assert isinstance(cached, tuple), f"Cache should be tuple, got {type(cached)}"
        assert cached[0] == 1, f"Version should be 1, got {cached[0]}"
        assert 'system.account.view' in cached[1]
        return 'pass', 'Cache correctly populated on first read'
    except AssertionError as e:
        return 'fail', str(e)
    finally:
        cleanup_test_user(user, role)

def test_cache_version_invalidation():
    """测试2：Role 修改后缓存版本失效"""
    user, role = make_test_user('cache_test_2')
    try:
        # 首次读取建立缓存
        perms1 = user.page_perms
        assert 'system.account.view' in perms1
        cached1 = cache.get(f'perms_{user.id}')
        version1 = cached1[0]
        
        # 修改角色权限
        role.page_perms = json.dumps({
            'system': {'account': ['view', 'add']}
        })
        role.save()
        # perms_version should auto-increment
        role.refresh_from_db()
        assert role.perms_version > version1, f"Version should increase: {version1} -> {role.perms_version}"
        
        # 重新读取 - 应该自动失效重算
        user2 = User.objects.get(pk=user.id)
        perms2 = user2.page_perms
        assert 'system.account.add' in perms2, f"New permission should be visible: {perms2}"
        
        cached2 = cache.get(f'perms_{user.id}')
        assert cached2[0] == role.perms_version, f"Cache version should match: {cached2[0]} vs {role.perms_version}"
        return 'pass', 'Cache correctly invalidated after role permission change'
    except AssertionError as e:
        return 'fail', str(e)
    finally:
        cleanup_test_user(user, role)

def test_cache_role_change():
    """测试3：用户角色变化后缓存更新"""
    user, role = make_test_user('cache_test_3')
    try:
        # 首次读取
        perms1 = user.page_perms
        assert 'system.account.view' in perms1
        
        # 创建新角色并添加
        import json as json_mod
        role2 = Role.objects.create(
            name=f'test_role_extra_{user.username}',
            page_perms=json_mod.dumps({'home': {'notice': ['view']}}),
            perms_version=1,
            tenant_id='test_tenant',
        )
        user.roles.add(role2)
        
        # 重新读取 - 版本应该变化
        user2 = User.objects.get(pk=user.id)
        perms2 = user2.page_perms
        assert 'home.notice.view' in perms2, f"New role permission should be visible: {perms2}"
        assert 'system.account.view' in perms2, f"Original permission should still be present"
        
        # 删除角色
        user2.roles.remove(role2)
        user3 = User.objects.get(pk=user.id)
        perms3 = user3.page_perms
        assert 'home.notice.view' not in perms3, f"Removed role permission should not be present: {perms3}"
        
        role2.delete()
        return 'pass', 'Cache correctly updated on role add/remove'
    except AssertionError as e:
        return 'fail', str(e)
    finally:
        cleanup_test_user(user, role)

def test_multi_role_merge():
    """测试4：多角色权限合并"""
    user, role = make_test_user('cache_test_4')
    try:
        import json as json_mod
        role2 = Role.objects.create(
            name=f'test_role_merge_{user.username}',
            page_perms=json_mod.dumps({'document': {'document': ['view', 'add']}}),
            perms_version=1,
            tenant_id='test_tenant',
        )
        user.roles.add(role2)
        
        perms = user.page_perms
        assert 'system.account.view' in perms, f"Role 1 permission missing"
        assert 'document.document.view' in perms, f"Role 2 permission missing"
        assert 'document.document.add' in perms, f"Role 2 permission missing"
        
        role2.delete()
        return 'pass', 'Multi-role permissions correctly merged'
    except AssertionError as e:
        return 'fail', str(e)
    finally:
        cleanup_test_user(user, role)

def test_cache_old_format_invalidation():
    """测试5：旧格式缓存被识别为失效"""
    user, role = make_test_user('cache_test_5')
    try:
        # 写入旧格式缓存（set 实例，非 tuple）
        cache.set(f'perms_{user.id}', {'system.account.view'}, 300)
        
        # 读取应该重算
        perms = user.page_perms
        cached = cache.get(f'perms_{user.id}')
        assert isinstance(cached, tuple), f"Cache should be updated to tuple format, got {type(cached)}"
        assert 'system.account.view' in perms
        return 'pass', 'Old format cache correctly invalidated'
    except AssertionError as e:
        return 'fail', str(e)
    finally:
        cleanup_test_user(user, role)

if __name__ == '__main__':
    tests = [
        ('cache_first_read', test_cache_first_read),
        ('cache_version_invalidation', test_cache_version_invalidation),
        ('cache_role_change', test_cache_role_change),
        ('multi_role_merge', test_multi_role_merge),
        ('cache_old_format_invalidation', test_cache_old_format_invalidation),
    ]
    results = []
    for name, func in tests:
        try:
            result, msg = func()
            results.append((name, result, msg))
            print(f"{'PASS' if result == 'pass' else 'FAIL'}: {name} - {msg}")
        except Exception as e:
            results.append((name, 'error', str(e)))
            print(f"ERROR: {name} - {e}")
    
    # 输出 JSON
    print("\\n=== JSON ===")
    print(json.dumps([
        {'test': n, 'result': r, 'message': m} for n, r, m in results
    ], ensure_ascii=False, indent=2))
'''
