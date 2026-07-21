#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
多租户并发压测脚本(上线后可补 🟡)

风险:多租户并发查询时,tenant_id 索引效率、租户隔离 SQL 是否正确加 WHERE 条件。

覆盖场景:
1. 多账号分属不同租户,并发查询各自数据
2. 跨租户访问(应被隔离)

注意:当前 5 个压测账号都在 stress 租户下,本脚本退化为同租户并发。
要测真实多租户,需在不同租户下各建账号。

运行:
    python -m locust -f locustfile/locustfile_multi_tenant.py -H http://localhost
    python -m locust -f locustfile/locustfile_multi_tenant.py -H http://localhost \\
        --headless -u 40 -r 5 -t 5m --csv=multi_tenant

关注: 各账号 QPS 均衡性、跨租户隔离、tenant_id WHERE
"""

from locust import task, between, events

from _common import TokenSharedHttpUser, STRESS_ACCOUNTS


class MultiTenantUser(TokenSharedHttpUser):
    """多租户并发用户(Token 池共享)"""

    wait_time = between(0.5, 1.5)

    @task(5)
    def list_own_documents(self):
        with self._get("/api/document/folder/?is_public=False",
                       "GET /api/document/folder/ (多租户-本租户)") as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @task(4)
    def list_own_audit_log(self):
        with self._get("/api/logs/audit/",
                       "GET /api/logs/audit/ (多租户-本租户)",
                       params={"page": 1, "page_size": 20}) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @task(3)
    def list_own_devices(self):
        with self._get("/api/device/device-resume/",
                       "GET /api/device/device-resume/ (多租户-本租户)",
                       params={"page": 1, "page_size": 20}) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @task(2)
    def list_own_interference(self):
        with self._get("/api/interference/",
                       "GET /api/interference/ (多租户-本租户)",
                       params={"page": 1, "page_size": 20}) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("多租户并发压测开始")
    print(f"账号池: {len(STRESS_ACCOUNTS)} 个(当前都在 stress 租户下)")
    print("⚠️  关注: 各账号 QPS 均衡性、跨租户隔离、tenant_id WHERE")
    print("=" * 60)
