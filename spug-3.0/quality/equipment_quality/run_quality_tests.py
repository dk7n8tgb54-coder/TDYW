#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""设备管理质量专项测试运行器（quality/equipment_quality）。

在 tdyw-test 容器内执行（隔离测试数据库，Django test runner 自动建
test_ 前缀库；spug 账号具备全局 CREATE 与 test_% 全权授权）：

    wsl docker exec -e MYSQL_DATABASE=spug_qa_el -e PYTHONIOENCODING=utf-8 \
        -w /data/spug/spug_api tdyw-test \
        python3 /data/spug/quality/equipment_quality/run_quality_tests.py [标签...]

- 默认运行本包全部四个模块；可传具体标签运行单个模块。
- QA_KEEPDB=0 时每次重建测试库（默认复用）。
- 与业务回归共用隔离库时，先跑业务回归再跑本套件（本套件的
  TransactionTestCase 会截断表）。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))  # /data/spug（容器内仓库根）
_API_ROOT = os.path.join(_REPO_ROOT, 'spug_api')

sys.path.insert(0, _API_ROOT)
sys.path.insert(0, _REPO_ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ['*']

from django.test.runner import DiscoverRunner  # noqa: E402


def main():
    labels = sys.argv[1:] or [
        'quality.equipment_quality.test_el_integration_contracts',
        'quality.equipment_quality.test_el_query_baseline',
        'quality.equipment_quality.test_el_robustness',
        'quality.equipment_quality.test_el_security',
    ]
    keepdb = os.environ.get('QA_KEEPDB', '1') != '0'
    runner = DiscoverRunner(verbosity=1, keepdb=keepdb, interactive=False)
    failures = runner.run_tests(labels)
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
