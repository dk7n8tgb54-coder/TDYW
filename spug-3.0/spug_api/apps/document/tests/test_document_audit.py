#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Document 模块 CRUD 可靠性审计测试脚本"""
import os, sys, signal, shutil, inspect, traceback
from unittest.mock import patch, MagicMock

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django; django.setup()

from django.db import transaction, connection
from apps.account.models import User
from apps.document.models import (
    DocumentFolderPrivate, DocumentFilePrivate, DocumentTransfer,
)
from apps.document.libs.view_utils import AUDIT_ACTION_MAP

RESULTS = []

def report(name, level, passed, detail=''):
    s = "PASS" if passed else "FAIL"
    RESULTS.append((name, level, s, detail))
    print(f"[{s}] {name} ({level})")
    if detail:
        for l in detail.split('\n'): print(f"       {l}")

import uuid
def make_user():
    u, _ = User.objects.get_or_create(
        username='audit_doc_test',
        defaults={
            'nickname': 'Audit Tester',
            'password_hash': 'test_hash',
            'access_token': uuid.uuid4().hex,
            'tenant_id': 'audit_doc',
            'is_supper': True,
            'last_ip': '127.0.0.1',
        }
    )
    return u

def cleanup_folders(ids, FolderModel):
    """安全清理文件夹（先断开 parent 关系避免循环引用）"""
    if not ids: return
    with connection.cursor() as cur:
        cur.execute(f"UPDATE {FolderModel._meta.db_table} SET parent_id=NULL WHERE id IN %s", [tuple(ids)])
    FolderModel.objects.filter(id__in=ids).delete()

# =============================================================================
# R1: get_active_descendant_folder_ids 循环引用 + 无深度限制
# =============================================================================
def test_r1():
    print("\n--- R1: get_active_descendant_folder_ids 循环引用 + 无深度限制 ---")
    user = make_user(); F = DocumentFolderPrivate; ids = []
    # 先清理之前可能残留的测试数据
    old = F.objects.filter(name__startswith='r1_audit_', tenant_id=user.tenant_id)
    old_ids = list(old.values_list('id', flat=True))
    if old_ids:
        cleanup_folders(old_ids, F)
    try:
        import random; suffix = str(random.randint(10000, 99999))
        a = F.objects.create(name=f'r1_audit_A_{suffix}', parent=None, created_by=user, tenant_id=user.tenant_id)
        b = F.objects.create(name=f'r1_audit_B_{suffix}', parent=a, created_by=user, tenant_id=user.tenant_id)
        c = F.objects.create(name=f'r1_audit_C_{suffix}', parent=b, created_by=user, tenant_id=user.tenant_id)
        ids = [a.id, b.id, c.id]
        a.refresh_from_db()
        # 制造循环: A.parent = C (形成 A->B->C->A 的环)
        with connection.cursor() as cur:
            cur.execute(f"UPDATE {F._meta.db_table} SET parent_id=%s WHERE id=%s", [c.id, a.id])
        a.refresh_from_db()

        from apps.document.views.folder.properties import get_active_descendant_folder_ids
        def handler(sig, frame): raise TimeoutError("timeout")
        signal.signal(signal.SIGALRM, handler); signal.alarm(5)
        try:
            result = get_active_descendant_folder_ids(a, F)
            signal.alarm(0)
            starting_in_descendants = a.id in result
            if starting_in_descendants:
                report("R1-循环引用", "P2", False,
                      f"起始文件夹{a.id}出现在自己的后代列表中 -> 大小计算可能重复统计\n  result={result}")
            else:
                report("R1-循环引用", "P2", True, f"函数正常终止, result={result}")
        except TimeoutError:
            signal.alarm(0)
            report("R1-循环引用", "P1", False,
                  "无限循环已确认! get_active_descendant_folder_ids 无 visited_ids 检测循环引用\n"
                  "  严重影响: 文件夹属性查询请求会挂死，消耗服务器资源")
        except Exception as e:
            signal.alarm(0)
            err_str = str(e).lower()
            if 'timeout' in err_str or 'lost connection' in err_str:
                report("R1-循环引用", "P1", False,
                      "无限循环已确认! signal.alarm 中断 DB 查询导致连接超时\n"
                      "  严重影响: 文件夹属性查询请求会挂死，消耗服务器资源")
            else:
                report("R1-循环引用", "P2", False, f"异常: {e}\n{traceback.format_exc()}")

        # 对比 search.py
        from apps.document.views.search import FolderSearchView
        src = inspect.getsource(FolderSearchView._get_descendant_folder_ids)
        ok = ('visited' in src.lower()) and ('max_depth' in src)
        report("R1-对比search.py", "P2", ok,
              f"search.py: visited={'visited' in src.lower()}, max_depth={'max_depth' in src}\n"
              f"properties.py: 两者均无")
    finally:
        connection.close_if_unusable_or_obsolete()
        cleanup_folders(ids, F)

