#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
大文件下载并发压测脚本(上线前必补 🔴)

风险:多用户并发下载大文件会占满带宽 + 磁盘 I/O。Gunicorn worker 容易被长连接占满。

覆盖场景:
1. 小文件下载(10KB)- 测吞吐
2. 中文件下载(500KB)- 测平衡
3. 大文件下载(3MB+)- 测带宽 + I/O
4. 文件夹打包下载(GET /api/document/folder/download/)- 测同步打包

运行:
    python -m locust -f locustfile/locustfile_download.py -H http://localhost
    python -m locust -f locustfile/locustfile_download.py -H http://localhost \\
        --headless -u 30 -r 5 -t 5m --csv=download

关注: 下载吞吐量、大文件 P95、Gunicorn worker 占用、磁盘 I/O

【2026-07-20 修复】
1. FolderDownloadView 是 GET 方法(原脚本用 POST → 405)。改用 _get。
2. 后端字段名是 id(原脚本传 folder_id → 参数错误)。改用 id。
3. FileUploadView.post 返回 json_response() 无 file_id(原脚本 resp.json().get("id") 永远 None)。
   改用 list 接口按文件名匹配拿 id。
4. FolderView.post 同样不返回 folder_id,需 list 查找。
5. 删除"404 当成功"的假逻辑,让真实错误暴露(实事求是)。
6. on_start 创建测试文件夹,所有上传文件放进去,打包下载用该文件夹 id。
"""

import uuid
import time
import logging

from locust import task, between, events

from _common import TokenSharedHttpUser, get_headers_multipart

logger = logging.getLogger(__name__)

SMALL_FILE = 10 * 1024
MEDIUM_FILE = 500 * 1024
LARGE_FILE = 3 * 1024 * 1024


class DownloadUser(TokenSharedHttpUser):
    """大文件下载压测用户(Token 池共享)"""

    wait_time = between(0.5, 2)

    def on_start(self):
        super().on_start()
        self.file_ids = []  # [(label, file_id), ...]
        self.test_folder_id = None
        self._create_test_folder()
        self._upload_test_files()

    def _create_test_folder(self):
        """创建测试文件夹(用于文件下载 + 文件夹打包下载测试)"""
        self._folder_name = f"dl_test_folder_{uuid.uuid4().hex[:8]}"
        with self._post(
            "/api/document/folder/",
            "[准备] 创建测试文件夹",
            json={"name": self._folder_name, "parent_id": "", "is_public": False},
        ) as resp:
            if resp.status_code != 200:
                # 创建失败不中断,但后续 task 会因 file_ids 为空而跳过
                resp.success()
                return
        # FolderView.post 返回 json_response() 无 folder_id,需 list 根目录按名匹配
        self.test_folder_id = self._find_folder_id_by_name(self._folder_name)
        if not self.test_folder_id:
            logger.warning("[下载压测] 创建文件夹成功但 list 未匹配到 folder_id")

    def _find_folder_id_by_name(self, name):
        """list 根目录按文件夹名匹配 id"""
        with self._get(
            "/api/document/folder/?is_public=False",
            "[准备] 查询根目录文件夹",
        ) as resp:
            if resp.status_code != 200:
                return None
            data = resp.json().get("data") or {}
            for f in data.get("folders") or []:
                if f.get("name") == name:
                    return f.get("id")
        return None

    def _upload_test_files(self):
        """上传 3 个不同大小的测试文件到测试文件夹,供下载"""
        if not self.test_folder_id:
            logger.warning("[下载压测] 无测试文件夹,上传跳过")
            return
        sizes = [("small", SMALL_FILE), ("medium", MEDIUM_FILE), ("large", LARGE_FILE)]
        uploaded_names = []
        for label, size in sizes:
            file_name = f"dl_test_{label}_{uuid.uuid4().hex[:8]}.txt"
            content = b"x" * size
            uploaded_names.append((label, file_name))
            with self._post(
                "/api/document/upload/",
                f"[准备] 上传 {label} 文件",
                files={"file": (file_name, content, "text/plain")},
                data={"folder_id": self.test_folder_id, "is_public": False},
            ) as resp:
                if resp.status_code != 200:
                    resp.failure(f"上传{label} HTTP {resp.status_code}: {resp.text[:120]}")
                else:
                    body = resp.json() or {}
                    if body.get("error"):
                        resp.failure(f"上传{label} 错误: {body['error'][:120]}")
                    else:
                        resp.success()
        # list 按名匹配 file_id（FileUploadView.post 不返回 id）
        self._match_file_ids(uploaded_names)
        # large 文件(3MB)上传慢可能首次 list 未落库,等 0.5s 重试一次
        if len(self.file_ids) < len(uploaded_names):
            time.sleep(0.5)
            self._match_file_ids(uploaded_names)
        if len(self.file_ids) < len(uploaded_names):
            matched = {lbl for lbl, _ in self.file_ids}
            missing = [lbl for lbl, _ in uploaded_names if lbl not in matched]
            logger.warning(f"[下载压测] 以下文件未匹配到 id,对应下载 task 将跳过: {missing}")

    def _match_file_ids(self, uploaded_names):
        """list 文件夹内容按文件名匹配 id（跳过已匹配的）"""
        with self._get(
            f"/api/document/folder/?id={self.test_folder_id}&is_public=False",
            "[准备] 查询测试文件夹内容",
        ) as resp:
            if resp.status_code != 200:
                return
            data = resp.json().get("data") or {}
            files = data.get("files") or []
            matched_labels = {lbl for lbl, _ in self.file_ids}
            for label, fname in uploaded_names:
                if label in matched_labels:
                    continue
                for f in files:
                    if f.get("name") == fname:
                        self.file_ids.append((label, f.get("id")))
                        break

    def on_stop(self):
        return  # 保留压测数据(用户要求全部保留)
        """清理测试文件 + 测试文件夹"""
        for _, file_id in self.file_ids:
            try:
                self._delete(
                    "/api/document/file/",
                    "[清理] 删除测试文件",
                    params={"id": file_id, "is_public": False},
                )
            except Exception:
                pass
        if self.test_folder_id:
            try:
                self._delete(
                    "/api/document/folder/",
                    "[清理] 删除测试文件夹",
                    params={"id": self.test_folder_id, "is_public": False},
                )
            except Exception:
                pass

    @task(4)
    def download_small_file(self):
        self._download_file("small")

    @task(3)
    def download_medium_file(self):
        self._download_file("medium")

    @task(2)
    def download_large_file(self):
        self._download_file("large")

    def _download_file(self, label):
        """下载指定标签的文件"""
        file_id = next((fid for lbl, fid in self.file_ids if lbl == label), None)
        if not file_id:
            return
        with self._get(
            "/api/document/download/",
            f"GET /api/document/download/ ({label})",
            params={"id": file_id, "is_public": False},
            stream=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:120]}")

    @task(1)
    def download_folder_zip(self):
        """文件夹打包下载(GET 同步模式,小文件夹 <100 文件)"""
        if not self.test_folder_id:
            return
        # FolderDownloadView 是 GET 方法,参数从 query string 取(id 必填 int)
        with self._get(
            "/api/document/folder/download/",
            "GET /api/document/folder/download/ (发起打包)",
            params={"id": self.test_folder_id, "is_public": False},
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 500:
                resp.failure(f"打包 500(可能 OOM): {resp.text[:120]}")
            else:
                # 不再假成功:403/404/405 等都是真实错误,应暴露
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:120]}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("大文件下载并发压测开始")
    print("⚠️  关注: 带宽、磁盘 I/O、Gunicorn worker 占用")
    print("=" * 60)
