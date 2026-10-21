# -*- coding: utf-8 -*-
"""设备管理模块只读压测（equipment_lifecycle + upgrade 现行菜单端点）。

安全级别 READ_ONLY（helpers/safety.py fail-closed 校验）：仅 GET 请求，
不创建/修改/删除任何业务数据。运行前必须显式提供：

    BASE_URL=http://<dev-or-test-host>
    ALLOW_PERFORMANCE_TEST=true
    TEST_USER_1=<专用测试账号>  TEST_PASS_1=<密码>

停止条件：由 --run-time 限时控制；请求失败率经 --exit-code-on-error
反映在退出码上。禁止指向生产环境（BASE_URL 指向生产主机时 safety 拒绝）。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from helpers.safety import check_safety, SafetyLevel
from helpers.auth import TokenPoolHttpUser

safety_ctx = check_safety(SafetyLevel.READ_ONLY)
BASE_URL = safety_ctx["base_url"]

from locust import task, between

EL = "/api/equipment-lifecycle"
UP = "/api/upgrade"


class EquipmentReadUser(TokenPoolHttpUser):
    """模拟设备管理菜单只读浏览：系统档案/运行处置记录/维护台账/模板/系统升级。"""

    wait_time = between(1, 3)
    host = BASE_URL

    def on_start(self):
        self.system_id = None
        self.record_id = None
        self._refresh_ids()

    def _pick_first_id(self, url, name):
        resp = self.api_get(url, name=name)
        try:
            rows = resp.json()["data"]["data"]
            if rows:
                return rows[0]["id"]
        except Exception:
            pass
        return None

    def _refresh_ids(self):
        self.system_id = self._pick_first_id(
            f"{EL}/systems/?page_size=5", "GET systems(id pool)")
        self.record_id = self._pick_first_id(
            f"{EL}/records/?page_size=5", "GET records(id pool)")

    @task(3)
    def systems_list(self):
        self.api_get(f"{EL}/systems/", name="GET systems list")

    @task(3)
    def records_list(self):
        self.api_get(f"{EL}/records/", name="GET records list")

    @task(2)
    def records_statistics(self):
        self.api_get(f"{EL}/records/statistics/", name="GET records statistics")

    @task(2)
    def records_todo(self):
        self.api_get(f"{EL}/records/todo/", name="GET records todo")

    @task(2)
    def ledgers_list(self):
        self.api_get(f"{EL}/ledgers/", name="GET ledgers list")

    @task(2)
    def period_groups(self):
        self.api_get(f"{EL}/ledgers/period-groups/?ledger_type=week_month",
                     name="GET ledger period groups")

    @task(1)
    def template_groups(self):
        self.api_get(f"{EL}/ledgers/template-groups/?ledger_type=week_month",
                     name="GET ledger template groups")

    @task(1)
    def excel_templates_available(self):
        self.api_get(f"{EL}/excel-templates/available/?ledger_type=week_month",
                     name="GET excel templates available")

    @task(2)
    def upgrade_records(self):
        self.api_get(f"{UP}/records/", name="GET upgrade records")

    @task(1)
    def upgrade_filter_options(self):
        self.api_get(f"{UP}/filter-options/", name="GET upgrade filter options")

    @task(2)
    def system_detail(self):
        if self.system_id:
            self.api_get(f"{EL}/systems/{self.system_id}/", name="GET system detail")

    @task(2)
    def record_detail(self):
        if self.record_id:
            self.api_get(f"{EL}/records/{self.record_id}/", name="GET record detail")
