#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
权限缓存击穿压测脚本(上线后可补 🟡)

风险:超管频繁修改角色权限 → Role.perms_version 自增 → 大量用户权限缓存同时失效 →
Redis 缓存击穿 → DB 集中查询角色权限。

覆盖场景:
1. 普通用户高频查询(命中缓存)
2. 超管修改角色权限(触发缓存失效)
3. 普通用户重新查询(缓存重建)

运行:
    python -m locust -f locustfile/locustfile_permission_cache.py -H http://localhost
    python -m locust -f locustfile/locustfile_permission_cache.py -H http://localhost \\
        --headless -u 30 -r 5 -t 5m --csv=permission_cache

关注: 普通用户查询 P95(缓存命中应 <100ms)、超管 PATCH、Redis 缓存命中率
"""

import random
import time

from locust import task, between, events

from _common import TokenSharedHttpUser, login, get_headers, STRESS_ACCOUNTS


class NormalUser(TokenSharedHttpUser):
    """普通用户:高频查询(命中缓存)"""

    wait_time = between(0.2, 0.8)
    weight = 5

    @task(10)
    def query_user_info(self):
        with self._get("/api/account/user/",
                       "GET /api/account/user/ (普通用户-缓存命中)") as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @task(5)
    def query_roles(self):
        with self._get("/api/account/role/",
                       "GET /api/account/role/ (普通用户-缓存命中)") as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")


class AdminCacheBuster(TokenSharedHttpUser):
    """超管:周期性修改角色权限(触发缓存失效风暴)"""

    wait_time = between(5, 15)
    weight = 1

    def on_start(self):
        # 超管用 admin 账号单独登录(不走 token 池)
        self.token = login(self.client, "admin", "Admin888..")
        self.username = "admin"
        self.role_ids = []
        self._fetch_roles()

    def _fetch_roles(self):
        # RoleView.get 返回 json_response(roles),即 {data: [role1, role2, ...]}
        # data 本身就是数组,不是 {data: {data: [...]}}
        with self._get("/api/account/role/", "[准备] 获取角色列表") as resp:
            if resp.status_code == 200:
                roles = resp.json().get("data") or []
                self.role_ids = [r.get("id") for r in roles if r.get("id")]
            else:
                resp.success()

    @task(1)
    def toggle_role_permission(self):
        if not self.role_ids:
            return
        role_id = random.choice(self.role_ids)
        # RoleView.patch 是 PATCH 方法(原脚本用 _post → 405)
        with self._patch(
            "/api/account/role/",
            "PATCH /api/account/role/ (超管-触发缓存失效)",
            json={"id": role_id, "desc": f"压测更新_{int(time.time())}"},
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:120]}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("权限缓存击穿压测开始")
    print("⚠️  超管会修改角色描述触发 perms_version 自增")
    print("⚠️  关注: 普通用户 P95 在缓存失效时是否飙高")
    print("=" * 60)
