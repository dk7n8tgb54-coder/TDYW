#!/usr/bin/env python3
"""状态机审计 - 深层行为问题修复验证
验证 3 个行为级问题的修复效果
"""
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
WEB = BASE.parent.parent.parent.parent / 'spug_web' / 'src' / 'pages' / 'document' / 'stores'
API = BASE.parent

def rf(p):
    with open(p, encoding='utf-8') as f: return f.read()

results = []
def check(rid, title, verdict, evidence):
    results.append((rid, title, verdict, evidence))


# ── 问题2: pollMergeStatus Promise 无人消费 ──
def v_issue2():
    ioc = rf(WEB/'upload'/'core'/'controls'/'ItemOperationController.js')
    # 搜索整个文件
    has_poll = bool(re.search(r"pollMergeStatus\s*\(", ioc))
    has_catch = has_poll and bool(re.search(r"\.catch\s*\(", ioc))
    has_error_transition = bool(re.search(r"transition\('ERROR'", ioc))
    ev = [
        f"pollMergeStatus 后有 .catch(): {has_catch}",
        f"catch 中 transition('ERROR'): {has_error_transition}",
    ]
    v = "FIXED" if has_catch and has_error_transition else "NOT_FIXED"
    check("问题2", "pollMergeStatus Promise 无人消费", v, ev)


# ── 问题3: 幂等 completed 仍当新任务轮询 ──
def v_issue3():
    ioc = rf(WEB/'upload'/'core'/'controls'/'ItemOperationController.js')
    # 检查是否有 is_idempotent + status === 'completed' 的检查
    has_idempotent_check = bool(re.search(
        r"is_idempotent.*?status.*?completed.*?MERGE_SUCCESS",
        ioc, re.DOTALL
    ))
    # 更精确：检查是否在 RETRY_MERGE transition 之前
    idempotent_pos = ioc.find("is_idempotent")
    retry_merge_pos = ioc.find("transition('RETRY_MERGE')")
    has_check_before_retry = (idempotent_pos >= 0 and retry_merge_pos >= 0 
                              and idempotent_pos < retry_merge_pos)
    # 检查是否有 MERGE_SUCCESS 转换
    has_merge_success = bool(re.search(
        r"is_idempotent.*?completed.*?MERGE_SUCCESS",
        ioc, re.DOTALL
    ))
    ev = [
        f"幂等completed检查在RETRY_MERGE前: {has_check_before_retry}",
        f"幂等completed走MERGE_SUCCESS: {has_merge_success}",
    ]
    v = "FIXED" if has_check_before_retry and has_merge_success else "NOT_FIXED"
    check("问题3", "幂等completed仍当新任务轮询", v, ev)


# ── 问题5: cancel 未阻断合并副作用 ──
def v_issue5():
    merge_py = rf(API/'tasks'/'merge.py')
    has_is_cancelled = bool(re.search(r"def _is_cancelled\s*\(", merge_py))
    # 找 execute 方法内的取消检查点数量
    execute_start = merge_py.find('def execute(self')
    if execute_start >= 0:
        execute_window = merge_py[execute_start:execute_start+1500]
        checkpoint_count = len(re.findall(r"_is_cancelled\(\)", execute_window))
    else:
        checkpoint_count = 0
    # 检查是否有 cleanup_on_error 调用（取消时清理合并文件）
    has_cleanup = bool(re.search(r"_is_cancelled.*?cleanup_on_error", merge_py, re.DOTALL))
    ev = [
        f"有 _is_cancelled 方法: {has_is_cancelled}",
        f"execute() 中取消检查点数: {checkpoint_count}",
        f"取消时清理合并文件: {has_cleanup}",
    ]
    v = "FIXED" if has_is_cancelled and checkpoint_count >= 2 and has_cleanup else "NOT_FIXED"
    check("问题5", "cancel 未阻断合并副作用", v, ev)


def main():
    v_issue2()
    v_issue3()
    v_issue5()
    
    print("=" * 70)
    print("深层行为问题修复验证报告")
    print("=" * 70)
    fixed = not_fixed = 0
    for rid, title, verdict, ev in results:
        print(f"\n[{rid}] {title}")
        print(f"  结论: {verdict}")
        for e in ev:
            print(f"  - {e}")
        if verdict == "FIXED": fixed += 1
        else: not_fixed += 1
    print(f"\n{'='*70}")
    print(f"汇总: FIXED={fixed}  NOT_FIXED={not_fixed}  总计={len(results)}")
    print("=" * 70)

if __name__ == '__main__':
    main()
