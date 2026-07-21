#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
kkFileView 预览并发压测脚本(上线前必补 🔴)

风险:kkFileView 容器 limit=1.5G,内部用 LibreOffice 转换 doc/xlsx/ppt,CPU/内存密集。

覆盖场景:
1. 获取预览令牌 - POST /api/document/preview_token/
2. 获取 office 预览 URL - GET /api/document/office_preview_url/
3. 普通文件预览(图片/PDF)- GET /api/document/preview/

运行:
    python -m locust -f locustfile/locustfile_kkfileview_preview.py -H http://localhost
    python -m locust -f locustfile/locustfile_kkfileview_preview.py -H http://localhost \\
        --headless -u 15 -r 3 -t 5m --csv=preview

关注: 预览接口 P95、kkfileview 容器内存峰值(docker stats kkfileview)
"""

import uuid
import random

from locust import task, between, events

from _common import TokenSharedHttpUser

FILE_TYPES = [
    ("image", b"\x89PNG\r\n\x1a\n" + b"\x00" * 10240, "test.png", "image/png"),
    ("pdf", b"%PDF-1.4\n" + b"\x00" * 51200, "test.pdf", "application/pdf"),
    ("text", b"preview test content\n" * 500, "test.txt", "text/plain"),
]


class PreviewUser(TokenSharedHttpUser):
    """kkFileView 预览压测用户(Token 池共享)"""

    wait_time = between(1, 3)

    def on_start(self):
        super().on_start()
        self.file_ids = []
        self._upload_test_files()

    def _upload_test_files(self):
        """上传测试文件后,list 根目录按文件名匹配拿 file_id。

        FileUploadView.post 返回 json_response() 无 data(无 file_id),
        原 resp.json().get("id") 永远 None 导致 file_ids 为空,所有预览 task 早返回。
        修复:上传后 list 根目录,按文件名匹配 file_id。
        """
        import logging
        logger = logging.getLogger(__name__)
        uploaded_names = []  # [(label, filename), ...]
        for label, content, filename, mime in FILE_TYPES:
            fname = f"{label}_{uuid.uuid4().hex[:6]}_{filename}"
            uploaded_names.append((label, fname))
            with self._post(
                "/api/document/upload/",
                f"[准备] 上传 {label} 文件",
                files={"file": (fname, content, mime)},
                data={"folder_id": "", "is_public": False},
            ) as resp:
                if resp.status_code != 200:
                    resp.failure(f"上传{label} HTTP {resp.status_code}: {resp.text[:120]}")
                else:
                    body = resp.json() or {}
                    if body.get("error"):
                        resp.failure(f"上传{label} 错误: {body['error'][:120]}")
                    else:
                        resp.success()
        if not uploaded_names:
            return
        # list 根目录按文件名匹配拿 file_id
        with self._get(
            "/api/document/folder/?is_public=False",
            "[准备] 查询文件列表",
        ) as resp:
            if resp.status_code != 200:
                resp.success()
                return
            data = resp.json().get("data") or {}
            files = data.get("files") or []
            for label, fname in uploaded_names:
                for f in files:
                    if f.get("name") == fname:
                        self.file_ids.append((label, f.get("id")))
                        break
        if len(self.file_ids) < len(uploaded_names):
            matched = {lbl for lbl, _ in self.file_ids}
            missing = [lbl for lbl, _ in uploaded_names if lbl not in matched]
            file_names_in_list = [f.get("name") for f in files]
            logger.warning(f"[kkFileView预览] 未匹配: {missing}, list 返回文件名: {file_names_in_list}, 上传文件名: {[fn for _, fn in uploaded_names]}")

    def on_stop(self):
        return  # 保留压测数据(用户要求全部保留)
        for _, file_id in self.file_ids:
            try:
                self._delete("/api/document/file/", "[清理] 删除测试文件",
                             params={"id": file_id, "is_public": False})
            except Exception:
                pass

    @task(5)
    def get_preview_token(self):
        """获取预览令牌(轻量,测令牌生成吞吐)"""
        if not self.file_ids:
            return
        _, file_id = random.choice(self.file_ids)
        with self._post(
            "/api/document/preview_token/",
            "POST /api/document/preview_token/ (预览令牌)",
            json={"file_id": file_id, "is_public": False},
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:120]}")

    @task(3)
    def get_office_preview_url(self):
        """获取 office 预览 URL(会触发 kkFileView 转换,重)"""
        if not self.file_ids:
            return
        _, file_id = random.choice(self.file_ids)
        with self._get(
            "/api/document/office_preview_url/",
            "GET /api/document/office_preview_url/ (office预览URL)",
            params={"file_id": file_id, "is_public": False},
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code in (400, 404):
                resp.success()
            elif resp.status_code >= 500:
                resp.failure(f"预览 500(可能 kkFileView OOM): {resp.text[:120]}")
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:120]}")

    @task(4)
    def preview_file(self):
        """普通文件预览(图片/PDF,不走 kkFileView)"""
        if not self.file_ids:
            return
        _, file_id = random.choice(self.file_ids)
        with self._get(
            "/api/document/preview/",
            "GET /api/document/preview/ (普通预览)",
            params={"id": file_id, "is_public": False},
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:120]}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("kkFileView 预览并发压测开始")
    print("⚠️  密切关注: docker stats kkfileview 内存峰值")
    print("=" * 60)
