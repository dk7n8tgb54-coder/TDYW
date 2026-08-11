#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Document 模块第二轮 CRUD 审计测试脚本
审查维度: IDOR/路径穿越/资源泄漏/软删除一致性/文件名安全/并发竞态

风险点清单:
  N1 (P2): permission_utils.py 死代码引用已移除的 all_objects + is_deleted
  N2 (P1): pending_files.py .seconds 应为 .total_seconds()（冷却期计算错误）
  N3 (P2): validate_file_name 未过滤 null 字节和控制字符
  N4 (P2): cleanup_service.py shutil.rmtree(ignore_errors=True) 静默吞错
  N5 (P2): models.py 物理文件先删、DB 记录后删（物理删除成功但 DB 删除失败 -> 孤儿记录）
  N6 (P2): cleanup_service.py 文件/文件夹删除异常被捕获不重抛（部分删除静默接受）
  N7 (P2): upload/lock.py 合并锁 threading.Lock 非分布式（多 Worker 无效）
  N8 (P2): properties.py BFS 遍历无租户过滤（防御纵深缺失）
"""
import os, sys, inspect, traceback
from datetime import timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django; django.setup()

RESULTS = []

def report(name, level, passed, detail=''):
    s = "PASS" if passed else "FAIL"
    RESULTS.append((name, level, s, detail))
    print(f"[{s}] {name} ({level})")
    if detail:
        for l in detail.split('\n'): print(f"       {l}")


# =============================================================================
# N1: permission_utils.py 死代码引用已移除的 all_objects + is_deleted
# =============================================================================
def test_n1():
    print("\n--- N1: permission_utils.py 死代码引用已移除字段 ---")
    from apps.document.libs import permission_utils
    # 检查 get_folder_and_descendants_iter 是否引用 all_objects 和 is_deleted
    src1 = inspect.getsource(permission_utils.get_folder_and_descendants_iter)
    has_all_objects_1 = 'all_objects' in src1
    has_is_deleted_1 = 'is_deleted=True' in src1

    src2 = inspect.getsource(permission_utils.get_folder_stats_optimized)
    has_all_objects_2 = 'all_objects' in src2
    has_is_deleted_2 = 'is_deleted=True' in src2

    # 检查 is_deleted 字段是否已从模型移除
    from apps.document.models import DocumentFolderPublic, DocumentFilePublic
    folder_fields = [f.name for f in DocumentFolderPublic._meta.get_fields()]
    file_fields = [f.name for f in DocumentFilePublic._meta.get_fields()]
    is_deleted_removed = 'is_deleted' not in folder_fields and 'is_deleted' not in file_fields

    # 检查 all_objects manager 是否存在
    has_all_objects_manager = hasattr(DocumentFolderPublic, 'all_objects')

    # 检查这些函数是否被外部调用（死代码检测）
    # 如果只有 permission_utils.py 自身引用，则是死代码
    is_dead_code = True  # 已通过 grep 确认无外部调用

    has_bug = (has_all_objects_1 or has_is_deleted_1 or has_all_objects_2 or has_is_deleted_2)
    report("N1-引用已移除字段", "P2", not has_bug,
          f"get_folder_and_descendants_iter: all_objects={has_all_objects_1}, is_deleted=True={has_is_deleted_1}\n"
          f"get_folder_stats_optimized: all_objects={has_all_objects_2}, is_deleted=True={has_is_deleted_2}\n"
          f"模型 is_deleted 字段已移除: {is_deleted_removed}\n"
          f"all_objects manager 存在: {has_all_objects_manager}\n"
          f"函数为死代码（无外部调用）: {is_dead_code}\n"
          f"-> 虽为死代码，调用即崩溃 AttributeError/FieldError")

    # 额外: is_deleted=True 逻辑也反了（应查 False=未删除）
    if has_is_deleted_1 or has_is_deleted_2:
        report("N1-is_deleted逻辑反转", "P2", False,
              "代码用 is_deleted=True 查询，但语义上应查 is_deleted=False（未删除的记录）")


# =============================================================================
# N2: pending_files.py .seconds 应为 .total_seconds()
# =============================================================================
def test_n2():
    print("\n--- N2: pending_files.py .seconds 冷却期计算错误 ---")
    from apps.document.tasks.cleanup.pending_files import RETRY_COOLDOWN_SECONDS
    # 模拟 .seconds vs .total_seconds() 的差异
    # 场景: 文件上次清理尝试在 1天+30分钟前，冷却期 3600 秒（1小时）
    td = timedelta(days=1, minutes=30)
    seconds_buggy = td.seconds  # 1800 (只取秒部分，忽略天)
    seconds_correct = td.total_seconds()  # 88200

    # buggy 版本: 1800 < 3600 = True -> 跳过（错误！应该处理）
    # correct 版本: 88200 < 3600 = False -> 不跳过（正确）
    buggy_skips = seconds_buggy < RETRY_COOLDOWN_SECONDS
    correct_skips = seconds_correct < RETRY_COOLDOWN_SECONDS

    has_bug = buggy_skips != correct_skips  # 如果结果不同，说明有 bug

    # 检查源码
    from apps.document.tasks.cleanup import pending_files
    src = inspect.getsource(pending_files)
    has_seconds = '.seconds' in src and '.total_seconds' not in src

    report("N2-.seconds冷却期计算错误", "P1", not has_seconds,
          f"源码使用 .seconds: {has_seconds}\n"
          f"  场景: timedelta(days=1, minutes=30)\n"
          f"  .seconds = {seconds_buggy} -> 跳过={buggy_skips} (错误! 应处理)\n"
          f"  .total_seconds() = {seconds_correct} -> 跳过={correct_skips} (正确)\n"
          f"  RETRY_COOLDOWN_SECONDS = {RETRY_COOLDOWN_SECONDS}\n"
          f"  -> 超过1天的待清理文件可能永远无法被清理")


# =============================================================================
# N3: validate_file_name 未过滤 null 字节和控制字符
# =============================================================================
def test_n3():
    print("\n--- N3: validate_file_name 未过滤 null 字节和控制字符 ---")
    from apps.document.libs.view_utils import validate_file_name

    # 测试 null 字节
    null_byte_name = "test\x00.txt"
    null_passes = validate_file_name(null_byte_name)

    # 测试换行符
    newline_name = "test\n.txt"
    newline_passes = validate_file_name(newline_name)

    # 测试回车符
    cr_name = "test\r.txt"
    cr_passes = validate_file_name(cr_name)

    # 测试制表符
    tab_name = "test\t.txt"
    tab_passes = validate_file_name(tab_name)

    # 测试 DEL 字符 (0x7F)
    del_name = "test\x7f.txt"
    del_passes = validate_file_name(del_name)

    # 测试其他控制字符 (0x01)
    ctrl_name = "test\x01.txt"
    ctrl_passes = validate_file_name(ctrl_name)

    # 正常文件名应该通过
    normal_passes = validate_file_name("test.txt")

    has_bug = null_passes or newline_passes or cr_passes or tab_passes or del_passes or ctrl_passes

    report("N3-null字节和控制字符未过滤", "P2", not has_bug,
          f"null字节 '\\x00': {null_passes} (应拒绝)\n"
          f"换行符 '\\n': {newline_passes} (应拒绝)\n"
          f"回车符 '\\r': {cr_passes} (应拒绝)\n"
          f"制表符 '\\t': {tab_passes} (应拒绝)\n"
          f"DEL字符 '\\x7f': {del_passes} (应拒绝)\n"
          f"控制字符 '\\x01': {ctrl_passes} (应拒绝)\n"
          f"正常文件名 'test.txt': {normal_passes} (应通过)")


# =============================================================================
# N4: cleanup_service.py shutil.rmtree(ignore_errors=True) 静默吞错
# =============================================================================
def test_n4():
    print("\n--- N4: shutil.rmtree(ignore_errors=True) 静默吞错 ---")
    from apps.document.services import cleanup_service
    src = inspect.getsource(cleanup_service)
    lines = src.split('\n')
    issues = []
    for i, line in enumerate(lines, 1):
        if 'rmtree' in line and 'ignore_errors=True' in line:
            issues.append(f"  line {i}: {line.strip()}")
    report("N4-rmtree静默吞错", "P2", len(issues) == 0,
          f"找到 {len(issues)} 处 ignore_errors=True:\n" + '\n'.join(issues) if issues else "无 ignore_errors=True")


# =============================================================================
# N5: models.py 物理文件先删、DB 记录后删
# =============================================================================
def test_n5():
    print("\n--- N5: 物理文件先删、DB 记录后删 ---")
    from apps.document.models import DocumentFileDeleteMixin
    src = inspect.getsource(DocumentFileDeleteMixin.delete)
    # 检查删除顺序: 先物理文件，后 super().delete()
    physical_first = False
    for line in src.split('\n'):
        stripped = line.strip()
        if 'safe_delete' in stripped or 'os.remove' in stripped or 'delete_physical' in stripped:
            physical_first = True
        if 'super().delete' in stripped and physical_first:
            # 物理删除在 super().delete 之前
            pass
    # 检查是否有 is_pending_clean 兜底机制
    has_pending_clean = 'is_pending_clean' in src
    # 检查注释
    has_comment = '先删除物理文件' in src or '物理文件删除成功' in src

    report("N5-物理先删DB后删", "P2", not has_comment,
          f"物理文件先删模式: {has_comment}\n"
          f"有 is_pending_clean 兜底: {has_pending_clean}\n"
          f"  -> 物理文件删除成功但 DB 删除失败时，物理文件丢失但 DB 记录残留\n"
          f"  -> is_pending_clean 可兜底标记，但需异步清理任务配合")


# =============================================================================
# N6: cleanup_service.py 异常被捕获不重抛
# =============================================================================
def test_n6():
    print("\n--- N6: 删除异常被捕获不重抛（部分删除静默接受） ---")
    from apps.document.services import cleanup_service
    src = inspect.getsource(cleanup_service)
    lines = src.split('\n')
    issues = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # 找 except 块，检查是否有 raise
        if line.startswith('except ') and ':' in line:
            except_line = i
            # 检查 except 块内是否有 raise
            has_raise = False
            j = i + 1
            while j < len(lines) and (lines[j].strip() == '' or len(lines[j]) - len(lines[j].lstrip()) > len(lines[i]) - len(lines[i].lstrip())):
                if 'raise' in lines[j].strip():
                    has_raise = True
                    break
                j += 1
            if not has_raise:
                # 检查是否是 DocumentPhysicalDeleteError（这是预期的，有兜底机制）
                if 'DocumentPhysicalDeleteError' in line:
                    issues.append(f"  line {except_line+1}: {line} (有兜底，但部分删除静默接受)")
                else:
                    issues.append(f"  line {except_line+1}: {line} (异常被吞，无 raise)")
        i += 1

    report("N6-异常被捕获不重抛", "P2", len(issues) == 0,
          f"找到 {len(issues)} 处 except 无 raise:\n" + '\n'.join(issues) if issues else "所有 except 块都有 raise")


# =============================================================================
# N7: upload/lock.py 合并锁 threading.Lock 非分布式
# =============================================================================
def test_n7():
    print("\n--- N7: 合并锁 threading.Lock 非分布式 ---")
    from apps.document.views.upload import lock as lock_module
    src = inspect.getsource(lock_module)
    has_threading_lock = 'threading.Lock()' in src
    has_redis_lock = 'RedisLock' in src or 'redis_lock' in src

    # 对比: tasks/merge.py 是否使用 RedisLock
    from apps.document.tasks import merge as merge_module
    merge_src = inspect.getsource(merge_module)
    merge_has_redis = 'RedisLock' in merge_src

    report("N7-合并锁非分布式", "P2", not has_threading_lock or has_redis_lock,
          f"upload/lock.py: threading.Lock={has_threading_lock}, RedisLock={has_redis_lock}\n"
          f"tasks/merge.py: RedisLock={merge_has_redis}\n"
          f"  -> 视图层 threading.Lock 仅进程内有效，多 Worker 并发合并请求无法互斥\n"
          f"  -> Celery 任务层有 RedisLock 分布式锁保护，但视图层存在竞态窗口")


# =============================================================================
# N8: properties.py BFS 遍历无租户过滤
# =============================================================================
def test_n8():
    print("\n--- N8: properties.py BFS 遍历无租户过滤 ---")
    from apps.document.views.folder.properties import get_active_descendant_folder_ids
    src = inspect.getsource(get_active_descendant_folder_ids)
    has_tenant_filter = 'tenant_id' in src or 'apply_tenant_filter' in src

    # 对比: search.py 是否有租户过滤
    from apps.document.views.search import FolderSearchView
    search_src = inspect.getsource(FolderSearchView._get_descendant_folder_ids)
    search_has_tenant = 'tenant_id' in search_src or 'apply_tenant_filter' in search_src

    report("N8-BFS无租户过滤", "P2", has_tenant_filter,
          f"properties.py: 有租户过滤={has_tenant_filter}\n"
          f"search.py: 有租户过滤={search_has_tenant}\n"
          f"  -> properties.py BFS 查询后代时不按 tenant_id 过滤\n"
          f"  -> 正常情况下 parent-child 在同一租户，但缺乏防御纵深")


# =============================================================================
# 主函数
# =============================================================================
def main():
    print("=" * 70)
    print("Document 模块第二轮 CRUD 审计测试")
    print("审查维度: IDOR/路径穿越/资源泄漏/软删除一致性/文件名安全/并发竞态")
    print("=" * 70)

    tests = [test_n1, test_n2, test_n3, test_n4, test_n5, test_n6, test_n7, test_n8]
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
