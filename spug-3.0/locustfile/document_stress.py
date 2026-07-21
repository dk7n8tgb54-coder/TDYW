#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
资料库（Document）模块压力测试脚本 —— 当前可用版本

对齐 2026-06 后的真实接口（回收站已移除，分片上传走 file_hash 隔离目录）。
覆盖场景：文件夹 CRUD、普通上传、分片上传+合并（含断点续传）、传输列表、
磁盘使用、DB 连接池健康。

【关键修正 vs 旧脚本】
1. 移除全部 /recycle-bin/* 任务（接口已于 2026-06-23 删除，旧脚本一跑全 404）。
2. 普通上传字段由错误的 `parent_id` 改为 `folder_id`（与 FileUploadView 一致）。
3. 分片合并字段由 `parent_id` 改为 `folder_id`（与 merge 视图 validate_merge_params 一致）。
4. 分片上传不传 `transfer_id`，避免视图 int() 解析失败；分片目录按 file_hash+user 隔离。
5. 数据清理：每个虚拟用户只建一个“根文件夹”，所有操作都在其下进行；
   on_stop 直接删除根文件夹（递归硬删子文件夹+文件+DB 记录），可覆盖合并产物。

运行方式（必须用 -f 指定本文件，且打生产容器 tdyw 的 80 端口）：
    python -m locust -f locustfile/document_stress.py -H http://localhost
    # 命令行模式
    python -m locust -f locustfile/document_stress.py -H http://localhost \
        --headless -u 50 -r 10 -t 10m --csv=document_stress

账号：见 README，使用专用压测账号（create_stress_accounts.py 创建）。
"""

import os
import io
import uuid
import random
import hashlib
import threading
from datetime import datetime

from locust import HttpUser, task, between, events
from locust.runners import MasterRunner

# ===================== 配置 =====================
# 5 个专用压测账号(与 _common.py / create_stress_accounts.py 一致)
STRESS_ACCOUNTS = [
    {"username": "st_press_01", "password": "Stress@2026"},
    {"username": "st_press_02", "password": "Stress@2026"},
    {"username": "st_press_03", "password": "Stress@2026"},
    {"username": "st_press_04", "password": "Stress@2026"},
    {"username": "st_press_05", "password": "Stress@2026"},
]

# 文件大小（字节）
SMALL_FILE = 10 * 1024            # 10KB
CHUNK_SIZE = 1024 * 1024          # 1MB
LARGE_FILE = 3 * CHUNK_SIZE       # 3MB -> 3 个分片

_account_lock = threading.Lock()
_account_index = 0

# Token 池:每个账号只登录一次,后续用户复用(避免 token 互相覆盖)
_token_pool = {}
_token_pool_lock = threading.Lock()


def _next_account():
    global _account_index
    with _account_lock:
        acc = STRESS_ACCOUNTS[_account_index % len(STRESS_ACCOUNTS)]
        _account_index += 1
        return acc


def _pool_login(client):
    """Token 池登录:已有 token 直接复用,没有才登录"""
    acc = _next_account()
    username = acc["username"]
    with _token_pool_lock:
        if username in _token_pool:
            return username, _token_pool[username]
    resp = client.post(
        "/api/account/login/",
        json={"username": username, "password": acc["password"], "type": "default"},
        name="[准备] 登录",
    )
    if resp.status_code != 200:
        raise Exception(f"登录失败 {username}: {resp.status_code} {resp.text[:120]}")
    token = (resp.json().get("data") or {}).get("access_token")
    if not token:
        raise Exception(f"登录响应缺少 access_token: {resp.text[:120]}")
    with _token_pool_lock:
        _token_pool[username] = token
    return username, token


def _pool_refresh(client, username):
    """401 时刷新指定账号的 token"""
    acc = next((a for a in STRESS_ACCOUNTS if a["username"] == username), None)
    if not acc:
        return None
    with _token_pool_lock:
        _token_pool.pop(username, None)
    resp = client.post(
        "/api/account/login/",
        json={"username": username, "password": acc["password"], "type": "default"},
        name="[刷新] 重新登录",
    )
    if resp.status_code == 200:
        token = (resp.json().get("data") or {}).get("access_token")
        if token:
            with _token_pool_lock:
                _token_pool[username] = token
            return token
    return None


# ===================== 基础用户类 =====================
class BaseDocumentUser(HttpUser):
    """抽象基类：登录、令牌、根文件夹创建与清理。"""

    abstract = True
    wait_time = between(1, 3)

    def on_start(self):
        self.root_folder_id = None
        self.login()
        self.ensure_root_folder()

    def on_stop(self):
        return  # 保留压测数据(用户要求全部保留)
        # 收尾清理：删除根文件夹（递归硬删其下所有文件/子文件夹）
        if getattr(self, "root_folder_id", None):
            try:
                self.client.delete(
                    f"/api/document/folder/?id={self.root_folder_id}&is_public={str(self.is_public).lower()}",
                    name="[清理] 删除根文件夹(级联)",
                )
            except Exception:
                pass
        # 不做登出(避免覆盖 token 池里的 token)

    # ---------- 登录 ----------
    def login(self):
        self.username, self.token = _pool_login(self.client)
        self.client.headers.update({"x-token": self.token})

    def _refresh_if_401(self, resp):
        """401 时刷新 token 并重试(返回新 response)"""
        if resp.status_code != 401:
            return resp
        new_token = _pool_refresh(self.client, self.username)
        if new_token:
            self.token = new_token
            self.client.headers.update({"x-token": self.token})
        return resp

    # ---------- 根文件夹 ----------
    def ensure_root_folder(self):
        name = f"stress_root_{uuid.uuid4().hex[:10]}"
        resp = self.client.post(
            "/api/document/folder/",
            json={"name": name, "parent_id": None, "is_public": self.is_public},
            name="[准备] 创建根文件夹",
        )
        if resp.status_code == 200:
            self.root_folder_id = (resp.json().get("data") or {}).get("id")

    # ---------- 辅助 ----------
    def gen_bytes(self, size):
        return os.urandom(size)

    def md5(self, content):
        return hashlib.md5(content).hexdigest()

    def list_root(self):
        """列出根文件夹内容，返回 (folder_ids, file_ids)"""
        if not self.root_folder_id:
            return [], []
        resp = self.client.get(
            f"/api/document/folder/?id={self.root_folder_id}&is_public={str(self.is_public).lower()}",
            name="[查询] 根文件夹内容",
        )
        if resp.status_code != 200:
            return [], []
        data = resp.json().get("data") or {}
        folders = [f["id"] for f in data.get("folders", [])]
        files = [f["id"] for f in data.get("files", [])]
        return folders, files

    # ============ 普通上传 ============
    def normal_upload(self, size=SMALL_FILE, parent_id=None):
        parent = parent_id if parent_id else self.root_folder_id
        name = f"normal_{uuid.uuid4().hex[:8]}.bin"
        content = self.gen_bytes(size)
        resp = self.client.post(
            "/api/document/upload/",
            data={"folder_id": parent, "is_public": str(self.is_public).lower()},
            files={"file": (name, content, "application/octet-stream")},
            name="[上传] 普通文件上传",
        )
        # 普通上传不返回 file id，清理靠根文件夹级联删除
        return resp.status_code == 200

    # ============ 分片上传 + 合并（完整） ============
    def chunked_upload(self, size=LARGE_FILE, parent_id=None, skip_last=False,
                       resume=False):
        """
        分片上传并合并。
        skip_last: True 时故意不上传最后一个分片（用于测试分片缺失）。
        resume: True 时先传前 N-1 片，再传剩余（断点续传）。
        """
        parent = parent_id if parent_id else self.root_folder_id
        name = f"chunk_{uuid.uuid4().hex[:8]}.bin"
        content = self.gen_bytes(size)
        file_hash = self.md5(content)
        total = (size + CHUNK_SIZE - 1) // CHUNK_SIZE

        def upload_one(idx):
            start = idx * CHUNK_SIZE
            end = min(start + CHUNK_SIZE, size)
            part = content[start:end]
            resp = self.client.post(
                "/api/document/upload_chunk/",
                data={
                    "file_name": name,
                    "file_size": size,
                    "chunk_index": idx,
                    "total_chunks": total,
                    "file_hash": file_hash,
                    "folder_id": parent,
                    "is_public": str(self.is_public).lower(),
                },
                files={"file": (f"{name}.part{idx}", part, "application/octet-stream")},
                name=f"[分片] 上传分片 {idx + 1}/{total}",
            )
            return resp.status_code == 200

        if resume:
            # 第一轮：传前 total-1 片
            for i in range(total - 1):
                if not upload_one(i):
                    return False
            # 第二轮：续传剩余
            if not upload_one(total - 1):
                return False
        else:
            for i in range(total):
                if skip_last and i == total - 1:
                    continue
                if not upload_one(i):
                    return False

        if skip_last:
            return True  # 故意不合并

        # 合并（异步 Celery，返回 task_id，不返回 file id）
        resp = self.client.post(
            "/api/document/merge_chunks/",
            json={
                "file_name": name,
                "file_size": size,
                "total_chunks": total,
                "file_hash": file_hash,
                "folder_id": parent,
                "is_public": self.is_public,
            },
            name="[合并] 提交合并任务",
        )
        return resp.status_code == 200


# ===================== 私有空间用户 =====================
class PrivateSpaceUser(BaseDocumentUser):
    is_public = False

    @task(3)
    def create_folder(self):
        name = f"pf_{uuid.uuid4().hex[:8]}"
        resp = self.client.post(
            "/api/document/folder/",
            json={"name": name, "parent_id": self.root_folder_id, "is_public": False},
            name="[私有] 创建子文件夹",
        )
        # 创建失败不追踪（幂等/重名），清理靠根目录级联

    @task(6)
    def list_folders(self):
        self.client.get(
            f"/api/document/folder/?id={self.root_folder_id}&is_public=False",
            name="[私有] 查询文件夹",
        )

    @task(4)
    def upload_file(self):
        self.normal_upload(SMALL_FILE)

    @task(2)
    def delete_one_file(self):
        _, file_ids = self.list_root()
        if file_ids:
            fid = random.choice(file_ids)
            self.client.delete(
                f"/api/document/file/?id={fid}&is_public=False",
                name="[私有] 删除文件",
            )

    @task(3)
    def chunked_upload_task(self):
        self.chunked_upload(LARGE_FILE)

    @task(1)
    def resumable_upload_task(self):
        self.chunked_upload(LARGE_FILE, resume=True)

    @task(5)
    def get_transfers(self):
        self.client.get("/api/document/transfers/?is_public=False", name="[私有] 传输列表")

    @task(3)
    def get_disk_usage(self):
        self.client.get("/api/document/disk_usage/?is_public=False", name="[私有] 磁盘使用")

    @task(2)
    def health_db_pool(self):
        self.client.get("/api/document/health/db-pool/", name="[私有] DB连接池")


# ===================== 公共空间用户 =====================
class PublicSpaceUser(BaseDocumentUser):
    is_public = True

    @task(3)
    def create_folder(self):
        name = f"pubf_{uuid.uuid4().hex[:8]}"
        resp = self.client.post(
            "/api/document/folder/",
            json={"name": name, "parent_id": self.root_folder_id, "is_public": True},
            name="[公共] 创建子文件夹",
        )

    @task(6)
    def list_folders(self):
        self.client.get(
            f"/api/document/folder/?id={self.root_folder_id}&is_public=True",
            name="[公共] 查询文件夹",
        )

    @task(4)
    def upload_file(self):
        self.normal_upload(SMALL_FILE)

    @task(2)
    def delete_one_file(self):
        _, file_ids = self.list_root()
        if file_ids:
            fid = random.choice(file_ids)
            self.client.delete(
                f"/api/document/file/?id={fid}&is_public=True",
                name="[公共] 删除文件",
            )

    @task(3)
    def chunked_upload_task(self):
        self.chunked_upload(LARGE_FILE)

    @task(1)
    def resumable_upload_task(self):
        self.chunked_upload(LARGE_FILE, resume=True)

    @task(5)
    def get_transfers(self):
        self.client.get("/api/document/transfers/?is_public=True", name="[公共] 传输列表")

    @task(3)
    def get_disk_usage(self):
        self.client.get("/api/document/disk_usage/?is_public=True", name="[公共] 磁盘使用")

    @task(2)
    def health_db_pool(self):
        self.client.get("/api/document/health/db-pool/", name="[公共] DB连接池")


# ===================== 测试生命周期事件 =====================
@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("资料库压力测试开始")
    print("目标: 私有/公共空间 CRUD + 分片上传 + 传输/磁盘")
    print("注意: 必须打生产容器 tdyw(80 端口)，并使用专用压测账号")
    print("=" * 60)
    if isinstance(environment.runner, MasterRunner):
        print("[主节点] 分布式模式")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    print("=" * 60)
    print("资料库压力测试结束")
    print("清理: 各虚拟用户 on_stop 已级联删除根文件夹")
    print("残留分片目录请参考 README 手动清理")
    print("=" * 60)
