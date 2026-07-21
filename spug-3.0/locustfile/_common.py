#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
locustfile 共用工具模块

提供登录、请求头、账号轮询、Token 池等通用功能,供所有压测脚本复用。

核心设计:Token 池共享
  Spug 每次登录会刷新 access_token,旧 token 立即失效。
  如果 50 个并发用户各自登录,同一账号的 token 会互相覆盖 → 401 风暴。
  解决:每个账号只登录一次,token 全局共享,所有用户复用。
  遇到 401 时调用 refresh_token() 刷新该账号的 token。

使用方式:
    from _common import login_shared, get_headers, refresh_token, DEFAULT_ACCOUNTS
"""

import os
import json
import threading

# 数据保留开关：默认保留压测数据("1")，设 KEEP_TEST_DATA=0 时 on_stop 自动清理
KEEP_TEST_DATA = os.environ.get("KEEP_TEST_DATA", "1") == "1"

# 5 个专用压测账号(已通过 tools/create_stress_accounts.py 在 tdyw 库创建)
# 租户隔离标识: stress,密码统一 Stress@2026
DEFAULT_ACCOUNTS = [
    {"username": "st_press_01", "password": "Stress@2026"},
    {"username": "st_press_02", "password": "Stress@2026"},
    {"username": "st_press_03", "password": "Stress@2026"},
    {"username": "st_press_04", "password": "Stress@2026"},
    {"username": "st_press_05", "password": "Stress@2026"},
]

_account_lock = threading.Lock()
_account_index = 0

# Token 池: {username: token}  全局共享,每个账号只登录一次
_token_pool = {}
_token_pool_lock = threading.Lock()


def load_accounts():
    """从环境变量 STRESS_ACCOUNTS 加载账号(JSON 数组),否则用默认账号"""
    raw = os.environ.get("STRESS_ACCOUNTS")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list) and data:
                return data
        except (ValueError, TypeError):
            pass
    return DEFAULT_ACCOUNTS


STRESS_ACCOUNTS = load_accounts()


def next_account():
    """线程安全地轮询返回下一个账号"""
    global _account_index
    with _account_lock:
        acc = STRESS_ACCOUNTS[_account_index % len(STRESS_ACCOUNTS)]
        _account_index += 1
        return acc


def _do_login(client, username, password, name="[准备] 登录"):
    """实际执行登录 HTTP 请求,返回 token。失败抛异常。"""
    with client.post(
        "/api/account/login/",
        json={"username": username, "password": password, "type": "default"},
        catch_response=True,
        name=name,
    ) as resp:
        if resp.status_code != 200:
            resp.failure(f"HTTP {resp.status_code}: {resp.text[:120]}")
            raise Exception(f"登录失败 HTTP {resp.status_code}")
        data = resp.json()
        if data.get("error"):
            resp.failure(f"登录错误: {data['error']}")
            raise Exception(f"登录错误: {data['error']}")
        token = (data.get("data") or {}).get("access_token")
        if not token:
            resp.failure("响应无 access_token")
            raise Exception("响应无 access_token")
        resp.success()
        return token


def login(client, username=None, password=None, name="[准备] 登录"):
    """
    直接登录(每次都发登录请求)。仅用于 account_login_stress 等专门测登录的脚本。
    普通压测脚本请用 login_shared()。
    """
    if username is None:
        acc = next_account()
        username = acc["username"]
        password = acc["password"]
    return _do_login(client, username, password, name)


def login_shared(client, name="[准备] 登录(共享)"):
    """
    Token 池共享登录:每个账号只登录一次,后续用户复用 token。

    工作流程:
    1. 轮询选一个账号
    2. 如果该账号已有 token,直接返回(不登录)
    3. 如果没有,登录并存入 token 池

    遇到 401 时调用 refresh_token(client, username) 刷新。

    Returns:
        (username, token): 账号名和 token,401 时用 username 刷新
    """
    acc = next_account()
    username = acc["username"]
    password = acc["password"]

    with _token_pool_lock:
        if username in _token_pool:
            return username, _token_pool[username]

    # 首次登录
    token = _do_login(client, username, password, name)
    with _token_pool_lock:
        _token_pool[username] = token
    return username, token


def refresh_token(client, username, name="[刷新] 重新登录"):
    """
    401 时刷新指定账号的 token。
    清除旧 token,重新登录,存入新 token。
    """
    acc = next((a for a in STRESS_ACCOUNTS if a["username"] == username), None)
    if not acc:
        raise Exception(f"账号 {username} 不在 STRESS_ACCOUNTS 中")

    with _token_pool_lock:
        _token_pool.pop(username, None)

    token = _do_login(client, username, acc["password"], name)
    with _token_pool_lock:
        _token_pool[username] = token
    return token


def get_headers(token):
    """构造带认证的请求头"""
    return {
        "Content-Type": "application/json",
        "X-Token": token,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
    }


def get_headers_multipart(token):
    """构造文件上传用的请求头(不带 Content-Type,locust 自动设 boundary)"""
    return {
        "X-Token": token,
        "X-Requested-With": "XMLHttpRequest",
    }


# =============================================================================
# Token 共享 HttpUser 基类
# 所有新压测脚本继承此类,自动处理 token 池共享 + 401 刷新
# =============================================================================

from locust import HttpUser


class TokenSharedHttpUser(HttpUser):
    """
    Token 池共享的 HttpUser 基类。

    用法(新脚本只需继承,不用写 on_start):
        class MyUser(TokenSharedHttpUser):
            @task
            def my_task(self):
                with self._get("/api/xxx/", "GET /api/xxx/") as resp:
                    if resp.status_code == 200:
                        resp.success()

    提供 _get / _post / _delete 辅助方法,自动处理 401 刷新。
    """

    abstract = True  # 基类不实例化

    def on_start(self):
        self.username, self.token = login_shared(self.client)

    def _refresh(self):
        """刷新当前账号的 token"""
        self.token = refresh_token(self.client, self.username)

    def _get(self, path, name, params=None, stream=False):
        """GET 请求,401 自动刷新重试

        注意:locust 的 catch_response=True 模式下,Response 对象必须在 with 块内
        调用 success/failure,否则抛 LocustError。原代码直接 `resp.success()`
        在 401 时会中断 task 队列(mixed_workload 的 relogin 触发此 bug)。
        修复:用 with 块包裹原 401 resp 调用 success,然后重试。
        """
        resp = self.client.get(path, params=params, headers=get_headers(self.token),
                               name=name, catch_response=True, stream=stream)
        if resp.status_code == 401:
            with resp:
                resp.success()  # 标记 401 为成功(不计失败),with 块退出时不再自动判断
            self._refresh()
            resp = self.client.get(path, params=params, headers=get_headers(self.token),
                                   name=name, catch_response=True, stream=stream)
        return resp

    def _post(self, path, name, json=None, data=None, files=None, headers=None):
        """POST 请求,401 自动刷新重试(同 _get 的 with 块修复)"""
        h = headers or (get_headers_multipart(self.token) if files else get_headers(self.token))
        resp = self.client.post(path, json=json, data=data, files=files, headers=h,
                                name=name, catch_response=True)
        if resp.status_code == 401:
            with resp:
                resp.success()
            self._refresh()
            h = headers or (get_headers_multipart(self.token) if files else get_headers(self.token))
            resp = self.client.post(path, json=json, data=data, files=files, headers=h,
                                    name=name, catch_response=True)
        return resp

    def _delete(self, path, name, params=None):
        """DELETE 请求,401 自动刷新重试(同 _get 的 with 块修复)"""
        resp = self.client.delete(path, params=params, headers=get_headers(self.token),
                                  name=name, catch_response=True)
        if resp.status_code == 401:
            with resp:
                resp.success()
            self._refresh()
            resp = self.client.delete(path, params=params, headers=get_headers(self.token),
                                      name=name, catch_response=True)
        return resp

    def _patch(self, path, name, json=None):
        """PATCH 请求,401 自动刷新重试(同 _get 的 with 块修复)"""
        resp = self.client.patch(path, json=json, headers=get_headers(self.token),
                                 name=name, catch_response=True)
        if resp.status_code == 401:
            with resp:
                resp.success()
            self._refresh()
            resp = self.client.patch(path, json=json, headers=get_headers(self.token),
                                     name=name, catch_response=True)
        return resp

    def _put(self, path, name, json=None):
        """PUT 请求,401 自动刷新重试(同 _get 的 with 块修复)"""
        resp = self.client.put(path, json=json, headers=get_headers(self.token),
                               name=name, catch_response=True)
        if resp.status_code == 401:
            with resp:
                resp.success()
            self._refresh()
            resp = self.client.put(path, json=json, headers=get_headers(self.token),
                                   name=name, catch_response=True)
        return resp
