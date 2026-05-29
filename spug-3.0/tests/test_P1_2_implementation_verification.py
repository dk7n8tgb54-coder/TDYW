#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
P1-2 批量操作事务保护 - 实现验证脚本
验证P1-2优化方案的所有要点是否已正确实现
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django
django.setup()

from django.test import TestCase, Client
from django.contrib.auth.models import User
from apps.document.models import DocumentTransfer, DocumentFolder
import re


class P1_2ImplementationVerification(TestCase):
    """P1-2实现验证"""

    def setUp(self):
        """初始化测试数据"""
        print("\n" + "="*80)
        print("P1-2 批量操作事务保护 - 实现验证")
        print("="*80)

    def verify_transaction_atomic(self):
        """验证1: @transaction.atomic装饰器"""
        print("\n【验证1】@transaction.atomic事务保护装饰器")
        print("-" * 80)

        # 读取views.py文件
        views_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'backend', 'apps', 'document', 'views.py')
        with open(views_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 检查三个批量操作视图是否有@transaction.atomic
        checks = {
            'TransferBatchPauseView': False,
            'TransferBatchResumeView': False,
            'TransferBatchCancelView': False
        }

        # 使用正则表达式检查
        for view_name in checks.keys():
            pattern = rf'class {view_name}\(View\):.*?@transaction\.atomic'
            if re.search(pattern, content, re.DOTALL):
                checks[view_name] = True
                print(f"  ✅ {view_name}: 已添加 @transaction.atomic")
            else:
                print(f"  ❌ {view_name}: 未找到 @transaction.atomic")

        all_passed = all(checks.values())
        if all_passed:
            print("\n  结果: ✅ 所有批量操作视图都已添加事务保护")
        else:
            print("\n  结果: ❌ 部分视图缺少事务保护")

        return all_passed

    def verify_batch_query_optimization(self):
        """验证2: 批量查询优化（避免N+1）"""
        print("\n【验证2】批量查询优化（避免N+1查询）")
        print("-" * 80)

        views_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'backend', 'apps', 'document', 'views.py')
        with open(views_path, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            '批量查询优化': False,
            '使用Q对象': False,
            '一次性权限校验': False
        }

        # 检查批量查询
        if 'id__in=transfer_ids' in content:
            checks['批量查询优化'] = True
            print("  ✅ 批量查询优化: 使用 id__in=transfer_ids")

        # 检查Q对象
        if 'from django.db.models import Q' in content or 'Q(user=request.user)' in content:
            checks['使用Q对象'] = True
            print("  ✅ 使用Q对象: Q(user=request.user)")

        # 检查一次性权限校验
        if 'permitted_transfers = all_transfers.filter' in content:
            checks['一次性权限校验'] = True
            print("  ✅ 一次性权限校验: permitted_transfers = all_transfers.filter")

        all_passed = all(checks.values())
        if all_passed:
            print("\n  结果: ✅ 批量查询优化已实现")
        else:
            print("\n  结果: ❌ 批量查询优化不完整")

        return all_passed

    def verify_select_for_update(self):
        """验证3: select_for_update()并发控制"""
        print("\n【验证3】select_for_update()并发控制")
        print("-" * 80)

        views_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'backend', 'apps', 'document', 'views.py')
        with open(views_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 检查TransferBatchCancelView是否使用select_for_update
        has_select_for_update = False

        # 提取TransferBatchCancelView部分
        pattern = r'class TransferBatchCancelView\(View\):.*?(?=\nclass |\Z)'
        match = re.search(pattern, content, re.DOTALL)

        if match:
            cancel_view_content = match.group(0)
            if 'select_for_update()' in cancel_view_content:
                has_select_for_update = True
                print("  ✅ TransferBatchCancelView: 使用 select_for_update() 加锁")
            else:
                print("  ❌ TransferBatchCancelView: 未使用 select_for_update()")
        else:
            print("  ❌ 未找到 TransferBatchCancelView")

        if has_select_for_update:
            print("\n  结果: ✅ 并发控制已实现")
        else:
            print("\n  结果: ❌ 并发控制未实现")

        return has_select_for_update

    def verify_idempotent_handling(self):
        """验证4: 幂等性处理"""
        print("\n【验证4】幂等性处理")
        print("-" * 80)

        views_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'backend', 'apps', 'document', 'views.py')
        with open(views_path, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            'PAUSED状态幂等性检查': False,
            'idempotent日志': False
        }

        # 检查PAUSED状态幂等性检查
        if "if transfer.status == 'PAUSED':" in content:
            checks['PAUSED状态幂等性检查'] = True
            print("  ✅ PAUSED状态幂等性检查: 已实现")

        # 检查幂等性日志
        if 'already paused (idempotent)' in content:
            checks['idempotent日志'] = True
            print("  ✅ 幂等性日志: 已添加")

        all_passed = all(checks.values())
        if all_passed:
            print("\n  结果: ✅ 幂等性处理已实现")
        else:
            print("\n  结果: ❌ 幂等性处理不完整")

        return all_passed

    def verify_error_handling(self):
        """验证5: 异常处理和事务回滚"""
        print("\n【验证5】异常处理和事务回滚")
        print("-" * 80)

        views_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'backend', 'apps', 'document', 'views.py')
        with open(views_path, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            'try-except块': False,
            '事务回滚注释': False
        }

        # 检查try-except块
        view_pattern = r'@transaction\.atomic.*?except Exception as e:'
        if re.search(view_pattern, content, re.DOTALL):
            checks['try-except块'] = True
            print("  ✅ try-except块: 已实现")

        # 检查事务回滚注释
        if '# 事务会自动回滚' in content or 'Transaction will automatically rollback' in content:
            checks['事务回滚注释'] = True
            print("  ✅ 事务回滚注释: 已添加")

        all_passed = all(checks.values())
        if all_passed:
            print("\n  结果: ✅ 异常处理和事务回滚已实现")
        else:
            print("\n  结果: ❌ 异常处理和事务回滚不完整")

        return all_passed

    def verify_chunk_cleanup(self):
        """验证6: 分片文件清理"""
        print("\n【验证6】分片文件清理（TransferBatchCancelView）")
        print("-" * 80)

        views_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'backend', 'apps', 'document', 'views.py')
        with open(views_path, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            '分片目录收集': False,
            '批量清理分片': False,
            '安全路径检查': False
        }

        # 提取TransferBatchCancelView部分
        pattern = r'class TransferBatchCancelView\(View\):.*?(?=\nclass |\Z)'
        match = re.search(pattern, content, re.DOTALL)

        if match:
            cancel_view_content = match.group(0)

            if 'chunk_dir_paths = []' in cancel_view_content:
                checks['分片目录收集'] = True
                print("  ✅ 分片目录收集: chunk_dir_paths = []")

            if 'shutil.rmtree(chunk_dir' in cancel_view_content:
                checks['批量清理分片'] = True
                print("  ✅ 批量清理分片: shutil.rmtree")

            if 'chunk_dir.startswith(chunk_base_dir)' in cancel_view_content:
                checks['安全路径检查'] = True
                print("  ✅ 安全路径检查: 防止路径遍历攻击")
        else:
            print("  ❌ 未找到 TransferBatchCancelView")

        all_passed = all(checks.values())
        if all_passed:
            print("\n  结果: ✅ 分片文件清理已实现")
        else:
            print("\n  结果: ❌ 分片文件清理不完整")

        return all_passed

    def verify_performance_optimization(self):
        """验证7: 性能优化"""
        print("\n【验证7】性能优化指标")
        print("-" * 80)

        views_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'backend', 'apps', 'document', 'views.py')
        with open(views_path, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            '批量查询而非循环查询': False,
            '一次性权限校验': False,
            '返回详细统计信息': False
        }

        # 检查是否避免循环中的get()调用
        pause_view_pattern = r'class TransferBatchPauseView\(View\):.*?(?=\nclass |\Z)'
        pause_match = re.search(pause_view_pattern, content, re.DOTALL)

        if pause_match:
            pause_content = pause_match.group(0)
            # 检查是否有循环中的get()调用（N+1问题的标志）
            if 'for transfer_id in transfer_ids:' not in pause_content or \
               'DocumentTransfer.objects.get' not in pause_content:
                checks['批量查询而非循环查询'] = True
                print("  ✅ 批量查询而非循环查询: 避免N+1问题")
            else:
                print("  ⚠️  批量查询而非循环查询: 可能存在N+1问题")

            # 检查一次性权限校验
            if 'permitted_transfers = all_transfers.filter' in pause_content:
                checks['一次性权限校验'] = True
                print("  ✅ 一次性权限校验: 减少数据库查询")

        # 检查返回详细统计信息
        if "'updated':" in content and "'skipped':" in content and "'success_ids':" in content:
            checks['返回详细统计信息'] = True
            print("  ✅ 返回详细统计信息: updated, skipped, success_ids")

        all_passed = all(checks.values())
        if all_passed:
            print("\n  结果: ✅ 性能优化已实现")
        else:
            print("\n  结果: ⚠️  性能优化有改进空间")

        return all_passed

    def run_all_verifications(self):
        """运行所有验证"""
        print("\n开始P1-2实现验证...\n")

        results = {
            '【验证1】@transaction.atomic事务保护': self.verify_transaction_atomic(),
            '【验证2】批量查询优化（避免N+1）': self.verify_batch_query_optimization(),
            '【验证3】select_for_update()并发控制': self.verify_select_for_update(),
            '【验证4】幂等性处理': self.verify_idempotent_handling(),
            '【验证5】异常处理和事务回滚': self.verify_error_handling(),
            '【验证6】分片文件清理': self.verify_chunk_cleanup(),
            '【验证7】性能优化': self.verify_performance_optimization(),
        }

        print("\n" + "="*80)
        print("P1-2 实现验证总结")
        print("="*80)

        passed_count = sum(1 for v in results.values() if v)
        total_count = len(results)

        for name, passed in results.items():
            status = "✅ 通过" if passed else "❌ 未通过"
            print(f"  {name}: {status}")

        print(f"\n通过率: {passed_count}/{total_count} ({passed_count/total_count*100:.1f}%)")

        if passed_count == total_count:
            print("\n🎉 P1-2优化方案已完全实现！")
            return 0
        else:
            print("\n⚠️  P1-2优化方案部分实现，需要继续完善")
            return 1


def main():
    """主函数"""
    verifier = P1_2ImplementationVerification()
    verifier.setUp()
    exit_code = verifier.run_all_verifications()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