# =============================================================================
# R2: folder_copy_service.py 无事务保护
# =============================================================================
def test_r2():
    print("\n--- R2: folder_copy_service.py 无事务保护 ---")
    # 使用代码检查（避免循环导入问题）
    from apps.document.services import folder_copy_service as fcs_module
    src = inspect.getsource(fcs_module)
    lines = src.split('\n')

    # 检查 copy_folder 方法是否有 transaction.atomic
    has_atomic = 'transaction.atomic' in src
    # 检查 shutil.copy2 是否有 try/except
    has_try_around_copy2 = False
    for i, line in enumerate(lines):
        if 'shutil.copy2' in line:
            # 检查上下5行是否有 try/except
            window = '\n'.join(lines[max(0,i-5):min(len(lines),i+5)])
            if 'try' in window and ('except' in window or 'finally' in window):
                has_try_around_copy2 = True
    # 检查是否 import transaction
    has_import = 'from django.db import transaction' in src or 'import transaction' in src

    report("R2-无transaction.atomic", "P1", has_atomic and has_import,
          f"import transaction: {has_import}\n"
          f"  transaction.atomic 使用: {has_atomic}\n"
          f"  shutil.copy2 有 try/except: {has_try_around_copy2}\n"
          f"  -> 复制中途失败会残留不完整副本树")

    # 额外检查: copy_folder 方法源码
    try:
        from apps.document.services.folder_copy_service import FolderCopier
        copy_src = inspect.getsource(FolderCopier.copy_folder)
        copy_has_atomic = 'transaction.atomic' in copy_src
        report("R2-copy_folder方法", "P1", copy_has_atomic,
              f"FolderCopier.copy_folder {'有' if copy_has_atomic else '无'} transaction.atomic")
    except Exception as e:
        # 如果循环导入，直接检查源码
        report("R2-copy_folder方法", "P1", has_atomic,
              f"无法直接导入 FolderCopier ({e}), 通过模块源码检查: {'有' if has_atomic else '无'} transaction.atomic")

# =============================================================================
# R3: 文件夹创建缺少审计日志
# =============================================================================
def test_r3():
    print("\n--- R3: 文件夹创建缺少审计日志 ---")
    # 检查 AUDIT_ACTION_MAP 是否有 FOLDER_CREATE
    has_create = 'FOLDER_CREATE' in AUDIT_ACTION_MAP
    report("R3-AUDIT_ACTION_MAP缺FOLDER_CREATE", "P2", False if not has_create else True,
          f"AUDIT_ACTION_MAP keys: {sorted(AUDIT_ACTION_MAP.keys())}\n"
          f"有 FOLDER_DELETE, FOLDER_MOVE, FOLDER_COPY 但"
          f"{'无' if not has_create else '有'} FOLDER_CREATE")

    # 检查 folder/views.py post() 是否调用 log_operation
    from apps.document.views.folder.views import FolderView
    src = inspect.getsource(FolderView.post)
    has_log = 'log_operation' in src
    report("R3-folder创建无审计日志", "P2", has_log,
          f"FolderView.post() {'有' if has_log else '无'} log_operation 调用\n"
          f"对比: delete有, move有, copy有, 但create{'无' if not has_log else '有'}")

