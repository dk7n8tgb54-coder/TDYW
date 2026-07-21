#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
混合负载压测脚本(上线前必补 🔴)

风险:真实用户行为是混合的——早 8 点集中登录 + 查列表 + 上传 + 下载 + 预览同时发生。
单模块压测看不出资源争用,混合负载才能暴露 Gunicorn worker 抢占、DB 连接池打满等真实瓶颈。

覆盖场景(模拟早高峰混合行为):
1. 登录/登出循环(会话压力)
2. 查询资料库文件夹列表(高频读)
3. 上传小文件(中频写 + 磁盘 I/O)
4. 下载文件(带宽)
5. 查询审计日志(高频读 + 哈希链)
6. 查询首页统计(聚合查询)
7. 查询设备列表(高频读)

运行:
    python -m locust -f locustfile/locustfile_mixed_workload.py -H http://localhost
    python -m locust -f locustfile/locustfile_mixed_workload.py -H http://localhost \\
        --headless -u 50 -r 10 -t 10m --csv=mixed_workload

关注: 整体 QPS、P95 响应时间、DB 连接数、Gunicorn worker 饱和度
"""

import uuid
import random

from locust import task, between, events

from _common import TokenSharedHttpUser


class MixedWorkloadUser(TokenSharedHttpUser):
    """混合负载用户:模拟真实用户同时做多种操作"""

    wait_time = between(0.3, 1.5)

    def on_start(self):
        super().on_start()
        self.file_ids = []

    def on_stop(self):
        return  # 保留压测数据(用户要求全部保留)
        for file_id in self.file_ids:
            try:
                self._delete("/api/document/file/", "[清理]",
                             params={"id": file_id, "is_public": False})
            except Exception:
                pass

    # 删除 relogin task: 用户要求不测登录并发(避免 Spug 登录限流:
    # 用户 5 次/15 分钟, IP 30 次/小时)。原 -u 5 时 5 账号轮流登录触发限流锁号。
    # 现在 token 池模式 5 账号登录一次, N 用户复用 token, 不再触发登录。
    # 会话压力测试改由 account_login_stress 单独脚本承担(当前不跑)。

    @task(10)
    def list_folders(self):
        with self._get("/api/document/folder/?is_public=False",
                       "GET /api/document/folder/ (混合-文件夹列表)") as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @task(8)
    def list_audit_log(self):
        with self._get("/api/logs/audit/",
                       "GET /api/logs/audit/ (混合-审计日志)",
                       params={"page": 1, "page_size": 20}) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @task(6)
    def list_devices(self):
        with self._get("/api/device/device-resume/",
                       "GET /api/device/device-resume/ (混合-设备列表)",
                       params={"page": 1, "page_size": 20}) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @task(4)
    def upload_small_file(self):
        file_name = f"mixed_{uuid.uuid4().hex[:8]}.txt"
        content = b"mixed workload upload " * 50
        with self._post("/api/document/upload/",
                        "POST /api/document/upload/ (混合-上传)",
                        files={"file": (file_name, content, "text/plain")},
                        data={"folder_id": "", "is_public": False}) as resp:
            if resp.status_code == 200:
                file_id = resp.json().get("id")
                if file_id:
                    self.file_ids.append(file_id)
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @task(3)
    def download_file(self):
        if not self.file_ids:
            return
        file_id = random.choice(self.file_ids[-5:])
        with self._get("/api/document/download/",
                       "GET /api/document/download/ (混合-下载)",
                       params={"id": file_id, "is_public": False}, stream=True) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @task(5)
    def home_statistics(self):
        with self._get("/api/home/statistic/",
                       "GET /api/home/statistic/ (混合-首页统计)") as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("混合负载压测开始(模拟早 8 点高峰)")
    print("⚠️  综合性测试,需同时监控: docker stats / MySQL / Gunicorn / Celery")
    print("=" * 60)
