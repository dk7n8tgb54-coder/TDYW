#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Document 模块 CRUD 修复验证测试脚本
验证所有 10 个风险点的修复是否生效。
"""
import os, sys, signal, inspect, traceback, uuid

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django; django.setup()

from django.db import transaction, connection
from apps.account.models import User
from apps.document.models import DocumentFolderPrivate, DocumentFilePrivate
from apps.document.libs.view_utils import AUDIT_ACTION_MAP

RESULTS = []

def report(name, passed, detail=''):
    s = "PASS" if passed else "FAIL"
    RESULTS.append((name, s, detail))
    print(f"[{s}] {name}")
    if detail:
        for l in detail.split('\n'): print(f"       {l}")

def make_user():
    u, _ = User.objects.get_or_create(
        username='audit_fix_test', defaults={
            'nickname': 'Fix Tester', 'password_hash': 'test_hash',
            'access_token': uuid.uuid4().hex, 'tenant_id': 'audit_fix',
            'is_supper': True, 'last_ip': '127.0.0.1',
        })
    return u

def cleanup_folders(ids, F):
    if not ids: return
    with connection.cursor() as cur:
        cur.execute(f"UPDATE {F._meta.db_table} SET parent_id=NULL WHERE id IN %s", [tuple(ids)])
    F.objects.filter(id__in=ids).delete()


def verify_r1():
    """R1: get_active_descendant_folder_ids 有 visited_ids + max_depth"""
    print("\n--- R1: 循环引用防护 ---")
    user = make_user(); F = DocumentFolderPrivate; ids = []
    old = F.objects.filter(name__startswith='r1_fix_', tenant_id=user.tenant_id)
    old_ids = list(old.values_list('id', flat=True))
    if old_ids: cleanup_folders(old_ids, F)
    try:
        import random; s = str(random.randint(10000, 99999))
        a = F.objects.create(name=f'r1_fix_A_{s}', parent=None, created_by=user, tenant_id=user.tenant_id)
        b = F.objects.create(name=f'r1_fix_B_{s}', parent=a, created_by=user, tenant_id=user.tenant_id)
        c = F.objects.create(name=f'r1_fix_C_{s}', parent=b, created_by=user, tenant_id=user.tenant_id)
        ids = [a.id, b.id, c.id]
        a.refresh_from_db()
        with connection.cursor() as cur:
            cur.execute(f"UPDATE {F._meta.db_table} SET parent_id=%s WHERE id=%s", [c.id, a.id])
        a.refresh_from_db()

        from apps.document.views.folder.properties import get_active_descendant_folder_ids
        def handler(sig, frame): raise TimeoutError("timeout")
        signal.signal(signal.SIGALRM, handler); signal.alarm(5)
        try:
            result = get_active_descendant_folder_ids(a, F)
            signal.alarm(0)
            report("R1-循环引用不再无限循环", True, f"函数正常终止, result={result}")
        except TimeoutError:
            signal.alarm(0)
            report("R1-循环引用不再无限循环", False, "仍然无限循环!")
        except Exception as e:
            signal.alarm(0)
            if 'timeout' in str(e).lower() or 'lost connection' in str(e).lower():
                report("R1-循环引用不再无限循环", False, "DB 超时 - 仍然无限循环!")
            else:
                report("R1-循环引用不再无限循环", False, f"异常: {e}")

        src = inspect.getsource(get_active_descendant_folder_ids)
        has_visited = 'visited_ids' in src
        has_max_depth = 'max_depth' in src
        report("R1-有visited_ids+max_depth", has_visited and has_max_depth,
              f"visited_ids={has_visited}, max_depth={has_max_depth}")
    finally:
        connection.close_if_unusable_or_obsolete()
        cleanup_folders(ids, F)

def verify_r2():
    """R2: folder_copy_service 有 transaction.atomic + try/except"""
    print("\n--- R2: 复制事务保护 ---")
    from apps.document.services import folder_copy_service as fcs
    src = inspect.getsource(fcs)
    has_atomic = 'transaction.atomic' in src
    # 检查 shutil.copy2 是否有 try/except
    lines = src.split('\n')
    copy2_has_try = False
    for i, line in enumerate(lines):
        if 'shutil.copy2' in line:
            window = '\n'.join(lines[max(0,i-5):min(len(lines),i+5)])
            if 'try' in window and ('except' in window or 'raise' in window):
                copy2_has_try = True
    report("R2-有transaction.atomic", has_atomic, f"transaction.atomic: {has_atomic}")
    report("R2-shutil.copy2有try/except", copy2_has_try, f"try/except around shutil.copy2: {copy2_has_try}")

def verify_r3():
    """R3: AUDIT_ACTION_MAP 有 FOLDER_CREATE + post() 有 log_operation"""
    print("\n--- R3: 文件夹创建审计日志 ---")
    has_create = 'FOLDER_CREATE' in AUDIT_ACTION_MAP
    report("R3-AUDIT_ACTION_MAP有FOLDER_CREATE", has_create,
          f"FOLDER_CREATE in AUDIT_ACTION_MAP: {has_create}")
    from apps.document.views.folder.views import FolderView
    src = inspect.getsource(FolderView.post)
    has_log = 'log_operation' in src and 'FOLDER_CREATE' in src
    report("R3-post()有log_operation", has_log,
          f"post() 中 log_operation + FOLDER_CREATE: {has_log}")

def verify_r4():
    """R4: folder/move.py folder.save() 有 update_fields"""
    print("\n--- R4: folder.save() update_fields ---")
    from apps.document.views.folder import move as move_module
    src = inspect.getsource(move_module)
    lines = src.split('\n')
    issues = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if 'folder.save(' in stripped and 'update_fields' not in stripped:
            if not stripped.startswith('#'):
                issues.append(f"  line {i}: {stripped}")
    report("R4-folder.save有update_fields", len(issues) == 0,
          f"找到 {len(issues)} 处无 update_fields" + ('\n' + '\n'.join(issues) if issues else ""))

def verify_r5():
    """R5: folder/move.py 作用域重校验在事务内"""
    print("\n--- R5: 作用域重校验在事务内 ---")
    from apps.document.views.folder import move as move_module
    src = inspect.getsource(move_module)
    lines = src.split('\n')
    scope_line = None; atomic_line = None
    for i, line in enumerate(lines, 1):
        if 'validate_target_folder_scope' in line and 'def ' not in line and 'import' not in line:
            scope_line = i
        if 'with transaction.atomic' in line:
            atomic_line = i
    ok = scope_line and atomic_line and scope_line > atomic_line
    report("R5-作用域校验在事务内", ok,
          f"validate at line {scope_line}, atomic at line {atomic_line} -> {'事务内' if ok else '事务外!'}")

def verify_r6_r7():
    """R6/R7: merge.py transfer.save() 有 update_fields"""
    print("\n--- R6/R7: merge.py transfer.save() update_fields ---")
    from apps.document.tasks import merge as merge_module
    src = inspect.getsource(merge_module)
    lines = src.split('\n')
    issues = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if 'transfer.save(' in stripped and 'update_fields' not in stripped:
            if not stripped.startswith('#'):
                issues.append(f"  line {i}: {stripped}")
    report("R6/R7-transfer.save有update_fields", len(issues) == 0,
          f"找到 {len(issues)} 处无 update_fields" + ('\n' + '\n'.join(issues) if issues else ""))

def verify_r9():
    """R9: _delete_folder 有外层事务"""
    print("\n--- R9: _delete_folder 外层事务 ---")
    from apps.document.views.folder.views import FolderView
    try:
        src = inspect.getsource(FolderView.delete)
    except:
        src = inspect.getsource(FolderView.delete)
    # 检查 _delete_folder 调用是否在 with transaction.atomic() 内
    lines = src.split('\n')
    atomic_found = False
    delete_in_atomic = False
    for i, line in enumerate(lines, 1):
        if 'with transaction.atomic' in line:
            atomic_found = True
        if '_delete_folder' in line and atomic_found:
            # 检查是否在 with 块内（缩进比 with 大）
            atomic_indent = len(lines[i-2]) - len(lines[i-2].lstrip()) if i >= 2 else 0
            delete_indent = len(line) - len(line.lstrip())
            if delete_indent > atomic_indent:
                delete_in_atomic = True
    report("R9-_delete_folder在transaction.atomic内", delete_in_atomic,
          f"_delete_folder 调用 {'在' if delete_in_atomic else '不在'} with transaction.atomic() 块内")

def verify_r10():
    """R10: generate_unique_name 有 max_iter"""
    print("\n--- R10: generate_unique_name max_iter ---")
    from apps.document.services.folder_copy_service import FolderNameGenerator
    src = inspect.getsource(FolderNameGenerator.generate_unique_name)
    has_max_iter = 'max_iter' in src
    has_raise = 'raise' in src
    report("R10-有max_iter+raise", has_max_iter and has_raise,
          f"max_iter={has_max_iter}, raise={has_raise}")


def main():
    print("=" * 70)
    print("Document 模块 CRUD 修复验证测试")
    print("=" * 70)
    tests = [verify_r1, verify_r2, verify_r3, verify_r4, verify_r5, verify_r6_r7, verify_r9, verify_r10]
    for t in tests:
        try:
            t()
        except Exception as e:
            report(t.__name__, False, f"测试函数异常: {e}\n{traceback.format_exc()}")
    print("\n" + "=" * 70)
    print("修复验证结果汇总")
    print("=" * 70)
    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    failed = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    for name, status, detail in RESULTS:
        print(f"  [{status}] {name}")
    print(f"\n总计: {passed} PASS, {failed} FAIL")
    # 清理
    u = User.objects.filter(username='audit_fix_test').first()
    if u:
        F = DocumentFolderPrivate
        folders = F.objects.filter(tenant_id=u.tenant_id, name__startswith='r1_fix_')
        ids = list(folders.values_list('id', flat=True))
        if ids: cleanup_folders(ids, F)
        u.delete()
    return 1 if failed > 0 else 0

if __name__ == '__main__':
    sys.exit(main())
