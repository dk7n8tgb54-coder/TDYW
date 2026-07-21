#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
审计日志列表压测脚本(上线前必补 🔴)

风险:审计日志数据量大(每日万级),列表查询需计算每条 log_hash 形成哈希链(O(n)),
时间范围筛选 + 分页 + 哈希链验证叠加,大数据量下可能慢。

覆盖场景:
1. 分页查询(翻页到深页)- GET /api/logs/audit/
2. 时间范围筛选(start_time/end_time)
3. action 类型筛选
4. target_type 筛选
5. 导出(全量)- GET /api/logs/audit/export/

运行:
    python -m locust -f locustfile/locustfile_audit_log.py -H http://localhost
    python -m locust -f locustfile/locustfile_audit_log.py -H http://localhost \\
        --headless -u 20 -r 5 -t 5m --csv=audit_log

关注指标:
- 深页 P95(翻到第 100 页,OFFSET 2000 行)
- 时间筛选 P95(跨月查询)
- 导出响应时间(全量导出可能 10s+)
- MySQL slow query log 是否出现
"""

import random
from datetime import datetime, timedelta

from locust import task, between, events

from _common import TokenSharedHttpUser


class AuditLogUser(TokenSharedHttpUser):
    """审计日志查询压测用户(Token 池共享)"""

    wait_time = between(0.5, 1.5)

    @task(5)
    def list_first_page(self):
        """首页查询(最常见)"""
        with self._get(
            "/api/logs/audit/",
            "GET /api/logs/audit/ (首页)",
            params={"page": 1, "page_size": 20},
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:120]}")

    @task(3)
    def list_deep_page(self):
        """深页查询(测 OFFSET 性能)"""
        page = random.randint(50, 200)
        with self._get(
            "/api/logs/audit/",
            f"GET /api/logs/audit/ (深页 page={page})",
            params={"page": page, "page_size": 20},
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:120]}")

    @task(4)
    def filter_by_time_range(self):
        """时间范围筛选"""
        end = datetime.now()
        start = end - timedelta(days=random.choice([1, 7, 30, 90]))
        with self._get(
            "/api/logs/audit/",
            "GET /api/logs/audit/ (时间筛选)",
            params={
                "page": 1, "page_size": 20,
                "start_time": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": end.strftime("%Y-%m-%d %H:%M:%S"),
            },
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:120]}")

    @task(3)
    def filter_by_action(self):
        """action 类型筛选"""
        action = random.choice(["login", "logout", "create", "update", "delete", "export"])
        with self._get(
            "/api/logs/audit/",
            f"GET /api/logs/audit/ (action={action})",
            params={"page": 1, "page_size": 20, "action": action},
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:120]}")

    @task(2)
    def filter_by_target_type(self):
        """target_type 筛选"""
        target_type = random.choice(["user", "role", "document", "tenant", "auth"])
        with self._get(
            "/api/logs/audit/",
            f"GET /api/logs/audit/ (target_type={target_type})",
            params={"page": 1, "page_size": 20, "target_type": target_type},
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:120]}")

    @task(1)
    def export_audit_log(self):
        """导出审计日志(全量,可能慢)"""
        end = datetime.now()
        start = end - timedelta(days=7)
        with self._get(
            "/api/logs/audit/export/",
            "GET /api/logs/audit/export/ (导出)",
            params={
                "start_time": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": end.strftime("%Y-%m-%d %H:%M:%S"),
            },
            stream=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:120]}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("审计日志列表压测开始")
    print("⚠️  关注: 深页 OFFSET 性能、时间筛选、导出响应时间")
    print("=" * 60)