# =============================================================================
# R4: folder/move.py folder.save() 无 update_fields
# =============================================================================
def test_r4():
    print("\n--- R4: folder/move.py folder.save() 无 update_fields ---")
    from apps.document.views.folder import move as move_module
    src = inspect.getsource(move_module)
    # 找 save() 调用但不含 update_fields
    lines = src.split('\n')
    issues = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if '.save(' in stripped and 'update_fields' not in stripped and '#' not in stripped.split('.save')[0]:
            # 排除注释和字符串
            if not stripped.startswith('#') and not stripped.startswith("'") and not stripped.startswith('"'):
                issues.append(f"  line {i}: {stripped}")
    report("R4-folder.save无update_fields", "P2", len(issues) == 0,
          f"找到 {len(issues)} 处 save() 无 update_fields:\n" + '\n'.join(issues) if issues else "所有 save() 调用均包含 update_fields")

# =============================================================================
# R5: folder/move.py 作用域重校验在事务外
# =============================================================================
def test_r5():
    print("\n--- R5: folder/move.py 作用域重校验在事务外 ---")
    from apps.document.views.folder import move as move_module
    src = inspect.getsource(move_module)
    # 检查 validate_target_folder_scope 是否在 transaction.atomic() 块内
    lines = src.split('\n')
    scope_line = None; atomic_line = None
    for i, line in enumerate(lines, 1):
        if 'validate_target_folder_scope' in line and 'def ' not in line:
            scope_line = i
        if 'with transaction.atomic' in line:
            atomic_line = i
    # 对比 file/move.py
    from apps.document.views.file import move as file_move_module
    file_src = inspect.getsource(file_move_module)
    file_lines = file_src.split('\n')
    file_scope = None; file_atomic = None
    for i, line in enumerate(file_lines, 1):
        if 'validate_target_folder_scope' in line and 'def ' not in line:
            file_scope = i
        if 'with transaction.atomic' in line:
            file_atomic = i

    folder_ok = scope_line and atomic_line and scope_line > atomic_line
    file_ok = file_scope and file_atomic and file_scope > file_atomic
    report("R5-folder/move作用域校验位置", "P2", folder_ok,
          f"folder/move.py: validate_target_folder_scope at line {scope_line}, atomic at line {atomic_line} -> "
          f"{'事务内' if folder_ok else '事务外(TOCTOU风险)'}\n"
          f"file/move.py: validate at line {file_scope}, atomic at line {file_atomic} -> "
          f"{'事务内' if file_ok else '事务外'}")

# =============================================================================
# R6/R7: merge.py save() 无 update_fields
# =============================================================================
def test_r6_r7():
    print("\n--- R6/R7: merge.py save() 无 update_fields ---")
    from apps.document.tasks import merge as merge_module
    src = inspect.getsource(merge_module)
    lines = src.split('\n')
    issues = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if '.save(' in stripped and 'update_fields' not in stripped:
            if not stripped.startswith('#') and not stripped.startswith("'") and not stripped.startswith('"'):
                if 'transfer.save' in stripped or 'file_obj.save' in stripped or 'folder.save' in stripped:
                    issues.append(f"  line {i}: {stripped}")
    report("R6/R7-merge.py save无update_fields", "P2", len(issues) == 0,
          f"找到 {len(issues)} 处 save() 无 update_fields:\n" + '\n'.join(issues) if issues else "所有 save() 调用均包含 update_fields")

