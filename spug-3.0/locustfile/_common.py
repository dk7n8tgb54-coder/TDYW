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


# 每个账号一把锁:序列化「首次登录 / 刷新登录」。
# 否则同一账号的多个并发线程会各自登录,每次登录都让旧 token 立即失效
# (server: User.access_token = uuid4().hex) → 互相把对方的 token 刷掉,形成 401 风暴
# (实测 ~17% 上传请求 401)。锁保证同一账号同一时刻只有一个线程真正登录。
_account_locks = {acc["username"]: threading.Lock() for acc in STRESS_ACCOUNTS}


def _obtain_token(client, username, password, current_token, name):
    """取得账号的有效 token(adopt-or-relogin + 按账号串行登录)。

    Spug 每次登录都会生成新 access_token 并让旧 token 立即失效。
    因此同一账号绝不允许并发登录:N 个并发各登一次会刷掉前 N-1 个 token → 401 风暴。

    本函数保证:同一账号同一时刻只有一个线程真正登录,其余线程在账号锁上等待,
    获锁后若发现别人已登录/刷新则直接 adopt 最新 token,绝不重复登录。
    """
    # 快速路径:池中已有 *比 current_token 新* 的 token → 直接采用
    with _token_pool_lock:
        pool_token = _token_pool.get(username)
        if pool_token is not None and pool_token != current_token:
            return pool_token

    lock = _account_locks.get(username)
    if lock is not None:
        lock.acquire()
    try:
        # 获锁后复查:等待期间可能已有人登录/刷新
        with _token_pool_lock:
            pool_token = _token_pool.get(username)
            if pool_token is not None and pool_token != current_token:
                return pool_token
        # 确实需要登录(首次,或全账号 token 都过期)
        token = _do_login(client, username, password, name)
        with _token_pool_lock:
            _token_pool[username] = token
        return token
    finally:
        if lock is not None:
            lock.release()


def login_shared(client, name="[准备] 登录(共享)"):
    """
    Token 池共享登录:每个账号只登录一次,后续用户复用 token。

    工作流程:
    1. 轮询选一个账号
    2. 如果该账号已有 token,直接采用(不登录)
    3. 如果没有,在账号锁保护下登录一次并存入 token 池,并发用户 adopt

    遇到 401 时调用 self._refresh()(见 TokenSharedHttpUser)刷新。

    Returns:
        (username, token): 账号名和 token,401 时用 username 刷新
    """
    acc = next_account()
    username = acc["username"]
    token = _obtain_token(client, username, acc["password"], None, name)
    return username, token


def refresh_token(client, username, name="[刷新] 重新登录"):
    """
    兼容旧脚本:刷新指定账号的 token(同样走串行登录,杜绝 401 风暴)。
    优先 adopt 池中已有的有效 token,仅在池为空时真正重新登录。
    """
    acc = next((a for a in STRESS_ACCOUNTS if a["username"] == username), None)
    if not acc:
        raise Exception(f"账号 {username} 不在 STRESS_ACCOUNTS 中")
    token = _obtain_token(client, username, acc["password"], None, name)
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
        """刷新当前账号的 token，消除并发刷新导致的 401 风暴。

        关键修复：token 在 _token_pool 中按账号共享。原实现每次 401 都直接重新登录
        （且 _do_login 在锁外执行），而登录会让该账号旧 token 立即失效 ——
        同一账号的多个并发用户会互相把对方的 token 刷掉，形成
        "401 → 刷新 → 别人失效 → 401 → ..." 的死循环（实测 ~17% 上传请求 401）。

        新逻辑：委托 _obtain_token 按账号串行登录 —— 同一时刻仅一个线程真正登录，
        其余线程 adopt 最新 token，从根上消除互相刷掉 token 的竞态。
        """
        acc = next((a for a in STRESS_ACCOUNTS if a["username"] == self.username), None)
        if not acc:
            raise Exception(f"账号 {self.username} 不在 STRESS_ACCOUNTS 中")
        token = _obtain_token(
            self.client, self.username, acc["password"], self.token, "[刷新] 重新登录"
        )
        self.token = token
        return token

    def _do_request(self, method, path, name, max_retries=3, **kwargs):
        """统一请求入口:自动带 token,遇 401 刷新重试(最多 max_retries 次)。

        关键设计(消除刷新间隙 401 风暴 + 避免 LocustError):
        - 中间 401 直接标记为成功(不计失败)并刷新 token 后重试;
        - 仅当所有重试都 401(极端罕见,需连续 3 次 token 被并发刷新覆盖)才把
          最后一次响应交回调用方判定,且保持「未标记」状态,避免
          "response already marked as completed" 异常;
        - 刷新逻辑见 _refresh 的 adopt-or-relogin,消除同账号并发互相刷掉 token。
        """
        files = kwargs.pop('files', None)
        if files is not None:
            kwargs['files'] = files
        base_headers = get_headers_multipart(self.token) if files else get_headers(self.token)
        override = kwargs.pop('headers', None)
        h = dict(base_headers)
        if override:
            h.update(override)

        last_resp = None
        for i in range(max_retries):
            last_resp = self.client.request(
                method, path, headers=h, name=name, catch_response=True, **kwargs
            )
            if last_resp.status_code != 401:
                return last_resp
            if i < max_retries - 1:
                # 中间 401:隐藏(不计失败)+ 刷新 + 重试
                with last_resp:
                    last_resp.success()
                self._refresh()
                h = get_headers_multipart(self.token) if files else get_headers(self.token)
                if override:
                    h.update(override)
            # 最后一轮仍 401:直接返回,交由调用方判定(保持未标记)
        return last_resp

    def _get(self, path, name, params=None, stream=False):
        """GET 请求,401 自动刷新重试(见 _do_request)"""
        return self._do_request('GET', path, name, params=params, stream=stream)

    def _post(self, path, name, json=None, data=None, files=None, headers=None):
        """POST 请求,401 自动刷新重试(见 _do_request)"""
        kwargs = {}
        if json is not None:
            kwargs['json'] = json
        if data is not None:
            kwargs['data'] = data
        if files is not None:
            kwargs['files'] = files
        if headers is not None:
            kwargs['headers'] = headers
        return self._do_request('POST', path, name, **kwargs)

    def _delete(self, path, name, params=None):
        """DELETE 请求,401 自动刷新重试(见 _do_request)"""
        return self._do_request('DELETE', path, name, params=params)

    def _patch(self, path, name, json=None):
        """PATCH 请求,401 自动刷新重试(见 _do_request)"""
        return self._do_request('PATCH', path, name, json=json)

    def _put(self, path, name, json=None):
        """PUT 请求,401 自动刷新重试(见 _do_request)"""
        return self._do_request('PUT', path, name, json=json)
