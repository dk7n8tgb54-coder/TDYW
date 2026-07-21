#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Celery 队列积压压测脚本(上线后可补 🟡)

风险:分片上传完成 → merge 任务进队列;用户打包文件夹 → pack 任务进队列。
高峰期队列堆积会导致 merge 任务超时(15min 硬超时)、pack zip 堆积磁盘。

覆盖场景:
1. 高频分片上传(产生 merge 任务)—— 私密/公共空间各一半用户
2. 高频文件夹打包(产生 pack 任务)—— 私密/公共空间各一半用户
3. 文件夹层级 3 层(root/sub/leaf),分片上传到 leaf,打包 root

运行:
    python -m locust -f locustfile/locustfile_celery_queue.py -H http://localhost
    python -m locust -f locustfile/locustfile_celery_queue.py -H http://localhost \\
        --headless -u 20 -r 5 -t 10m --csv=celery_queue

监控: celery inspect active / docker stats tdyw / 磁盘增长

数据保留:
    默认 on_stop 递归删除测试文件夹。如需保留数据查看,设环境变量:
        KEEP_TEST_DATA=1 python -m locust -f locustfile/locustfile_celery_queue.py ...
"""

import os
import uuid
import hashlib

from locust import task, between, events

from _common import TokenSharedHttpUser, KEEP_TEST_DATA

CHUNK_SIZE = 1024 * 1024
LARGE_FILE = 3 * CHUNK_SIZE

FOLDER_DEPTH = 10  # 文件夹嵌套深度


class BaseCeleryQueueUser(TokenSharedHttpUser):
    """Celery 队列积压压测用户基类(私密/公共共用逻辑)"""

    abstract = True
    is_public = False  # 子类覆盖
    _folder_prefix = "celery"  # 文件夹命名前缀

    wait_time = between(0.1, 0.3)  # 模拟批量上传持续不停顿

    def on_start(self):
        super().on_start()
        self.root_folder_id = None
        self.leaf_folder_id = None
        self._create_test_folders()

    # ---------- 文件夹创建(3 层: root/sub/leaf) ----------
    def _create_folder_and_get_id(self, name, parent_id=None, label="[准备]"):
        """创建文件夹并返回 id。优先用响应 id,失败则 list 按名匹配兜底。"""
        body = {"name": name, "is_public": self.is_public}
        if parent_id:
            body["parent_id"] = parent_id
        with self._post(
            "/api/document/folder/",
            f"{label} 创建文件夹 {name}",
            json=body,
        ) as resp:
            if resp.status_code == 200:
                data = (resp.json() or {}).get("data") or {}
                fid = data.get("id")
                if fid:
                    return fid
        # 兜底: list 按名匹配
        return self._find_folder_id_by_name(name, parent_id)

    def _find_folder_id_by_name(self, name, parent_id=None):
        params = {"is_public": str(self.is_public).lower()}
        if parent_id:
            params["id"] = parent_id
        with self._get(
            "/api/document/folder/",
            f"[准备] 查询文件夹 {name}",
            params=params,
        ) as resp:
            if resp.status_code != 200:
                return None
            data = (resp.json() or {}).get("data") or {}
            for f in data.get("folders") or []:
                if f.get("name") == name:
                    return f.get("id")
        return None

    def _create_test_folders(self):
        """创建 FOLDER_DEPTH 层嵌套文件夹,分片上传目标为最深层。"""
        prefix = uuid.uuid4().hex[:6]
        parent_id = None
        for i in range(FOLDER_DEPTH):
            name = f"{self._folder_prefix}_L{i}_{prefix}"
            fid = self._create_folder_and_get_id(name, parent_id=parent_id, label=f"[准备] L{i}")
            if not fid:
                break
            if i == 0:
                self.root_folder_id = fid
            parent_id = fid
        self.leaf_folder_id = parent_id

    # ---------- 清理 ----------
    def on_stop(self):
        if KEEP_TEST_DATA:
            return
        if self.root_folder_id:
            try:
                self._delete(
                    "/api/document/folder/",
                    "[清理] 删除根文件夹(级联)",
                    params={"id": self.root_folder_id,
                            "is_public": str(self.is_public).lower()},
                )
            except Exception:
                pass

    # ---------- 分片上传 + 合并 ----------
    @task(5)
    def upload_chunked_file_trigger_merge(self):
        """分片上传 + 合并(产生 merge Celery 任务),上传到 leaf 层"""
        if not self.leaf_folder_id:
            return
        file_content = b"x" * LARGE_FILE
        file_hash = hashlib.md5(file_content).hexdigest()
        file_name = f"celery_merge_{uuid.uuid4().hex[:8]}.txt"
        total_chunks = (LARGE_FILE + CHUNK_SIZE - 1) // CHUNK_SIZE
        uploaded = []

        for idx in range(total_chunks):
            start = idx * CHUNK_SIZE
            end = min(start + CHUNK_SIZE, len(file_content))
            chunk = file_content[start:end]
            with self._post(
                "/api/document/upload_chunk/",
                f"POST /api/document/upload_chunk/ ({'公共' if self.is_public else '私密'}分片{idx+1}/{total_chunks})",
                files={"file": (f"{file_name}.part{idx}", chunk, "application/octet-stream")},
                data={"file_name": file_name, "file_size": LARGE_FILE,
                      "chunk_index": idx, "total_chunks": total_chunks,
                      "file_hash": file_hash, "folder_id": self.leaf_folder_id,
                      "is_public": str(self.is_public).lower()},
            ) as resp:
                if resp.status_code == 200:
                    uploaded.append(idx)
                else:
                    resp.failure(f"分片上传失败: {resp.text[:80]}")
                    return

        if len(uploaded) == total_chunks:
            with self._post(
                "/api/document/merge_chunks/",
                f"POST /api/document/merge_chunks/ ({'公共' if self.is_public else '私密'}触发merge)",
                json={"file_name": file_name, "file_size": LARGE_FILE,
                      "total_chunks": total_chunks, "file_hash": file_hash,
                      "folder_id": self.leaf_folder_id, "is_public": self.is_public},
            ) as resp:
                if resp.status_code == 200:
                    resp.success()
                else:
                    resp.failure(f"合并失败: {resp.text[:80]}")

    # ---------- 文件夹打包 ----------
    @task(3)
    def trigger_folder_pack(self):
        """打包 root 文件夹(含 3 层子树 + 已上传文件),产生 pack 任务"""
        if not self.root_folder_id:
            return
        # FolderDownloadView 是 GET,字段名是 id
        with self._get("/api/document/folder/download/",
                       f"GET /api/document/folder/download/ ({'公共' if self.is_public else '私密'}触发pack)",
                       params={"id": self.root_folder_id,
                               "is_public": str(self.is_public).lower()}) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                # 403/404/405 都是真实错误,应暴露
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:80]}")


class PrivateCeleryQueueUser(BaseCeleryQueueUser):
    """私密空间 Celery 队列积压用户"""
    is_public = False


class PublicCeleryQueueUser(BaseCeleryQueueUser):
    """公共空间 Celery 队列积压用户"""
    is_public = True


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("Celery 队列积压压测开始")
    print("  私密/公共空间各一半用户,文件夹 3 层深度")
    print("  会产生大量 merge + pack 任务")
    print("  监控: celery inspect active / docker stats tdyw")
    if KEEP_TEST_DATA:
        print("  [KEEP_TEST_DATA=1] 压测数据将保留(不自动清理)")
    print("=" * 60)
