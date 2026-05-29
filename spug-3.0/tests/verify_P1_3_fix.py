#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
P1-3 合并锁修复 - 实现验证脚本（纯静态代码分析）
"""

import sys
import os
import re


def verify_merge_lock_class():
    """验证1: MergeLock类实现"""
    print("\n【验证1】MergeLock类实现")
    print("-" * 80)

    views_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'backend', 'apps', 'document', 'views.py')

    if not os.path.exists(views_path):
        print(f"\n❌ 错误: 找不到文件 {views_path}")
        return False

    with open(views_path, 'r', encoding='utf-8') as f:
        content = f.read()

    checks = {
        'MergeLock类定义': False,
        'acquire方法': False,
        'release方法': False,
        'is_locked方法': False,
        'get_held_duration方法': False,
        '超时机制': False,
    }

    # 检查MergeLock类
    if 'class MergeLock:' in content:
        checks['MergeLock类定义'] = True
        print("  ✅ MergeLock类定义: 已添加")

    if 'def acquire(self, timeout=None, blocking=True):' in content:
        checks['acquire方法'] = True
        print("  ✅ acquire方法: 支持timeout和blocking参数")

    if 'def release(self):' in content:
        checks['release方法'] = True
        print("  ✅ release方法: 已实现")

    if 'def is_locked(self):' in content:
        checks['is_locked方法'] = True
        print("  ✅ is_locked方法: 已实现")

    if 'def get_held_duration(self):' in content:
        checks['get_held_duration方法'] = True
        print("  ✅ get_held_duration方法: 已实现")

    if 'MERGE_LOCK_TIMEOUT' in content:
        checks['超时机制'] = True
        print("  ✅ 超时机制: MERGE_LOCK_TIMEOUT配置")

    all_passed = all(checks.values())
    if all_passed:
        print("\n  结果: ✅ MergeLock类已正确实现")
    else:
        print("\n  结果: ❌ MergeLock类实现不完整")

    return all_passed


def verify_get_merge_lock_optimization():
    """验证2: get_merge_lock函数优化"""
    print("\n【验证2】get_merge_lock函数优化（锁粒度）")
    print("-" * 80)

    views_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'backend', 'apps', 'document', 'views.py')

    with open(views_path, 'r', encoding='utf-8') as f:
        content = f.read()

    checks = {
        '函数签名更新': False,
        '锁粒度包含is_public': False,
        '锁粒度包含tenant_id': False,
        '使用MergeLock类': False,
    }

    # 检查函数签名
    if 'def get_merge_lock(file_hash, is_public, tenant_id):' in content:
        checks['函数签名更新'] = True
        print("  ✅ 函数签名: 更新为包含is_public和tenant_id")

    # 检查锁粒度
    if "'public' if is_public else 'private'" in content:
        checks['锁粒度包含is_public'] = True
        print("  ✅ 锁粒度: 包含空间类型（public/private）")

    if 'tenant_id or ' in content or "tenant_id or 'default'" in content:
        checks['锁粒度包含tenant_id'] = True
        print("  ✅ 锁粒度: 包含租户ID")

    # 检查使用MergeLock类
    if '_merge_locks[lock_key] = MergeLock()' in content:
        checks['使用MergeLock类'] = True
        print("  ✅ 使用MergeLock类: 锁池使用新的MergeLock类")

    all_passed = all(checks.values())
    if all_passed:
        print("\n  结果: ✅ get_merge_lock函数已优化")
    else:
        print("\n  结果: ❌ get_merge_lock函数优化不完整")

    return all_passed


def verify_cleanup_stale_locks():
    """验证3: cleanup_stale_locks函数"""
    print("\n【验证3】cleanup_stale_locks函数（过期锁清理）")
    print("-" * 80)

    views_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'backend', 'apps', 'document', 'views.py')

    with open(views_path, 'r', encoding='utf-8') as f:
        content = f.read()

    checks = {
        '函数定义': False,
        '检查超时2倍': False,
        '强制释放过期锁': False,
        '日志记录': False,
    }

    if 'def cleanup_stale_locks():' in content:
        checks['函数定义'] = True
        print("  ✅ cleanup_stale_locks函数: 已定义")

    if 'MERGE_LOCK_TIMEOUT * 2' in content:
        checks['检查超时2倍'] = True
        print("  ✅ 超时检查: 清理超过2倍超时时间的锁")

    if 'lock_obj.release()' in content and 'stale_locks' in content:
        checks['强制释放过期锁'] = True
        print("  ✅ 强制释放: 过期锁会被清理")

    if 'Force released stale lock' in content:
        checks['日志记录'] = True
        print("  ✅ 日志记录: 记录清理操作")

    all_passed = all(checks.values())
    if all_passed:
        print("\n  结果: ✅ cleanup_stale_locks函数已实现")
    else:
        print("\n  结果: ❌ cleanup_stale_locks函数实现不完整")

    return all_passed


def verify_line_2204_bug_fix():
    """验证4: 2204行bug修复"""
    print("\n【验证4】2204行bug修复（文件名长度验证）")
    print("-" * 80)

    views_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'backend', 'apps', 'document', 'views.py')

    with open(views_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    checks = {
        '文件名长度验证在锁获取之前': False,
        '未在验证中调用merge_lock.release()': False,
        '没有错误的锁释放': False,
    }

    # 查找文件名长度验证的行（大约在2200行附近）
    for i, line in enumerate(lines):
        if 'if len(unique_name) > 255:' in line:
            # 检查这行后面几行是否有merge_lock.release()
            validation_block = ''.join(lines[i:min(i+5, len(lines))])

            if 'merge_lock.release()' not in validation_block:
                checks['未在验证中调用merge_lock.release()'] = True
                print("  ✅ 文件名长度验证: 不包含错误的锁释放")

            # 检查锁获取是否在验证之后
            rest_of_file = ''.join(lines[i:])
            lock_acquire_pos = rest_of_file.find('merge_lock = get_merge_lock(')
            if lock_acquire_pos > 0:
                checks['文件名长度验证在锁获取之前'] = True
                print("  ✅ 执行顺序: 文件名验证在锁获取之前")

            break

    # 全局检查是否还有旧的错误代码模式
    if 'merge_lock.release()\n            return json_response(error=\'文件名过长，请缩短文件名后重试\')' not in ''.join(lines):
        checks['没有错误的锁释放'] = True
        print("  ✅ 旧错误代码: 已删除")

    all_passed = all(checks.values())
    if all_passed:
        print("\n  结果: ✅ 2204行bug已修复")
    else:
        print("\n  结果: ❌ 2204行bug修复不完整")

    return all_passed


def verify_idempotent_check():
    """验证5: 幂等性检查"""
    print("\n【验证5】幂等性检查（传输记录status字段）")
    print("-" * 80)

    views_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'backend', 'apps', 'document', 'views.py')

    with open(views_path, 'r', encoding='utf-8') as f:
        content = f.read()

    checks = {
        'COMPLETED状态检查': False,
        'MERGING状态检查': False,
        '幂等性返回': False,
        '检查在锁获取之前': False,
    }

    # 检查幂等性检查
    if "transfer_obj.status == 'COMPLETED'" in content:
        checks['COMPLETED状态检查'] = True
        print("  ✅ COMPLETED状态检查: 已实现")

    if "transfer_obj.status == 'MERGING'" in content:
        checks['MERGING状态检查'] = True
        print("  ✅ MERGING状态检查: 已实现")

    if "'message': '文件已合并完成'" in content:
        checks['幂等性返回'] = True
        print("  ✅ 幂等性返回: 已实现")

    # 检查幂等性检查是否在锁获取之前
    idempotent_pattern = r"transfer_obj\.status == 'COMPLETED'.*?merge_lock = get_merge_lock\("
    if re.search(idempotent_pattern, content, re.DOTALL):
        checks['检查在锁获取之前'] = True
        print("  ✅ 执行顺序: 幂等性检查在锁获取之前")

    all_passed = all(checks.values())
    if all_passed:
        print("\n  结果: ✅ 幂等性检查已实现")
    else:
        print("\n  结果: ❌ 幂等性检查不完整")

    return all_passed


def verify_lock_release_finally():
    """验证6: 锁释放finally块"""
    print("\n【验证6】锁释放finally块（高可用兜底）")
    print("-" * 80)

    views_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'backend', 'apps', 'document', 'views.py')

    with open(views_path, 'r', encoding='utf-8') as f:
        content = f.read()

    checks = {
        'finally块': False,
        'merge_lock.release()在finally中': False,
        'release异常捕获': False,
        '详细日志': False,
    }

    # 检查finally块
    if 'def merge_files_with_lock():' in content and 'finally:' in content:
        checks['finally块'] = True
        print("  ✅ finally块: 已添加")

    # 检查锁释放
    pattern = r'finally:.*?merge_lock\.release\(\)'
    if re.search(pattern, content, re.DOTALL):
        checks['merge_lock.release()在finally中'] = True
        print("  ✅ 锁释放: merge_lock.release()在finally中")

    # 检查release异常捕获
    if 'except Exception as release_error:' in content and 'Failed to release merge lock' in content:
        checks['release异常捕获'] = True
        print("  ✅ 异常捕获: release操作也捕获异常")

    # 检查详细日志
    if 'file_hash={file_hash}, is_public={is_public}, tenant={tenant_id}' in content:
        checks['详细日志'] = True
        print("  ✅ 详细日志: 包含file_hash、is_public、tenant_id")

    all_passed = all(checks.values())
    if all_passed:
        print("\n  结果: ✅ 锁释放finally块已实现")
    else:
        print("\n  结果: ❌ 锁释放finally块实现不完整")

    return all_passed


def main():
    """主函数"""
    print("\n" + "="*80)
    print("P1-3 合并锁修复 - 实现验证")
    print("="*80)

    # 运行所有验证
    results = {
        '【验证1】MergeLock类实现': verify_merge_lock_class(),
        '【验证2】get_merge_lock函数优化': verify_get_merge_lock_optimization(),
        '【验证3】cleanup_stale_locks函数': verify_cleanup_stale_locks(),
        '【验证4】2204行bug修复': verify_line_2204_bug_fix(),
        '【验证5】幂等性检查': verify_idempotent_check(),
        '【验证6】锁释放finally块': verify_lock_release_finally(),
    }

    print("\n" + "="*80)
    print("P1-3 实现验证总结")
    print("="*80)

    passed_count = sum(1 for v in results.values() if v)
    total_count = len(results)

    for name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 未通过"
        print(f"  {name}: {status}")

    print(f"\n通过率: {passed_count}/{total_count} ({passed_count/total_count*100:.1f}%)")

    if passed_count == total_count:
        print("\n🎉 P1-3修复方案已完全实现！")
        return 0
    else:
        print("\n⚠️  P1-3修复方案部分实现，需要继续完善")
        return 1


if __name__ == '__main__':
    # 设置控制台输出编码为UTF-8
    if sys.platform == 'win32':
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

    sys.exit(main())
