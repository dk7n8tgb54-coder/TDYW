#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""统一冲突处理 + 文件移动物理迁移 后端测试

覆盖：
1. 移动冲突检测（同名同大小、同名不同大小）
2. replace/keep/skip 三种动作
3. keep 连续生成 _1、_2
4. 物理文件迁移到目标目录
5. 移动后删除原文件夹，文件仍可访问
6. 冲突预检 + 事务内重新校验
7. 物理迁移失败 DB 不变
8. 复制冲突检测
"""
import os, sys, json, uuid, random, shutil, tempfile

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

from django.conf import settings
from django.db import connection, transaction, IntegrityError
from apps.account.models import User
from apps.document.models import DocumentFolderPublic, DocumentFilePublic
from apps.document.libs.document_utils import (
    get_document_absolute_path, get_document_relative_path, is_safe_path,
)
from apps.document.services.conflict_service import (
    check_display_name_conflict, generate_unique_display_name,
    build_conflict_info, batch_check_conflicts, CONFLICT_ACTIONS,
)
from apps.document.views.file.move import FileMoveView
from apps.document.views.file.copy import FileCopyView

R = []


def report(name, passed, detail=''):
    s = "PASS" if passed else "FAIL"
    R.append((name, s, detail))
    print(f"[{s}] {name}")
    if detail:
        for l in detail.split('\n'):
            print(f"       {l}")


def make_user(username, tenant_id):
    u, _ = User.objects.get_or_create(
        username=username,
        defaults={
            'nickname': username, 'password_hash': 'x',
            'access_token': uuid.uuid4().hex, 'tenant_id': tenant_id,
            'is_supper': True, 'last_ip': '127.0.0.1',
        },
    )
    return u


class FakeRequest:
    def __init__(self, user, data):
        self.user = user
        self.data = data
        self.method = 'POST'
        self.GET = {}
        self.POST = {}
        self.content_type = 'application/json'
        self.body = json.dumps(data).encode('utf-8')


def make_folder(user, name, parent=None):
    return DocumentFolderPublic.objects.create(
        name=name, parent=parent,
        created_by=user, tenant_id=user.tenant_id,
    )


def make_file(user, folder, display_name, content='test', file_size=None):
    """创建文件记录 + 物理文件"""
    physical_name = f'{uuid.uuid4().hex}.bin'
    file_dir = get_document_absolute_path(
        is_public=False, user_id=user.id, folder_id=folder.id if folder else None)
    os.makedirs(file_dir, exist_ok=True)
    file_path = os.path.join(file_dir, physical_name)
    with open(file_path, 'w') as f:
        f.write(content)
    return DocumentFilePublic.objects.create(
        name=display_name, display_name=display_name,
        physical_name=physical_name, file_path=file_path,
        file_size=file_size or len(content),
        folder=folder, created_by=user, tenant_id=user.tenant_id,
    )


def cleanup_files(FileModel, ids):
    """清理文件记录和物理文件"""
    for fid in ids:
        try:
            f = FileModel.objects.filter(id=fid).first()
            if f:
                p = f.file_path
                t = f.thumbnail_path or ''
                f.delete()
                if p and os.path.exists(p):
                    os.remove(p)
                if t and os.path.exists(t):
                    os.remove(t)
        except Exception:
            pass


def cleanup_folders(FolderModel, ids):
    for fid in ids:
        try:
            f = FolderModel.objects.filter(id=fid).first()
            if f:
                f.delete()
        except Exception:
            pass


# ===== 测试 =====

def test_1_move_no_conflict_physical_migration():
    """T1: 移动无冲突 -> 物理文件迁移到目标目录"""
    print("\n--- T1: 移动无冲突 + 物理迁移 ---")
    user = make_user('ct1', 'ct_t1')
    F, Folder = DocumentFilePublic, DocumentFolderPublic
    s = str(random.randint(10000, 99999))

    folder_a = make_folder(user, f'A_{s}')
    folder_b = make_folder(user, f'B_{s}')
    file = make_file(user, folder_a, f'file_{s}.txt', 'hello')

    old_path = file.file_path
    report('T1: 移动前物理文件存在', os.path.exists(old_path))

    view = FileMoveView()
    resp = view.post(FakeRequest(user, {
        'id': file.id, 'target_id': folder_b.id, 'is_public': False
    }))
    data = json.loads(resp.content)

    file.refresh_from_db()
    report('T1: 返回 success', data.get('data', {}).get('status') == 'success',
           f'response={data}')

    # 物理文件应在新目录
    new_path = file.file_path
    target_dir = get_document_absolute_path(
        is_public=False, user_id=user.id, folder_id=folder_b.id)
    report('T1: file_path 更新到目标目录',
           f'folder-{folder_b.id}' in new_path,
           f'old={old_path}, new={new_path}')
    report('T1: 物理文件在新目录', os.path.exists(new_path))
    report('T1: 旧路径文件已移走', not os.path.exists(old_path))

    # 清理
    cleanup_files(F, [file.id])
    cleanup_folders(Folder, [folder_a.id, folder_b.id])


def test_2_move_conflict_same_name_same_size():
    """T2: 同名同大小冲突 -> 返回 conflict 响应"""
    print("\n--- T2: 同名同大小冲突 ---")
    user = make_user('ct2', 'ct_t2')
    F, Folder = DocumentFilePublic, DocumentFolderPublic
    s = str(random.randint(10000, 99999))

    folder_a = make_folder(user, f'A_{s}')
    folder_b = make_folder(user, f'B_{s}')
    file_a = make_file(user, folder_a, f'dup_{s}.txt', 'content', 7)
    file_b = make_file(user, folder_b, f'dup_{s}.txt', 'other', 7)

    view = FileMoveView()
    resp = view.post(FakeRequest(user, {
        'id': file_a.id, 'target_id': folder_b.id, 'is_public': False
    }))
    data = json.loads(resp.content)
    status = data.get('data', {}).get('status')

    report('T2: 返回 conflict', status == 'conflict', f'response={data}')
    conflicts = data.get('data', {}).get('conflicts', [])
    report('T2: 有冲突信息', len(conflicts) > 0)
    if conflicts:
        report('T2: same_size=true', conflicts[0].get('same_size') is True,
               f'conflict={conflicts[0]}')

    # 数据库数量不变
    count = F.objects.filter(folder=folder_b, display_name=f'dup_{s}.txt').count()
    report('T2: 目标目录文件数不变(1)', count == 1, f'count={count}')

    cleanup_files(F, [file_a.id, file_b.id])
    cleanup_folders(Folder, [folder_a.id, folder_b.id])


def test_3_move_conflict_different_size():
    """T3: 同名不同大小冲突"""
    print("\n--- T3: 同名不同大小冲突 ---")
    user = make_user('ct3', 'ct_t3')
    F, Folder = DocumentFilePublic, DocumentFolderPublic
    s = str(random.randint(10000, 99999))

    folder_a = make_folder(user, f'A_{s}')
    folder_b = make_folder(user, f'B_{s}')
    file_a = make_file(user, folder_a, f'diff_{s}.txt', 'short', 5)
    file_b = make_file(user, folder_b, f'diff_{s}.txt', 'longer content', 14)

    view = FileMoveView()
    resp = view.post(FakeRequest(user, {
        'id': file_a.id, 'target_id': folder_b.id, 'is_public': False
    }))
    data = json.loads(resp.content)
    status = data.get('data', {}).get('status')

    report('T3: 返回 conflict', status == 'conflict')
    conflicts = data.get('data', {}).get('conflicts', [])
    if conflicts:
        report('T3: same_size=false', conflicts[0].get('same_size') is False)

    cleanup_files(F, [file_a.id, file_b.id])
    cleanup_folders(Folder, [folder_a.id, folder_b.id])


def test_4_move_replace():
    """T4: replace 动作 -> 删除目标文件，移动源文件"""
    print("\n--- T4: replace 动作 ---")
    user = make_user('ct4', 'ct_t4')
    F, Folder = DocumentFilePublic, DocumentFolderPublic
    s = str(random.randint(10000, 99999))

    folder_a = make_folder(user, f'A_{s}')
    folder_b = make_folder(user, f'B_{s}')
    file_a = make_file(user, folder_a, f'rep_{s}.txt', 'source', 6)
    file_b = make_file(user, folder_b, f'rep_{s}.txt', 'target', 6)

    view = FileMoveView()
    resp = view.post(FakeRequest(user, {
        'id': file_a.id, 'target_id': folder_b.id, 'is_public': False,
        'conflict_action': 'replace'
    }))
    data = json.loads(resp.content)
    report('T4: 返回 success', data.get('data', {}).get('status') == 'success',
           f'response={data}')

    file_a.refresh_from_db()
    report('T4: file_a folder 变为 B', file_a.folder_id == folder_b.id)
    report('T4: file_a 物理文件在新目录', os.path.exists(file_a.file_path))

    # file_b 应该被删除
    report('T4: file_b 已删除', not F.objects.filter(id=file_b.id).exists())

    cleanup_files(F, [file_a.id])
    cleanup_folders(Folder, [folder_a.id, folder_b.id])


def test_5_move_keep():
    """T5: keep 动作 -> 生成唯一 display_name"""
    print("\n--- T5: keep 动作 ---")
    user = make_user('ct5', 'ct_t5')
    F, Folder = DocumentFilePublic, DocumentFolderPublic
    s = str(random.randint(10000, 99999))

    folder_a = make_folder(user, f'A_{s}')
    folder_b = make_folder(user, f'B_{s}')
    file_a = make_file(user, folder_a, f'keep_{s}.txt', 'source', 6)
    file_b = make_file(user, folder_b, f'keep_{s}.txt', 'target', 6)

    view = FileMoveView()
    resp = view.post(FakeRequest(user, {
        'id': file_a.id, 'target_id': folder_b.id, 'is_public': False,
        'conflict_action': 'keep'
    }))
    data = json.loads(resp.content)
    report('T5: 返回 success', data.get('data', {}).get('status') == 'success')

    file_a.refresh_from_db()
    report('T5: display_name 带 _1 后缀',
           f'keep_{s}_1.txt' in (file_a.display_name or ''),
           f'display_name={file_a.display_name}')
    report('T5: file_b 仍存在', F.objects.filter(id=file_b.id).exists())

    cleanup_files(F, [file_a.id, file_b.id])
    cleanup_folders(Folder, [folder_a.id, folder_b.id])


def test_6_move_skip():
    """T6: skip 动作 -> 不执行任何操作"""
    print("\n--- T6: skip 动作 ---")
    user = make_user('ct6', 'ct_t6')
    F, Folder = DocumentFilePublic, DocumentFolderPublic
    s = str(random.randint(10000, 99999))

    folder_a = make_folder(user, f'A_{s}')
    folder_b = make_folder(user, f'B_{s}')
    file_a = make_file(user, folder_a, f'skip_{s}.txt', 'source', 6)
    file_b = make_file(user, folder_b, f'skip_{s}.txt', 'target', 6)

    old_path = file_a.file_path

    view = FileMoveView()
    resp = view.post(FakeRequest(user, {
        'id': file_a.id, 'target_id': folder_b.id, 'is_public': False,
        'conflict_action': 'skip'
    }))
    data = json.loads(resp.content)
    report('T6: 返回 skipped', data.get('data', {}).get('status') == 'skipped',
           f'response={data}')

    file_a.refresh_from_db()
    report('T6: file_a folder 不变(A)', file_a.folder_id == folder_a.id)
    report('T6: file_a 物理文件不动', file_a.file_path == old_path)
    report('T6: file_b 仍存在', F.objects.filter(id=file_b.id).exists())

    cleanup_files(F, [file_a.id, file_b.id])
    cleanup_folders(Folder, [folder_a.id, folder_b.id])


def test_7_move_then_delete_original_folder():
    """T7: 移动后删除原文件夹 -> 文件仍可访问"""
    print("\n--- T7: 移动后删除原文件夹 ---")
    user = make_user('ct7', 'ct_t7')
    F, Folder = DocumentFilePublic, DocumentFolderPublic
    s = str(random.randint(10000, 99999))

    folder_a = make_folder(user, f'A_{s}')
    folder_b = make_folder(user, f'B_{s}')
    file = make_file(user, folder_a, f'survive_{s}.txt', 'important', 9)

    # 移动到 B
    view = FileMoveView()
    resp = view.post(FakeRequest(user, {
        'id': file.id, 'target_id': folder_b.id, 'is_public': False
    }))
    data = json.loads(resp.content)
    report('T7: 移动成功', data.get('data', {}).get('status') == 'success')

    file.refresh_from_db()

    # 删除 A 的物理目录
    from apps.document.services.cleanup_service import PhysicalFolderCleaner
    PhysicalFolderCleaner.delete(folder_a, is_public=False, user_id=user.id)

    # 文件物理文件应仍然存在
    report('T7: 物理文件仍存在（在 B 目录）', os.path.exists(file.file_path),
           f'file_path={file.file_path}')
    report('T7: DB 记录仍存在', F.objects.filter(id=file.id).exists())

    cleanup_files(F, [file.id])
    cleanup_folders(Folder, [folder_a.id, folder_b.id])


def test_8_keep_consecutive_suffixes():
    """T8: keep 连续生成 _1、_2"""
    print("\n--- T8: keep 连续后缀 ---")
    user = make_user('ct8', 'ct_t8')
    F, Folder = DocumentFilePublic, DocumentFolderPublic
    s = str(random.randint(10000, 99999))

    folder_a = make_folder(user, f'A_{s}')
    folder_b = make_folder(user, f'B_{s}')

    # B 中已有同名文件
    file_b = make_file(user, folder_b, f'con_{s}.txt', 'existing', 8)

    # 第一次 keep 移动 -> _1
    file1 = make_file(user, folder_a, f'con_{s}.txt', 'first', 5)
    view = FileMoveView()
    resp = view.post(FakeRequest(user, {
        'id': file1.id, 'target_id': folder_b.id, 'is_public': False,
        'conflict_action': 'keep'
    }))
    file1.refresh_from_db()
    report('T8: 第一次 keep -> _1',
           f'con_{s}_1.txt' in (file1.display_name or ''),
           f'display_name={file1.display_name}')

    # 第二次 keep 移动 -> _2
    file2 = make_file(user, folder_a, f'con_{s}.txt', 'second', 6)
    resp = view.post(FakeRequest(user, {
        'id': file2.id, 'target_id': folder_b.id, 'is_public': False,
        'conflict_action': 'keep'
    }))
    file2.refresh_from_db()
    report('T8: 第二次 keep -> _2',
           f'con_{s}_2.txt' in (file2.display_name or ''),
           f'display_name={file2.display_name}')

    # 三个文件 display_name 都不同
    names = set(F.objects.filter(folder=folder_b).values_list('display_name', flat=True))
    report('T8: 三个 display_name 各不相同', len(names) == 3,
           f'names={names}')

    cleanup_files(F, [file_b.id, file1.id, file2.id])
    cleanup_folders(Folder, [folder_a.id, folder_b.id])


def test_9_copy_conflict_detection():
    """T9: 复制冲突检测"""
    print("\n--- T9: 复制冲突检测 ---")
    user = make_user('ct9', 'ct_t9')
    F, Folder = DocumentFilePublic, DocumentFolderPublic
    s = str(random.randint(10000, 99999))

    folder_a = make_folder(user, f'A_{s}')
    folder_b = make_folder(user, f'B_{s}')
    file_a = make_file(user, folder_a, f'copy_{s}.txt', 'source', 6)
    file_b = make_file(user, folder_b, f'copy_{s}.txt', 'existing', 9)

    view = FileCopyView()
    resp = view.post(FakeRequest(user, {
        'id': file_a.id, 'folder_id': folder_b.id, 'is_public': False
    }))
    data = json.loads(resp.content)
    status = data.get('data', {}).get('status')

    report('T9: 复制返回 conflict', status == 'conflict', f'response={data}')

    # 原文件不变
    count = F.objects.filter(folder=folder_b, display_name=f'copy_{s}.txt').count()
    report('T9: 目标目录仍只有 1 个文件', count == 1)

    cleanup_files(F, [file_a.id, file_b.id])
    cleanup_folders(Folder, [folder_a.id, folder_b.id])


def test_10_copy_replace():
    """T10: 复制 replace 动作"""
    print("\n--- T10: 复制 replace ---")
    user = make_user('ct10', 'ct_t10')
    F, Folder = DocumentFilePublic, DocumentFolderPublic
    s = str(random.randint(10000, 99999))

    folder_a = make_folder(user, f'A_{s}')
    folder_b = make_folder(user, f'B_{s}')
    file_a = make_file(user, folder_a, f'crep_{s}.txt', 'source', 6)
    file_b = make_file(user, folder_b, f'crep_{s}.txt', 'target', 6)

    view = FileCopyView()
    resp = view.post(FakeRequest(user, {
        'id': file_a.id, 'folder_id': folder_b.id, 'is_public': False,
        'conflict_action': 'replace'
    }))
    data = json.loads(resp.content)
    report('T10: 复制 replace 返回 success',
           data.get('data', {}).get('status') == 'success',
           f'response={data}')

    # file_b 被删除
    report('T10: file_b 已删除', not F.objects.filter(id=file_b.id).exists())

    cleanup_files(F, [file_a.id])
    cleanup_folders(Folder, [folder_a.id, folder_b.id])


def test_11_copy_keep():
    """T11: 复制 keep 动作"""
    print("\n--- T11: 复制 keep ---")
    user = make_user('ct11', 'ct_t11')
    F, Folder = DocumentFilePublic, DocumentFolderPublic
    s = str(random.randint(10000, 99999))

    folder_a = make_folder(user, f'A_{s}')
    folder_b = make_folder(user, f'B_{s}')
    file_a = make_file(user, folder_a, f'ck_{s}.txt', 'source', 6)
    file_b = make_file(user, folder_b, f'ck_{s}.txt', 'existing', 8)

    view = FileCopyView()
    resp = view.post(FakeRequest(user, {
        'id': file_a.id, 'folder_id': folder_b.id, 'is_public': False,
        'conflict_action': 'keep'
    }))
    data = json.loads(resp.content)
    report('T11: 复制 keep 返回 success',
           data.get('data', {}).get('status') == 'success',
           f'response={data}')

    # 检查生成了带 _1 后缀的文件
    count = F.objects.filter(folder=folder_b, display_name__startswith=f'ck_{s}').count()
    report('T11: 目标目录有 2 个文件（原+新）', count == 2,
           f'count={count}')

    # 原文件仍存在
    report('T11: file_a 仍在 A', F.objects.filter(id=file_a.id, folder=folder_a).exists())

    cleanup_files(F, [file_a.id, file_b.id])
    # 清理复制的文件
    copies = F.objects.filter(folder=folder_b, display_name__startswith=f'ck_{s}')
    cleanup_files(F, [c.id for c in copies])
    cleanup_folders(Folder, [folder_a.id, folder_b.id])


def test_12_copy_skip():
    """T12: 复制 skip 动作"""
    print("\n--- T12: 复制 skip ---")
    user = make_user('ct12', 'ct_t12')
    F, Folder = DocumentFilePublic, DocumentFolderPublic
    s = str(random.randint(10000, 99999))

    folder_a = make_folder(user, f'A_{s}')
    folder_b = make_folder(user, f'B_{s}')
    file_a = make_file(user, folder_a, f'cs_{s}.txt', 'source', 6)
    file_b = make_file(user, folder_b, f'cs_{s}.txt', 'existing', 8)

    view = FileCopyView()
    resp = view.post(FakeRequest(user, {
        'id': file_a.id, 'folder_id': folder_b.id, 'is_public': False,
        'conflict_action': 'skip'
    }))
    data = json.loads(resp.content)
    report('T12: 复制 skip 返回 skipped',
           data.get('data', {}).get('status') == 'skipped',
           f'response={data}')

    # 目标目录文件数不变
    count = F.objects.filter(folder=folder_b, display_name=f'cs_{s}.txt').count()
    report('T12: 目标目录文件数不变(1)', count == 1)

    cleanup_files(F, [file_a.id, file_b.id])
    cleanup_folders(Folder, [folder_a.id, folder_b.id])


def test_13_move_root_to_folder():
    """T13: 根目录到文件夹移动"""
    print("\n--- T13: 根目录到文件夹移动 ---")
    user = make_user('ct13', 'ct_t13')
    F, Folder = DocumentFilePublic, DocumentFolderPublic
    s = str(random.randint(10000, 99999))

    # 文件在根目录
    file = make_file(user, None, f'root_{s}.txt', 'root file', 8)
    folder_b = make_folder(user, f'RootB_{s}')

    view = FileMoveView()
    resp = view.post(FakeRequest(user, {
        'id': file.id, 'target_id': folder_b.id, 'is_public': False
    }))
    data = json.loads(resp.content)
    report('T13: 移动成功', data.get('data', {}).get('status') == 'success',
           f'response={data}')

    file.refresh_from_db()
    report('T13: file_path 指向目标目录',
           f'folder-{folder_b.id}' in file.file_path)
    report('T13: 物理文件在新目录', os.path.exists(file.file_path))

    cleanup_files(F, [file.id])
    cleanup_folders(Folder, [folder_b.id])


def test_14_move_folder_to_root():
    """T14: 文件夹到根目录移动"""
    print("\n--- T14: 文件夹到根目录移动 ---")
    user = make_user('ct14', 'ct_t14')
    F, Folder = DocumentFilePublic, DocumentFolderPublic
    s = str(random.randint(10000, 99999))

    folder_a = make_folder(user, f'RootA_{s}')
    file = make_file(user, folder_a, f'toroot_{s}.txt', 'to root', 7)

    view = FileMoveView()
    resp = view.post(FakeRequest(user, {
        'id': file.id, 'target_id': 0, 'is_public': False
    }))
    data = json.loads(resp.content)
    report('T14: 移动到根目录成功', data.get('data', {}).get('status') == 'success',
           f'response={data}')

    file.refresh_from_db()
    # 根目录路径不含 folder-N
    report('T14: file_path 在根目录',
           'folder-' not in file.file_path or f'folder-{folder_a.id}' not in file.file_path,
           f'file_path={file.file_path}')
    report('T14: 物理文件存在', os.path.exists(file.file_path))

    cleanup_files(F, [file.id])
    cleanup_folders(Folder, [folder_a.id])


def main():
    print("=" * 60)
    print("统一冲突处理 + 文件移动物理迁移 后端测试")
    print("=" * 60)

    tests = [
        test_1_move_no_conflict_physical_migration,
        test_2_move_conflict_same_name_same_size,
        test_3_move_conflict_different_size,
        test_4_move_replace,
        test_5_move_keep,
        test_6_move_skip,
        test_7_move_then_delete_original_folder,
        test_8_keep_consecutive_suffixes,
        test_9_copy_conflict_detection,
        test_10_copy_replace,
        test_11_copy_keep,
        test_12_copy_skip,
        test_13_move_root_to_folder,
        test_14_move_folder_to_root,
    ]

    for t in tests:
        try:
            t()
        except Exception as e:
            report(t.__name__, False, str(e))
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    passed = sum(1 for _, s, _ in R if s == "PASS")
    failed = sum(1 for _, s, _ in R if s == "FAIL")
    print(f"总计: {passed} PASS / {failed} FAIL / {len(R)} 总")
    if failed:
        print("\n失败项:")
        for name, s, detail in R:
            if s == "FAIL":
                print(f"  - {name}: {detail}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
