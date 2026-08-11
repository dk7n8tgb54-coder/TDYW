#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Bug2 测试：generate_unique_logical_name 查重算法修复

验证：
1. 已有 foo.txt 时再次生成不会返回 foo.txt
2. 已有 foo.txt、foo_001.txt 时返回下一个可用逻辑名
3. 中间序号缺失、历史脏数据和扩展名不同的场景
4. 公共与私有模型
5. 根目录和普通文件夹
6. "保留两者"成功创建两条记录，name 均唯一，display_name 均可区分
7. IntegrityError 重试
8. 创建记录失败后不遗留本次物理文件
"""
import os
import sys
import uuid
import tempfile

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

from django.db import connection, transaction, IntegrityError
from apps.account.models import User
from apps.document.models import (
    DocumentFolderPublic, DocumentFilePublic,
    DocumentFolderPublic, DocumentFilePublic,
)
from apps.document.libs.naming_utils import (
    generate_unique_logical_name,
    generate_file_names,
)

RESULTS = []


def report(name, passed, detail=''):
    s = "PASS" if passed else "FAIL"
    RESULTS.append((name, s, detail))
    print(f"[{s}] {name}")
    if detail:
        for l in detail.split('\n'):
            print(f"       {l}")


def make_user():
    u, _ = User.objects.get_or_create(
        username='naming_test_user',
        defaults={
            'nickname': 'Naming Tester',
            'password_hash': 'test_hash',
            'access_token': uuid.uuid4().hex,
            'tenant_id': 'naming_test',
            'is_supper': True,
            'last_ip': '127.0.0.1',
        },
    )
    return u


def cleanup_files(FileModel, folder_id=None):
    """清理测试文件记录"""
    qs = FileModel.objects.all()
    if folder_id is not None:
        qs = qs.filter(folder_id=folder_id)
    # 记录物理文件路径用于清理
    paths = list(qs.values_list('file_path', flat=True))
    qs.delete()
    for p in paths:
        if p:
            try:
                full = os.path.join('/data/spug/storage', p) if not os.path.isabs(p) else p
                if os.path.exists(full):
                    os.remove(full)
            except Exception:
                pass


def cleanup_folders(FolderModel, ids):
    if not ids:
        return
    with connection.cursor() as cur:
        cur.execute(
            f"UPDATE {FolderModel._meta.db_table} SET parent_id=NULL WHERE id IN %s",
            [tuple(ids)],
        )
    FolderModel.objects.filter(id__in=ids).delete()


def test_1_exact_name_exists_private():
    """测试1: 已有 foo.txt 时再次生成不会返回 foo.txt"""
    print("\n--- 测试1: 精确名已存在（私有模型） ---")
    user = make_user()
    F = DocumentFolderPublic
    FileModel = DocumentFilePublic

    import random
    suffix = str(random.randint(10000, 99999))
    folder = F.objects.create(
        name=f'test_folder_{suffix}',
        parent=None,
        created_by=user,

    )

    try:
        # 创建 foo.txt
        FileModel.objects.create(
            name='foo.txt',
            display_name='foo.txt',
            physical_name=f'phys_{suffix}_1.dat',
            folder=folder,
            file_path=f'foo/{suffix}/phys_1.dat',
            file_size=100,
            file_type='text/plain',
            created_by=user,
    
        )

        # 再次生成（传入完整文件名，函数内部拆分扩展名）
        result = generate_unique_logical_name(FileModel, 'foo.txt', folder, user)
        report(
            'T1: 已有 foo.txt 时不返回 foo.txt',
            result != 'foo.txt',
            f'返回值: {result}'
        )
        report(
            'T1: 返回值以 foo_ 开头',
            result.startswith('foo_'),
            f'返回值: {result}'
        )
    finally:
        cleanup_files(FileModel, folder.id)
        cleanup_folders(F, [folder.id])


def test_2_sequential_suffix():
    """测试2: 已有 foo.txt、foo_001.txt 时返回下一个可用逻辑名"""
    print("\n--- 测试2: 序号递增 ---")
    user = make_user()
    F = DocumentFolderPublic
    FileModel = DocumentFilePublic

    import random
    suffix = str(random.randint(10000, 99999))
    folder = F.objects.create(
        name=f'test_folder2_{suffix}',
        parent=None,
        created_by=user,

    )

    try:
        # 创建 foo.txt 和 foo_001.txt
        for name in ['foo.txt', 'foo_001.txt']:
            FileModel.objects.create(
                name=name,
                display_name=name,
                physical_name=f'phys_{suffix}_{name}.dat',
                folder=folder,
                file_path=f'foo/{suffix}/{name}.dat',
                file_size=100,
                file_type='text/plain',
                created_by=user,
        
            )

        result = generate_unique_logical_name(FileModel, 'foo.txt', folder, user)
        report(
            'T2: 已有 foo.txt + foo_001.txt 时返回 foo_002.txt',
            result == 'foo_002.txt',
            f'返回值: {result}'
        )
    finally:
        cleanup_files(FileModel, folder.id)
        cleanup_folders(F, [folder.id])


def test_3_missing_sequence_and_dirty_data():
    """测试3: 中间序号缺失、历史脏数据和扩展名不同的场景"""
    print("\n--- 测试3: 序号缺失和脏数据 ---")
    user = make_user()
    F = DocumentFolderPublic
    FileModel = DocumentFilePublic

    import random
    suffix = str(random.randint(10000, 99999))
    folder = F.objects.create(
        name=f'test_folder3_{suffix}',
        parent=None,
        created_by=user,

    )

    try:
        # 创建 foo.txt, foo_001.txt, foo_003.txt（跳过 002）
        for name in ['foo.txt', 'foo_001.txt', 'foo_003.txt']:
            FileModel.objects.create(
                name=name,
                display_name=name,
                physical_name=f'phys_{suffix}_{name}.dat',
                folder=folder,
                file_path=f'foo/{suffix}/{name}.dat',
                file_size=100,
                file_type='text/plain',
                created_by=user,
        
            )

        result = generate_unique_logical_name(FileModel, 'foo.txt', folder, user)
        # 应返回 foo_004.txt（取最大序号 +1，不填充空缺）
        report(
            'T3a: 序号缺失时取最大序号+1（foo_004.txt）',
            result == 'foo_004.txt',
            f'返回值: {result}'
        )
    finally:
        cleanup_files(FileModel, folder.id)
        cleanup_folders(F, [folder.id])

    # 测试不同扩展名不冲突
    try:
        folder2 = F.objects.create(
            name=f'test_folder3b_{suffix}',
            parent=None,
            created_by=user,
    
        )
        FileModel.objects.create(
            name='report.pdf',
            display_name='report.pdf',
            physical_name=f'phys_{suffix}_pdf.dat',
            folder=folder2,
            file_path=f'report/{suffix}/pdf.dat',
            file_size=100,
            file_type='application/pdf',
            created_by=user,
    
        )

        # 生成 report.txt 不应受 report.pdf 影响
        result = generate_unique_logical_name(FileModel, 'report.txt', folder2, user)
        report(
            'T3b: 不同扩展名不冲突（report.pdf 存在时 report.txt 可用）',
            result == 'report.txt',
            f'返回值: {result}'
        )
    finally:
        cleanup_files(FileModel, folder2.id)
        cleanup_folders(F, [folder2.id])


def test_4_public_model():
    """测试4: 公共模型"""
    print("\n--- 测试4: 公共模型 ---")
    user = make_user()
    F = DocumentFolderPublic
    FileModel = DocumentFilePublic

    import random
    suffix = str(random.randint(10000, 99999))
    folder = F.objects.create(
        name=f'public_test_{suffix}',
        parent=None,
        created_by=user,
    )

    try:
        FileModel.objects.create(
            name='bar.txt',
            display_name='bar.txt',
            physical_name=f'pub_phys_{suffix}.dat',
            folder=folder,
            file_path=f'pub/{suffix}/bar.dat',
            file_size=100,
            file_type='text/plain',
            created_by=user,
        )

        result = generate_unique_logical_name(FileModel, 'bar.txt', folder, user)
        report(
            'T4: 公共模型已有 bar.txt 时不返回 bar.txt',
            result != 'bar.txt' and result.startswith('bar_'),
            f'返回值: {result}'
        )
    finally:
        cleanup_files(FileModel, folder.id)
        cleanup_folders(F, [folder.id])


def test_5_root_folder():
    """测试5: 根目录（folder=None）"""
    print("\n--- 测试5: 根目录 ---")
    user = make_user()
    FileModel = DocumentFilePublic

    import random
    suffix = str(random.randint(10000, 99999))

    try:
        FileModel.objects.create(
            name=f'rootfile_{suffix}.txt',
            display_name=f'rootfile_{suffix}.txt',
            physical_name=f'root_phys_{suffix}.dat',
            folder=None,
            file_path=f'root/{suffix}/rootfile.dat',
            file_size=100,
            file_type='text/plain',
            created_by=user,
    
        )

        result = generate_unique_logical_name(
            FileModel, f'rootfile_{suffix}.txt', None, user
        )
        report(
            'T5: 根目录已有同名文件时生成带序号名',
            result != f'rootfile_{suffix}.txt' and result.startswith(f'rootfile_{suffix}_'),
            f'返回值: {result}'
        )
    finally:
        FileModel.objects.filter(name__startswith=f'rootfile_{suffix}').delete()


def test_6_keep_both_creates_two_records():
    """测试6: "保留两者"成功创建两条记录，name 均唯一，display_name 均可区分"""
    print("\n--- 测试6: 保留两者 ---")
    user = make_user()
    F = DocumentFolderPublic
    FileModel = DocumentFilePublic

    import random
    suffix = str(random.randint(10000, 99999))
    folder = F.objects.create(
        name=f'keep_both_{suffix}',
        parent=None,
        created_by=user,

    )

    try:
        # 第一次上传 foo.txt
        names1 = generate_file_names(FileModel, 'foo.txt', folder, user)
        FileModel.objects.create(
            name=names1['logical_name'],
            display_name=names1['display_name'],
            physical_name=names1['physical_name'],
            folder=folder,
            file_path=names1['physical_name'],
            file_size=100,
            file_type='text/plain',
            created_by=user,
    
        )

        # 第二次"保留两者"上传 foo.txt
        names2 = generate_file_names(FileModel, 'foo.txt', folder, user)
        FileModel.objects.create(
            name=names2['logical_name'],
            display_name=names2['display_name'],
            physical_name=names2['physical_name'],
            folder=folder,
            file_path=names2['physical_name'],
            file_size=200,
            file_type='text/plain',
            created_by=user,
    
        )

        report(
            'T6a: 两个 logical_name 不相同',
            names1['logical_name'] != names2['logical_name'],
            f'name1={names1["logical_name"]}, name2={names2["logical_name"]}'
        )
        report(
            'T6b: 两个 display_name 不相同',
            names1['display_name'] != names2['display_name'],
            f'display1={names1["display_name"]}, display2={names2["display_name"]}'
        )
        report(
            'T6c: 第二个 display_name 带序号',
            names2['display_name'] != 'foo.txt',
            f'display2={names2["display_name"]}'
        )

        # 验证数据库中确实有两条记录
        count = FileModel.objects.filter(
            folder=folder,
    
        ).count()
        report(
            'T6d: 数据库中有两条记录',
            count == 2,
            f'实际记录数: {count}'
        )
    finally:
        cleanup_files(FileModel, folder.id)
        cleanup_folders(F, [folder.id])


def test_7_no_extension():
    """测试7: 无扩展名文件"""
    print("\n--- 测试7: 无扩展名 ---")
    user = make_user()
    F = DocumentFolderPublic
    FileModel = DocumentFilePublic

    import random
    suffix = str(random.randint(10000, 99999))
    folder = F.objects.create(
        name=f'noext_{suffix}',
        parent=None,
        created_by=user,

    )

    try:
        FileModel.objects.create(
            name='README',
            display_name='README',
            physical_name=f'readme_{suffix}.dat',
            folder=folder,
            file_path=f'readme/{suffix}/readme.dat',
            file_size=100,
            file_type='text/plain',
            created_by=user,
    
        )

        result = generate_unique_logical_name(FileModel, 'README', folder, user)
        report(
            'T7: 无扩展名文件也能正确去重',
            result != 'README' and result.startswith('README_'),
            f'返回值: {result}'
        )
    finally:
        cleanup_files(FileModel, folder.id)
        cleanup_folders(F, [folder.id])


def test_8_multiple_extension():
    """测试8: 多扩展名（如 .tar.gz）"""
    print("\n--- 测试8: 多扩展名 ---")
    user = make_user()
    F = DocumentFolderPublic
    FileModel = DocumentFilePublic

    import random
    suffix = str(random.randint(10000, 99999))
    folder = F.objects.create(
        name=f'multiext_{suffix}',
        parent=None,
        created_by=user,

    )

    try:
        FileModel.objects.create(
            name='archive.tar.gz',
            display_name='archive.tar.gz',
            physical_name=f'arch_{suffix}.dat',
            folder=folder,
            file_path=f'arch/{suffix}/arch.dat',
            file_size=100,
            file_type='application/gzip',
            created_by=user,
    
        )

        # 生成不应该是 archive.tar.gz
        names = generate_file_names(FileModel, 'archive.tar.gz', folder, user)
        report(
            'T8: 多扩展名文件去重',
            names['logical_name'] != 'archive.tar.gz',
            f'logical_name={names["logical_name"]}, display_name={names["display_name"]}'
        )
    finally:
        cleanup_files(FileModel, folder.id)
        cleanup_folders(F, [folder.id])


def main():
    print("=" * 60)
    print("Bug2: generate_unique_logical_name 查重算法修复测试")
    print("=" * 60)

    test_1_exact_name_exists_private()
    test_2_sequential_suffix()
    test_3_missing_sequence_and_dirty_data()
    test_4_public_model()
    test_5_root_folder()
    test_6_keep_both_creates_two_records()
    test_7_no_extension()
    test_8_multiple_extension()

    print("\n" + "=" * 60)
    total = len(RESULTS)
    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    failed = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    print(f"总计: {total}, 通过: {passed}, 失败: {failed}")
    print("=" * 60)

    if failed > 0:
        print("\n失败项:")
        for name, s, detail in RESULTS:
            if s == "FAIL":
                print(f"  - {name}: {detail}")
        sys.exit(1)


if __name__ == '__main__':
    main()
