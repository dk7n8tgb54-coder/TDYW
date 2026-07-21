#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
小文件批量上传高峰压测脚本(上线后可补 🟡)

风险:用户拖拽几千个小文件(10KB)批量上传,前端 3 并发文件持续提交。
几千个文件会产生大量 DB 写入(File 记录)+ 磁盘小文件落盘 + Gunicorn worker 争用。

覆盖场景:
1. 几千个 10KB 小文件持续上传(模拟 3 账号 × 3 并发文件 = 9 并发)
2. 私密/公共空间各一半用户
3. 文件夹层级 3 层(root/sub/leaf),文件上传到 leaf

运行:
    python -m locust -f locustfile/locustfile_bulk_upload.py -H http://localhost
    python -m locust -f locustfile/locustfile_bulk_upload.py -H http://localhost \\
        --headless -u 9 -r 3 -t 5m --csv=bulk_upload

关注: 上传 QPS、P95、失败率、Gunicorn worker 占用、磁盘 I/O、DB 连接数

数据保留:
    默认 on_stop 递归删除测试文件夹。如需保留数据查看,设环境变量:
        KEEP_TEST_DATA=1 python -m locust -f locustfile/locustfile_bulk_upload.py ...

设计说明:
- token 池模式: 5 账号登录一次, N 用户复用 token, 不触发登录限流
- on_start 创建 3 层测试文件夹(root/sub/leaf), 所有上传到 leaf, on_stop 递归删 root
- wait_time between(0.1, 0.3): 模拟前端持续上传不停顿(非用户慢速操作)
"""

import os
import uuid
import logging

from locust import task, between, events

from _common import TokenSharedHttpUser, KEEP_TEST_DATA

logger = logging.getLogger(__name__)

SMALL_FILE_SIZE = 10 * 1024  # 10KB
FOLDER_DEPTH = 10  # 文件夹嵌套深度


class BaseBulkUploadUser(TokenSharedHttpUser):
    """小文件批量上传高峰用户基类(私密/公共共用逻辑)"""

    abstract = True
    is_public = False  # 子类覆盖
    _folder_prefix = "bulk"  # 文件夹命名前缀

    wait_time = between(0.1, 0.3)

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
        """创建 FOLDER_DEPTH 层嵌套文件夹,上传目标为最深层。"""
        prefix = uuid.uuid4().hex[:8]
        parent_id = None
        for i in range(FOLDER_DEPTH):
            name = f"{self._folder_prefix}_L{i}_{prefix}"
            fid = self._create_folder_and_get_id(name, parent_id=parent_id, label=f"[准备] L{i}")
            if not fid:
                logger.warning(f"[批量上传] 创建 L{i} 文件夹失败,已建 {i} 层")
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
                logger.warning("[批量上传] 文件夹删除失败,可能需要手动清理")

    # ---------- 小文件上传 ----------
    @task
    def upload_small_file(self):
        """持续上传 10KB 小文件(不分片)到 leaf 层"""
        if not self.leaf_folder_id:
            return
        file_name = f"bulk_{uuid.uuid4().hex[:8]}.txt"
        content = b"x" * SMALL_FILE_SIZE
        with self._post(
            "/api/document/upload/",
            f"POST /api/document/upload/ ({'公共' if self.is_public else '私密'}批量小文件)",
            files={"file": (file_name, content, "text/plain")},
            data={"folder_id": self.leaf_folder_id,
                  "is_public": str(self.is_public).lower()},
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:80]}")


class PublicBulkUploadUser(BaseBulkUploadUser):
    """公共空间小文件批量上传用户"""
    is_public = True


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("小文件批量上传高峰压测开始")
    print("  私密/公共空间各一半用户,文件夹 3 层深度")
    print("  会产生大量小文件(10KB),关注磁盘 I/O + DB 写入")
    if KEEP_TEST_DATA:
        print("  [KEEP_TEST_DATA=1] 压测数据将保留(不自动清理)")
    print("=" * 60)
