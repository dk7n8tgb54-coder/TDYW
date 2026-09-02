# -*- coding: utf-8 -*-
"""合同协议模块上线前测试执行器（容器内运行）。

用法：
    python /tmp/contract_qa_runner.py <测试模块列表文件>

静音应用 INFO 日志，输出测试结果、失败明细与错误堆栈。
"""
import logging
import os
import sys

# 运行器放在 /tmp，需显式把项目根目录加入模块搜索路径
sys.path.insert(0, os.environ.get('SPUG_PROJECT_DIR', '/data/spug/spug_api'))
os.chdir(os.environ.get('SPUG_PROJECT_DIR', '/data/spug/spug_api'))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django  # noqa: E402

django.setup()

logging.disable(logging.INFO)

from django.conf import settings  # noqa: E402
from django.test.utils import get_runner  # noqa: E402

with open(sys.argv[1]) as fh:
    labels = [line.strip() for line in fh if line.strip()]

TestRunner = get_runner(settings)
runner = TestRunner(verbosity=2, interactive=False, keepdb=False)
failures = runner.run_tests(labels)
sys.exit(1 if failures else 0)
