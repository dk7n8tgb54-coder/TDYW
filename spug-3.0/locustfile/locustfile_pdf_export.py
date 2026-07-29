#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PDF 导出并发压测脚本(上线前必补 🔴)

风险:PDF 导出是 CPU/内存密集操作。8G 服务器下 tdyw 容器 limit=2G、kkfileview limit=1.5G,
并发导出极易触发 OOM。本脚本验证并发导出上限。

覆盖模块:
1. department_duty_log(部门值班日志)PDF 导出 - POST /api/department-duty-log/export/pdf/

前置条件:目标环境需已有已签的 department_duty_log 记录(只导出已签,不导出草稿)。

运行:
    python -m locust -f locustfile/locustfile_pdf_export.py -H http://localhost
    python -m locust -f locustfile/locustfile_pdf_export.py -H http://localhost \\
        --headless -u 10 -r 2 -t 5m --csv=pdf_export

关注: P95 响应时间、失败率(OOM=500)、容器内存峰值
"""

import logging

from locust import task, between, events

from _common import TokenSharedHttpUser

logger = logging.getLogger(__name__)


class PdfExportUser(TokenSharedHttpUser):
    """PDF 导出压测用户(Token 池共享)"""

    wait_time = between(2, 5)

    def on_start(self):
        super().on_start()
        self.duty_log_ids = []
        self._fetch_record_ids()

    def _fetch_record_ids(self):
        """查询已有记录 id 列表,判断环境是否有可导出数据。

        路径用中划线 department-duty-log(主路由 spug/urls.py 注册为 department-duty-log/)。
        DepartmentDutyLogListCreateView.get 返回 {data: {records: [...], total: N}}。
        @auth 权限不足时返回 {data: '', error: '...'},需先检查 error。
        """
        with self._get(
            "/api/department-duty-log/records/?page=1&page_size=20",
            "[准备] 查询值班日志记录",
        ) as resp:
            if resp.status_code == 200:
                body = resp.json() or {}
                if body.get("error"):
                    resp.failure(f"查询权限不足: {body['error'][:80]}")
                    return
                data = body.get("data") or {}
                records = data.get("records") or []
                self.duty_log_ids = [r.get("id") for r in records if r.get("id")]
            else:
                # 暴露 404/403 等真实错误,不再假成功
                resp.failure(f"查询值班日志 HTTP {resp.status_code}: {resp.text[:80]}")

        if not self.duty_log_ids:
            logger.warning("[PDF导出] 未找到任何记录。请先在目标环境创建已签值班日志记录。")

    @task(5)
    def export_duty_log_pdf(self):
        """部门值班日志 PDF 导出(批量导出已签/已作废记录)

        DepartmentDutyLogPdfExportView 是 POST,接受 JSON body 筛选条件。
        空 body 导出全部已签/已作废记录,不依赖单个 record_id。
        即使 duty_log_ids 为空也尝试导出(暴露"无数据"的真实响应,而非静默跳过)。
        """
        with self._post(
            "/api/department-duty-log/export/pdf/",
            "POST /api/department-duty-log/export/pdf/ (值班日志PDF导出)",
            json={},  # 空 body 导出全部已签/已作废记录
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 500:
                resp.failure(f"导出 500(可能 OOM): {resp.text[:120]}")
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:120]}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("PDF 导出并发压测开始")
    print("  密切关注: docker stats tdyw 内存峰值")
    print("  前置: 目标环境需有已签值班日志记录,否则导出返回 400")
    print("=" * 60)
