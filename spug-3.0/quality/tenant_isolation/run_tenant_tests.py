#!/usr/bin/env python
"""租户隔离专项测试 - 专用运行入口

在 Docker 容器内执行:
    python quality_tenant_isolation/run_tenant_tests.py

或在宿主机通过 WSL:
    wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -e PYTHONUNBUFFERED=1 -w /data/spug/spug_api tdyw-test python quality_tenant_isolation/run_tenant_tests.py'

功能:
1. 设置 Django 环境 (ALLOWED_HOSTS + Client IP patch)
2. 依次执行 7 个测试模块
3. 汇总结果并输出 JSON
"""
import os
import sys
import json
import traceback

# 确保能找到 Django 和测试模块
# 当从容器内 /data/spug/spug_api 执行时，当前目录已在 sys.path
# 将 quality_tenant_isolation 目录加入 path 以便 import factories/helpers
_here = os.path.dirname(os.path.abspath(__file__))
# 项目根目录 (spug_api/) 是 _here 的上两级 (quality/tenant_isolation -> 项目根)
# 但在容器内 _here 就是 /data/spug/spug_api/quality_tenant_isolation
# 所以项目根是 _here 的父目录
_project_root = os.path.dirname(_here)
sys.path.insert(0, _project_root)  # spug_api/ 目录，用于 import spug.settings
sys.path.insert(0, _here)  # quality_tenant_isolation/ 目录，用于 import factories/helpers
sys.path.insert(0, os.path.join(_here, 'tests'))  # tests/ 子目录，避免与 spug_api/tests/ 冲突

# Django 设置
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

from django.conf import settings
settings.ALLOWED_HOSTS = ['*']

# Patch Django Test Client 以设置 IP header
from django.test import Client
_orig_request = Client.request
def _patched_request(self, **request):
    request['HTTP_X_REAL_IP'] = '127.0.0.1'
    return _orig_request(self, **request)
Client.request = _patched_request

# 导入测试模块（直接导入，避免 tests 包名冲突）
import test_cross_tenant_crud
import test_cross_tenant_relations
import test_cross_tenant_files
import test_cross_tenant_statistics
import test_cross_tenant_cache
import test_cross_tenant_tasks
import test_global_data_boundaries

ALL_TEST_MODULES = [
    ('CRUD 跨租户测试', test_cross_tenant_crud),
    ('跨租户关联测试', test_cross_tenant_relations),
    ('跨租户文件隔离测试', test_cross_tenant_files),
    ('跨租户统计测试', test_cross_tenant_statistics),
    ('跨租户缓存测试', test_cross_tenant_cache),
    ('跨租户任务测试', test_cross_tenant_tasks),
    ('全局数据边界测试', test_global_data_boundaries),
]


def main():
    print('=' * 60)
    print('  全系统租户隔离与跨租户越权专项测试')
    print('=' * 60)

    # 获取 bootstrap user
    from apps.account.models import User
    bootstrap = User.objects.first()
    if not bootstrap:
        print('ERROR: 数据库中无用户，无法创建测试数据')
        sys.exit(1)

    context = {'bootstrap_user': bootstrap}
    all_results = []

    for name, module in ALL_TEST_MODULES:
        print(f'\n{"=" * 60}')
        print(f'  {name}')
        print(f'{"=" * 60}')
        try:
            results = module.run(context)
            for r in results:
                status = 'PASS' if r['passed'] else ('SKIP' if r['passed'] is None else 'FAIL')
                print(f"  [{status}] {r['module']}/{r['test']}: {r['detail']}")
                all_results.append(r)
        except Exception as e:
            print(f'  模块异常: {e}')
            traceback.print_exc()
            all_results.append({
                'module': name,
                'test': f'{name} (模块异常)',
                'passed': False,
                'detail': str(e),
                'severity': 'error',
            })

    # 汇总
    print(f'\n{"=" * 60}')
    print('  测试汇总')
    print(f'{"=" * 60}')

    passed = sum(1 for r in all_results if r['passed'] is True)
    failed = sum(1 for r in all_results if r['passed'] is False)
    skipped = sum(1 for r in all_results if r['passed'] is None)
    total = len(all_results)

    print(f'  总计: {total} | 通过: {passed} | 失败: {failed} | 跳过(待测): {skipped}')

    if failed:
        print('\n  失败项:')
        for r in all_results:
            if r['passed'] is False:
                sev = r.get('severity', 'info').upper()
                print(f"    [{sev}] {r['module']}/{r['test']}: {r['detail']}")

    if skipped:
        print(f'\n  跳过(待行为测试): {skipped} 项')

    # 按严重度统计
    sev_counts = {}
    for r in all_results:
        if r['passed'] is False:
            sev = r.get('severity', 'info').lower()
            sev_counts[sev] = sev_counts.get(sev, 0) + 1
    if sev_counts:
        print('\n  漏洞严重度分布:')
        for sev in ['critical', 'high', 'medium', 'low', 'error']:
            if sev in sev_counts:
                print(f'    {sev.upper()}: {sev_counts[sev]}')

    # 输出 JSON 供报告生成
    print('\n__RESULTS_JSON__')
    print(json.dumps(all_results, ensure_ascii=False))


if __name__ == '__main__':
    main()
