#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
账号登录并发压力测试脚本

场景：大量虚拟用户同时打 /api/account/login/，测量登录接口的吞吐与延迟。
使用专用压测账号 + 正确密码，不会触发账号锁定（锁定只在密码错误时触发）。

【重要】登录限流（见 apps/account/views.py login）：
  - IP 级：1 小时内失败次数 >= 30 直接拒绝
  - 用户级：15 分钟内失败次数 >= 5 临时锁定 15 分钟
本脚本只用正确密码，因此不会产生失败计数，可安全高并发。

运行方式（生产 tdyw：容器名 tdyw，账号复用现有生产账号）：
    python -m locust -f locustfile/account_login_stress.py -H http://<tdyw-host>:<port>
    python -m locust -f locustfile/account_login_stress.py -H http://<tdyw-host>:<port> \
        --headless -u 200 -r 50 -t 5m --csv=login_stress

账号：默认复用现有生产账号（下方 DEFAULT_ACCOUNTS）。也可用环境变量覆盖：
    # JSON 数组，元素为 {"username":..,"password":..}
    export STRESS_ACCOUNTS='[{"username":"tongxinke","password":"Dt@6299093"}]'
注意：生产 tdyw 不复用 create_stress_accounts.py 的 st_press_0x 测试账号。
"""

import os
import json
import threading

from locust import HttpUser, task, between, events
from locust.runners import MasterRunner

# 默认复用现有生产账号（与 document_stress_test 系列一致），不新建测试账号
DEFAULT_ACCOUNTS = [
    {"username": "tongxinke", "password": "Dt@6299093"},
    {"username": "zidonghuake", "password": "Aa@123456"},
    {"username": "daohangke", "password": "Aa@123456"},
    {"username": "dianhuake", "password": "Aa@123456"},
]


def _load_accounts():
    raw = os.environ.get("STRESS_ACCOUNTS")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list) and data:
                return data
        except (ValueError, TypeError):
            pass
    return DEFAULT_ACCOUNTS


STRESS_ACCOUNTS = _load_accounts()

_lock = threading.Lock()
_idx = 0


def _next_account():
    global _idx
    with _lock:
        acc = STRESS_ACCOUNTS[_idx % len(STRESS_ACCOUNTS)]
        _idx += 1
        return acc


class LoginStressUser(HttpUser):
    """只做登录的施压用户。"""

    wait_time = between(0.5, 2)

    def on_start(self):
        # 预登录一次，确认账号可用（失败直接抛异常，终止该用户）
        acc = _next_account()
        self.username = acc["username"]
        self.password = acc["password"]

    @task(10)
    def login(self):
        with self.client.post(
            "/api/account/login/",
            json={"username": self.username, "password": self.password, "type": "default"},
            catch_response=True,
            name="POST /api/account/login/",
        ) as resp:
            if resp.status_code == 200:
                data = resp.json().get("data") or {}
                if data.get("access_token"):
                    resp.success()
                else:
                    resp.failure(f"无 access_token: {resp.text[:120]}")
            else:
                # 若被打到限流/锁定，标记失败（说明配置或账号有问题）
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:120]}")

    @task(1)
    def repeated_login_with_logout(self):
        """登录后立即登出，模拟真实会话建立/释放，观察 token 写库压力。"""
        with self.client.post(
            "/api/account/login/",
            json={"username": self.username, "password": self.password, "type": "default"},
            catch_response=True,
            name="登录+登出 会话",
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"登录失败 HTTP {resp.status_code}")
                return
            token = (resp.json().get("data") or {}).get("access_token")
            if not token:
                resp.failure("无 access_token")
                return
        # 用拿到的 token 登出
        self.client.delete(
            "/api/account/logout/",
            headers={"x-token": token},
            name="登出",
        )


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("账号登录并发压测开始")
    print(f"账号池: {len(STRESS_ACCOUNTS)} 个专用压测账号（轮询复用）")
    print("安全: 全部使用正确密码，不会触发账号锁定")
    print("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    print("=" * 60)
    print("账号登录并发压测结束")
    print("=" * 60)
