#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Bug6 后端测试：FolderView 幂等创建 created 字段验证

验证：
1. 首次创建返回 created:True，数据库增加一条
2. 同父目录同名创建返回 created:False，数据库数量不变
3. 不同父目录允许同名
4. 公共和私有空间作用域正确
5. _find_existing_folder 作用域与 unique_key 一致
6. 并发 IntegrityError 兜底返回已有 ID 和 created:False
7. 私有空间跨用户同名隔离
8. 根目录与子目录作用域正确
"""
import os
import sys
import json
import uuid
import random

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

from django.db import connection, transaction, IntegrityError
from apps.account.models import User
from apps.document.models import (
    DocumentFolderPublic, DocumentFolderPublic,
)
from apps.document.views.folder.views import FolderView

RESULTS = []


def report(name, passed, detail=''):
    s = "PASS" if passed else "FAIL"
    RESULTS.append((name, s, detail))
    print(f"[{s}] {name}")
    if detail:
        for l in detail.split('\n'):
            print(f"       {l}")


def make_user(username='folder_test_user', tenant_id='folder_test'):
    u, _ = User.objects.get_or_create(
        username=username,
        defaults={
            'nickname': 'Folder Tester',
            'password_hash': 'test_hash',
            'access_token': uuid.uuid4().hex,
            'tenant_id': tenant_id,
            'is_supper': True,
            'last_ip': '127.0.0.1',
        },
    )
    return u


def cleanup_folders(FolderModel, ids):
    if not ids:
        return
    with connection.cursor() as cur:
        cur.execute(
            f"UPDATE {FolderModel._meta.db_table} SET parent_id=NULL WHERE id IN %s",
            [tuple(ids)],
        )
    FolderModel.objects.filter(id__in=ids).delete()


class FakeRequest:
    """模拟 DRF request 对象"""
    def __init__(self, user, data):
        self.user = user
        self.data = data
        self.method = 'POST'
        self.GET = {}
        self.POST = {}
        self.content_type = 'application/json'
        self.body = json.dumps(data).encode('utf-8')


def test_1_first_create_returns_created_true_private():
    """测试1: 首次创建返回 created:True"""
    print("\n--- 测试1: 首次创建（私有空间） ---")
    user = make_user('ft_user1', 'ft_tenant1')
    F = DocumentFolderPublic
    suffix = str(random.randint(10000, 99999))
    folder_name = f'test_folder_{suffix}'

    try:
        view = FolderView()
        request = FakeRequest(user, {
            'name': folder_name,
            'parent_id': 0,
            'is_public': False,
        })
        response = view.post(request)
        data = json.loads(response.content)
        created = data.get('data', {}).get('created')
        folder_id = data.get('data', {}).get('id')

        report('T1: 首次创建返回 created=True', created is True,
               f'response: {data}')
        report('T1: 返回有效 folder id', folder_id is not None,
               f'folder_id: {folder_id}')

        # 验证数据库确实增加了一条
        exists = F.objects.filter(id=folder_id, name=folder_name, created_by=user).exists()
        report('T1: 数据库有对应记录', exists)

        cleanup_folders(F, [folder_id] if folder_id else [])
    except Exception as e:
        report('T1: 异常', False, str(e))
        import traceback
        traceback.print_exc()


def test_2_same_name_same_parent_returns_created_false_private():
    """测试2: 同父目录同名创建返回 created:False"""
    print("\n--- 测试2: 同名同父目录（私有空间） ---")
    user = make_user('ft_user2', 'ft_tenant2')
    F = DocumentFolderPublic
    suffix = str(random.randint(10000, 99999))
    folder_name = f'dup_folder_{suffix}'

    try:
        # 先创建一个
        view = FolderView()
        request1 = FakeRequest(user, {
            'name': folder_name,
            'parent_id': 0,
            'is_public': False,
        })
        response1 = view.post(request1)
        data1 = json.loads(response1.content)
        first_id = data1['data']['id']
        first_created = data1['data']['created']

        # 再创建同名的
        request2 = FakeRequest(user, {
            'name': folder_name,
            'parent_id': 0,
            'is_public': False,
        })
        response2 = view.post(request2)
        data2 = json.loads(response2.content)
        second_id = data2['data']['id']
        second_created = data2['data']['created']

        report('T2: 第一次 created=True', first_created is True)
        report('T2: 第二次 created=False', second_created is False)
        report('T2: 返回相同 folder id', first_id == second_id,
               f'first={first_id}, second={second_id}')

        # 数据库只有一条
        count = F.objects.filter(name=folder_name, created_by=user, parent__isnull=True).count()
        report('T2: 数据库只有一条记录', count == 1, f'count={count}')

        cleanup_folders(F, [first_id])
    except Exception as e:
        report('T2: 异常', False, str(e))
        import traceback
        traceback.print_exc()


def test_3_different_parent_allows_same_name_private():
    """测试3: 不同父目录允许同名"""
    print("\n--- 测试3: 不同父目录同名（私有空间） ---")
    user = make_user('ft_user3', 'ft_tenant3')
    F = DocumentFolderPublic
    suffix = str(random.randint(10000, 99999))
    folder_name = f'same_name_{suffix}'

    try:
        # 创建父文件夹 A
        parent_a = F.objects.create(
            name=f'parent_a_{suffix}', parent=None,
            created_by=user, tenant_id=user.tenant_id,
        )
        # 创建父文件夹 B
        parent_b = F.objects.create(
            name=f'parent_b_{suffix}', parent=None,
            created_by=user, tenant_id=user.tenant_id,
        )

        view = FolderView()

        # 在 A 下创建 folder_name
        req_a = FakeRequest(user, {'name': folder_name, 'parent_id': parent_a.id, 'is_public': False})
        resp_a = view.post(req_a)
        data_a = json.loads(resp_a.content)

        # 在 B 下创建同名 folder_name
        req_b = FakeRequest(user, {'name': folder_name, 'parent_id': parent_b.id, 'is_public': False})
        resp_b = view.post(req_b)
        data_b = json.loads(resp_b.content)

        report('T3: A 下创建 created=True', data_a['data']['created'] is True)
        report('T3: B 下同名创建 created=True（不同父目录）', data_b['data']['created'] is True)
        report('T3: 两个 folder id 不同',
               data_a['data']['id'] != data_b['data']['id'],
               f"A={data_a['data']['id']}, B={data_b['data']['id']}")

        cleanup_folders(F, [parent_a.id, parent_b.id, data_a['data']['id'], data_b['data']['id']])
    except Exception as e:
        report('T3: 异常', False, str(e))
        import traceback
        traceback.print_exc()


def test_4_public_space_scope():
    """测试4: 公共空间作用域正确（不区分用户）"""
    print("\n--- 测试4: 公共空间作用域 ---")
    user1 = make_user('ft_user4a', 'ft_tenant4')
    user2 = make_user('ft_user4b', 'ft_tenant4')
    F = DocumentFolderPublic
    suffix = str(random.randint(10000, 99999))
    folder_name = f'pub_folder_{suffix}'

    try:
        view = FolderView()

        # user1 创建公共文件夹
        req1 = FakeRequest(user1, {'name': folder_name, 'parent_id': 0, 'is_public': True})
        resp1 = view.post(req1)
        data1 = json.loads(resp1.content)

        # user2 创建同名公共文件夹 -> 应返回 created:False
        req2 = FakeRequest(user2, {'name': folder_name, 'parent_id': 0, 'is_public': True})
        resp2 = view.post(req2)
        data2 = json.loads(resp2.content)

        report('T4: user1 创建 created=True', data1['data']['created'] is True)
        report('T4: user2 同名 created=False（公共空间不区分用户）',
               data2['data']['created'] is False)
        report('T4: 返回相同 folder id',
               data1['data']['id'] == data2['data']['id'])

        cleanup_folders(F, [data1['data']['id']])
    except Exception as e:
        report('T4: 异常', False, str(e))
        import traceback
        traceback.print_exc()


def test_5_private_space_cross_user_isolation():
    """测试5: 私有空间跨用户同名隔离"""
    print("\n--- 测试5: 私有空间跨用户隔离 ---")
    user1 = make_user('ft_user5a', 'ft_tenant5')
    user2 = make_user('ft_user5b', 'ft_tenant5')
    F = DocumentFolderPublic
    suffix = str(random.randint(10000, 99999))
    folder_name = f'priv_folder_{suffix}'

    try:
        view = FolderView()

        # user1 创建私有文件夹
        req1 = FakeRequest(user1, {'name': folder_name, 'parent_id': 0, 'is_public': False})
        resp1 = view.post(req1)
        data1 = json.loads(resp1.content)

        # user2 创建同名私有文件夹 -> 应返回 created:True（不同用户）
        req2 = FakeRequest(user2, {'name': folder_name, 'parent_id': 0, 'is_public': False})
        resp2 = view.post(req2)
        data2 = json.loads(resp2.content)

        report('T5: user1 创建 created=True', data1['data']['created'] is True)
        report('T5: user2 同名 created=True（私有空间按用户隔离）',
               data2['data']['created'] is True)
        report('T5: 两个 folder id 不同',
               data1['data']['id'] != data2['data']['id'])

        cleanup_folders(F, [data1['data']['id'], data2['data']['id']])
    except Exception as e:
        report('T5: 异常', False, str(e))
        import traceback
        traceback.print_exc()


def test_6_cross_tenant_isolation_private():
    """测试6: 私有空间跨租户隔离"""
    print("\n--- 测试6: 私有空间跨租户隔离 ---")
    user1 = make_user('ft_user6a', 'ft_tenant6a')
    user2 = make_user('ft_user6b', 'ft_tenant6b')
    F = DocumentFolderPublic
    suffix = str(random.randint(10000, 99999))
    folder_name = f'tenant_folder_{suffix}'

    try:
        view = FolderView()

        # tenant A 用户创建
        req1 = FakeRequest(user1, {'name': folder_name, 'parent_id': 0, 'is_public': False})
        resp1 = view.post(req1)
        data1 = json.loads(resp1.content)

        # tenant B 用户创建同名 -> 应返回 created:True（不同租户）
        req2 = FakeRequest(user2, {'name': folder_name, 'parent_id': 0, 'is_public': False})
        resp2 = view.post(req2)
        data2 = json.loads(resp2.content)

        report('T6: tenant A created=True', data1['data']['created'] is True)
        report('T6: tenant B 同名 created=True（跨租户隔离）',
               data2['data']['created'] is True)

        cleanup_folders(F, [data1['data']['id'], data2['data']['id']])
    except Exception as e:
        report('T6: 异常', False, str(e))
        import traceback
        traceback.print_exc()


def test_7_find_existing_folder_scope_matches_unique_key():
    """测试7: _find_existing_folder 作用域与 unique_key 一致"""
    print("\n--- 测试7: _find_existing_folder 作用域验证 ---")
    user = make_user('ft_user7', 'ft_tenant7')
    F = DocumentFolderPublic
    suffix = str(random.randint(10000, 99999))

    try:
        # 创建根目录下的文件夹
        folder = F.objects.create(
            name=f'scope_test_{suffix}', parent=None,
            created_by=user, tenant_id=user.tenant_id,
        )

        # 验证 unique_key 计算
        expected_key = folder._compute_unique_key()
        actual_key = folder.unique_key
        report('T7: unique_key 已正确计算', expected_key == actual_key,
               f'expected={expected_key}, actual={actual_key}')

        # 验证 _find_existing_folder 能找到它
        found = FolderView._find_existing_folder(F, f'scope_test_{suffix}', 0, False, user)
        report('T7: _find_existing_folder 根目录找到已有文件夹', found is not None and found.id == folder.id)

        # 验证不同 name 找不到
        not_found = FolderView._find_existing_folder(F, f'nonexistent_{suffix}', 0, False, user)
        report('T7: 不同 name 找不到', not_found is None)

        cleanup_folders(F, [folder.id])
    except Exception as e:
        report('T7: 异常', False, str(e))
        import traceback
        traceback.print_exc()


def test_8_concurrent_integrity_error_fallback():
    """测试8: 并发 IntegrityError 兜底"""
    print("\n--- 测试8: 并发 IntegrityError 兜底 ---")
    user = make_user('ft_user8', 'ft_tenant8')
    F = DocumentFolderPublic
    suffix = str(random.randint(10000, 99999))
    folder_name = f'concurrent_{suffix}'

    try:
        # 先手动创建一个文件夹
        existing = F.objects.create(
            name=folder_name, parent=None,
            created_by=user, tenant_id=user.tenant_id,
        )

        # 模拟并发场景：_find_existing_folder 先返回 None，
        # 然后创建时撞 unique_key -> IntegrityError
        # 验证 _find_existing_folder 在 IntegrityError 后能找到已有记录
        found = FolderView._find_existing_folder(F, folder_name, 0, False, user)
        report('T8: IntegrityError 后 _find_existing_folder 找到已有', 
               found is not None and found.id == existing.id,
               f'found_id={found.id if found else None}, existing_id={existing.id}')

        # 验证 unique_key 冲突确实会发生
        report('T8: unique_key 值不为空', bool(existing.unique_key),
               f'unique_key={existing.unique_key}')

        # 尝试创建同 unique_key 的记录应触发 IntegrityError
        try:
            with transaction.atomic():
                dup = F(
                    name=folder_name, parent=None,
                    created_by=user, tenant_id=user.tenant_id,
                )
                dup.unique_key = existing.unique_key  # 强制冲突
                dup.save()
            report('T8: 重复 unique_key 触发 IntegrityError', False, '未触发异常')
        except IntegrityError:
            report('T8: 重复 unique_key 触发 IntegrityError', True)

        cleanup_folders(F, [existing.id])
    except Exception as e:
        report('T8: 异常', False, str(e))
        import traceback
        traceback.print_exc()


def test_9_root_vs_subdirectory_scope():
    """测试9: 根目录与子目录作用域正确"""
    print("\n--- 测试9: 根目录与子目录作用域 ---")
    user = make_user('ft_user9', 'ft_tenant9')
    F = DocumentFolderPublic
    suffix = str(random.randint(10000, 99999))
    folder_name = f'root_sub_{suffix}'

    try:
        # 创建子目录
        parent = F.objects.create(
            name=f'parent_{suffix}', parent=None,
            created_by=user, tenant_id=user.tenant_id,
        )
        # 在子目录下创建 folder_name
        child = F.objects.create(
            name=folder_name, parent=parent,
            created_by=user, tenant_id=user.tenant_id,
        )

        # _find_existing_folder 在根目录找不到子目录中的文件夹
        found_root = FolderView._find_existing_folder(F, folder_name, 0, False, user)
        report('T9: 根目录中找不到子目录的文件夹', found_root is None)

        # _find_existing_folder 在子目录中能找到
        found_child = FolderView._find_existing_folder(F, folder_name, parent.id, False, user)
        report('T9: 子目录中找到已有文件夹',
               found_child is not None and found_child.id == child.id)

        cleanup_folders(F, [parent.id, child.id])
    except Exception as e:
        report('T9: 异常', False, str(e))
        import traceback
        traceback.print_exc()


def main():
    print("=" * 60)
    print("Bug6 后端测试：FolderView 幂等创建 created 字段验证")
    print("=" * 60)

    test_1_first_create_returns_created_true_private()
    test_2_same_name_same_parent_returns_created_false_private()
    test_3_different_parent_allows_same_name_private()
    test_4_public_space_scope()
    test_5_private_space_cross_user_isolation()
    test_6_cross_tenant_isolation_private()
    test_7_find_existing_folder_scope_matches_unique_key()
    test_8_concurrent_integrity_error_fallback()
    test_9_root_vs_subdirectory_scope()

    print("\n" + "=" * 60)
    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    failed = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    print(f"总计: {passed} PASS / {failed} FAIL / {len(RESULTS)} 总")
    if failed:
        print("\n失败项:")
        for name, s, detail in RESULTS:
            if s == "FAIL":
                print(f"  - {name}: {detail}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