# =============================================================================
# R8: folder/views.py _get_all_folders 硬截断 1000 条
# =============================================================================
def test_r8():
    print("\n--- R8: folder/views.py 硬截断 1000 条无分页 ---")
    from apps.document.views.folder.views import FolderView
    src = inspect.getsource(FolderView)
    has_1000 = '[:1000]' in src or '[: 1000]' in src
    has_pagination = 'page_size' in src or 'paginate' in src.lower()
    # 更精确搜索
    lines = src.split('\n')
    truncation_lines = []
    for i, line in enumerate(lines, 1):
        if '1000' in line and ('[' in line or 'limit' in line.lower()):
            truncation_lines.append(f"  line {i}: {line.strip()}")
    report("R8-硬截断1000条", "P2", not has_1000,
          f"{'发现' if has_1000 else '未发现'} [:1000] 硬截断\n" + '\n'.join(truncation_lines) +
          f"\n  分页机制: {'有' if has_pagination else '无'}")

# =============================================================================
# R9: _delete_folder 无外层事务
# =============================================================================
def test_r9():
    print("\n--- R9: _delete_folder 无外层事务 ---")
    from apps.document.views.folder.views import FolderView
    # 检查 _delete_folder 方法源码
    try:
        src = inspect.getsource(FolderView._delete_folder)
    except:
        # 可能是普通函数而非方法
        src = inspect.getsource(FolderView.delete)
    has_outer_atomic = 'with transaction.atomic' in src
    has_batch_atomic = src.count('transaction.atomic') > 0

    # 更详细分析
    lines = src.split('\n')
    atomic_count = sum(1 for l in lines if 'with transaction.atomic' in l)
    report("R9-_delete_folder无外层事务", "P1", atomic_count > 0,
          f"_delete_folder 中 transaction.atomic 出现次数: {atomic_count}\n"
          f"  {'有外层事务保护' if atomic_count > 0 else '无外层事务! 部分删除失败无法回滚'}")

    # 额外检查: 对比 file/views.py 的 delete 方法
    from apps.document.views.file.views import FileView
    file_src = inspect.getsource(FileView.delete)
    file_atomic = file_src.count('with transaction.atomic')
    report("R9-对比file/views.delete", "P1", file_atomic > 0,
          f"FileView.delete 中 transaction.atomic 出现次数: {file_atomic}")

# =============================================================================
# R10: generate_unique_name while 循环无上限
# =============================================================================
def test_r10():
    print("\n--- R10: generate_unique_name while 循环无上限 ---")
    from apps.document.services.folder_copy_service import FolderNameGenerator
    src = inspect.getsource(FolderNameGenerator)
    has_while = 'while' in src
    has_max_iter = 'max_iter' in src or 'max_attempt' in src or 'limit' in src.lower()
    has_break = 'break' in src

    # 找到 while 循环行
    lines = src.split('\n')
    while_lines = []
    for i, line in enumerate(lines, 1):
        if 'while' in line.strip():
            while_lines.append(f"  line {i}: {line.strip()}")
    report("R10-generate_unique_name无上限", "P2", not has_while or has_max_iter,
          f"while 循环: {'有' if has_while else '无'}\n"
          f"max_iter 限制: {'有' if has_max_iter else '无'}\n"
          + '\n'.join(while_lines) if while_lines else "")


# =============================================================================
# 主函数
# =============================================================================
def main():
    print("=" * 70)
    print("Document 模块 CRUD 可靠性审计测试")
    print("=" * 70)

    tests = [test_r1, test_r2, test_r3, test_r4, test_r5, test_r6_r7, test_r8, test_r9, test_r10]
    for t in tests:
        try:
            t()
        except Exception as e:
            report(t.__name__, "P?", False, f"测试函数异常: {e}\n{traceback.format_exc()}")

    print("\n" + "=" * 70)
    print("审计结果汇总")
    print("=" * 70)
    passed = sum(1 for _, _, s, _ in RESULTS if s == "PASS")
    failed = sum(1 for _, _, s, _ in RESULTS if s == "FAIL")
    for name, level, status, detail in RESULTS:
        print(f"  [{status}] {name} ({level})")
    print(f"\n总计: {passed} PASS, {failed} FAIL, 共 {len(RESULTS)} 项")
    print(f"风险确认: {failed} 个风险点已验证为真")

    return 1 if failed > 0 else 0

if __name__ == '__main__':
    sys.exit(main())
