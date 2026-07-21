#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
长时间稳定性压测脚本(Soak Test,上线后可补 🟡)

风险:短时压测看不出内存泄漏、连接泄漏、日志膨胀、磁盘增长。
Soak test 持续 8h+,暴露内存/连接/磁盘/文件描述符泄漏。

运行(注意 -t 至少 8h):
    python -m locust -f locustfile/locustfile_soak_test.py -H http://localhost \\
        --headless -u 20 -r 2 -t 8h --csv=soak_test

关注(8h 后对比基线): 内存增长>200MB / DB连接增长>50 / P95退化>2倍 → 疑似泄漏
"""

import uuid

from locust import task, between, events

from _common import TokenSharedHttpUser


class SoakTestUser(TokenSharedHttpUser):
    """长时间稳定性压测用户(轻量混合负载)"""

    wait_time = between(2, 5)

    def on_start(self):
        super().on_start()
        self.file_ids = []

    def on_stop(self):
        return  # 保留压测数据(用户要求全部保留)
        for file_id in self.file_ids[-20:]:
            try:
                self._delete("/api/document/file/", "[清理]",
                             params={"id": file_id, "is_public": False})
            except Exception:
                pass

    @task(8)
    def list_folders(self):
        with self._get("/api/document/folder/?is_public=False",
                       "GET /api/document/folder/ (Soak-文件夹列表)") as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @task(5)
    def list_audit_log(self):
        with self._get("/api/logs/audit/",
                       "GET /api/logs/audit/ (Soak-审计日志)",
                       params={"page": 1, "page_size": 20}) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @task(3)
    def upload_small_file(self):
        file_name = f"soak_{uuid.uuid4().hex[:8]}.txt"
        content = b"soak test " * 100
        with self._post("/api/document/upload/",
                        "POST /api/document/upload/ (Soak-上传)",
                        files={"file": (file_name, content, "text/plain")},
                        data={"folder_id": "", "is_public": False}) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
                return
        # FileUploadView.post 返回 json_response() 无 id,需 list 根目录按名匹配拿 file_id
        with self._get("/api/document/folder/?is_public=False",
                       "[Soak] 查询文件列表拿 file_id",
                       params={"page_size": 50}) as resp:
            if resp.status_code == 200:
                data = resp.json().get("data") or {}
                for f in data.get("files") or []:
                    if f.get("name") == file_name:
                        self.file_ids.append(f.get("id"))
                        break

    @task(2)
    def delete_old_file(self):
        if len(self.file_ids) < 10:
            return
        file_id = self.file_ids.pop(0)
        with self._delete("/api/document/file/",
                          "DELETE /api/document/file/ (Soak-删除)",
                          params={"id": file_id, "is_public": False}) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                self.file_ids.append(file_id)
                resp.failure(f"HTTP {resp.status_code}")

    @task(2)
    def home_statistics(self):
        with self._get("/api/home/statistic/",
                       "GET /api/home/statistic/ (Soak-首页统计)") as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("长时间稳定性压测开始(Soak Test)")
    print("⚠️  建议运行 8h 以上(-t 8h)")
    print("⚠️  另开终端监控: 内存/DB连接/磁盘 (每30分钟采样)")
    print("=" * 60)
