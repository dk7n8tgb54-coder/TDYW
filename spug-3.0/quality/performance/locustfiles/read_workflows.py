"""
Read-only workflow locustfile.

Covers ALL major API endpoints with GET requests only.
No data is created, modified, or deleted.

Run:
    locust -f locustfiles/read_workflows.py --headless -u 20 -r 2 --run-time 5m
"""

import os
import sys
import time
import random
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from helpers.safety import check_safety, SafetyLevel
from helpers.auth import TokenPoolHttpUser
from helpers.metrics import get_collector

# Safety check - MUST pass before anything else
safety_ctx = check_safety(SafetyLevel.READ_ONLY)
BASE_URL = safety_ctx["base_url"]

from locust import task, between, events


class ReadWorkflowUser(TokenPoolHttpUser):
    """
    Read-only workflow user.

    Simulates a user browsing through various modules:
    - Dashboard / Home
    - Data Analysis
    - Duty Logs
    - Run Logs
    - Radio License
    - Contract Agreement
    - Documents
    - Regulations
    - Devices
    - Faults
    - Upgrades
    - Interference
    - Alerts
    - Account Management
    - Audit Logs
    - Settings
    """

    wait_time = between(1, 5)
    host = BASE_URL

    def _safe_get(self, endpoint, name=None):
        """Execute GET request with 401 retry and metrics recording."""
        if name is None:
            name = f"GET {endpoint}"

        resp = self.api_get(endpoint, name=name)

        # 401 retry
        if resp.status_code == 401:
            self.check_and_refresh_token(resp)
            resp = self.api_get(endpoint, name=name)

        # Record metrics
        collector = get_collector()

        # Locust response time is in milliseconds
        try:
            elapsed_ms = int(resp.elapsed.total_seconds() * 1000)
        except AttributeError:
            elapsed_ms = 0

        collector.record("GET", endpoint, elapsed_ms, resp.status_code)

        # Check for business error (HTTP 200 with error field)
        if resp.status_code == 200:
            try:
                data = resp.json()
                if isinstance(data, dict) and data.get("error"):
                    collector.record_business_error("GET", endpoint)
            except Exception:
                pass

        return resp

    # === Home / Dashboard ===

    @task(10)
    def home_navigation(self):
        """Get navigation menu."""
        self._safe_get("/api/home/navigation/")

    @task(5)
    def home_statistics(self):
        """Get home dashboard statistics."""
        self._safe_get("/api/home/statistic/")

    @task(6)
    def home_announcements(self):
        """Get announcement list."""
        self._safe_get("/api/home/announcement/")

    @task(3)
    def home_unread_count(self):
        """Get unread announcement count."""
        self._safe_get("/api/home/announcement/unread-count/")

    # === Account / User Info ===

    @task(10)
    def account_self(self):
        """Get current user info."""
        self._safe_get("/api/account/self/")

    @task(4)
    def account_users(self):
        """Get user list (admin only)."""
        self._safe_get("/api/account/user/")

    @task(3)
    def account_roles(self):
        """Get role list."""
        self._safe_get("/api/account/role/")

    @task(2)
    def account_tenants(self):
        """Get tenant list."""
        self._safe_get("/api/account/tenant/")

    @task(2)
    def account_login_history(self):
        """Get login history."""
        # NOTE: Endpoint path may need verification
        self._safe_get("/api/account/login/history/")

    # === Data Analysis ===

    @task(5)
    def data_analysis_overview(self):
        """Get data analysis overview."""
        self._safe_get("/api/data-analysis/overview/")

    @task(3)
    def data_analysis_fault(self):
        """Get fault data analysis."""
        # NOTE: Endpoint path may need verification
        self._safe_get("/api/data-analysis/fault/")

    # === Department Duty Log ===

    @task(4)
    def dept_duty_log_records(self):
        """Get department duty log records."""
        self._safe_get("/api/department-duty-log/records/")

    @task(2)
    def dept_duty_log_options(self):
        """Get department duty log options."""
        self._safe_get("/api/department-duty-log/options/")

    # === Duty Log ===

    @task(4)
    def duty_records(self):
        """Get duty records."""
        self._safe_get("/api/duty/duty/")

    # === RunLog ===

    @task(4)
    def runlog_records(self):
        """Get runlog records."""
        self._safe_get("/api/runlog/")

    @task(2)
    def runlog_overview(self):
        """Get runlog overview."""
        self._safe_get("/api/runlog/overview/")

    @task(2)
    def runlog_statistics(self):
        """Get runlog statistics."""
        self._safe_get("/api/runlog/statistics/")

    # === Reminder ===

    @task(5)
    def reminder_list(self):
        """Get reminder list."""
        self._safe_get("/api/reminder/")

    @task(2)
    def reminder_status(self):
        """Get reminder status."""
        self._safe_get("/api/reminder/status/")

    # === Radio License ===

    @task(4)
    def radio_license_list(self):
        """Get radio license list."""
        self._safe_get("/api/radio-license/")

    # === Station Frequency Approval ===

    @task(3)
    def radio_license_approvals(self):
        """Get station frequency approval list."""
        self._safe_get("/api/radio-license/approvals/")

    # === Contract Agreement ===

    @task(4)
    def contract_agreement_list(self):
        """Get contract agreement list."""
        self._safe_get("/api/contract-agreement/")

    @task(2)
    def contract_agreement_badge(self):
        """Get contract agreement badge count."""
        self._safe_get("/api/contract-agreement/badge/")

    # === Document ===

    @task(5)
    def document_folders(self):
        """Get document folders."""
        self._safe_get("/api/document/folder/")

    @task(5)
    def document_files(self):
        """Get document files."""
        self._safe_get("/api/document/file/")

    @task(3)
    def document_disk_usage(self):
        """Get document disk usage."""
        self._safe_get("/api/document/disk_usage/")

    # === Regulation ===

    @task(4)
    def regulation_list(self):
        """Get regulation list."""
        self._safe_get("/api/regulation/")

    @task(2)
    def regulation_category_tree(self):
        """Get regulation category tree."""
        self._safe_get("/api/regulation/categories/tree/")

    # === Device ===

    @task(4)
    def device_list(self):
        """Get device resume list."""
        self._safe_get("/api/device/device-resume/")

    @task(3)
    def device_history(self):
        """Get device history list."""
        self._safe_get("/api/device/device-event/")

    # === Fault ===

    @task(4)
    def fault_records(self):
        """Get fault record list."""
        self._safe_get("/api/fault/faultrecord/")

    # === Upgrade ===

    @task(4)
    def upgrade_records(self):
        """Get upgrade records."""
        self._safe_get("/api/upgrade/records/")

    @task(3)
    def upgrade_statistics(self):
        """Get upgrade statistics."""
        self._safe_get("/api/upgrade/statistics/")

    @task(2)
    def upgrade_plans(self):
        """Get upgrade plans."""
        self._safe_get("/api/upgrade/plans/")

    # === Interference ===

    @task(4)
    def interference_records(self):
        """Get interference record list."""
        self._safe_get("/api/interference/")

    @task(2)
    def interference_statistics(self):
        """Get interference statistics."""
        self._safe_get("/api/interference/statistics/")

    # === Alert ===

    @task(4)
    def alert_rules(self):
        """Get alert rules."""
        self._safe_get("/api/alert/")

    @task(3)
    def alert_records(self):
        """Get alert records."""
        self._safe_get("/api/alert/records/")

    @task(2)
    def alert_trend(self):
        """Get alert trend."""
        self._safe_get("/api/alert/trend/")

    # === Audit Logs ===

    @task(3)
    def audit_logs(self):
        """Get audit log list."""
        self._safe_get("/api/logs/audit/")

    # === Settings ===

    @task(3)
    def settings(self):
        """Get system settings."""
        self._safe_get("/api/setting/")


@events.test_stop.add_listener
def _on_read_stop(environment, **kwargs):
    """Print metrics summary on test stop."""
    collector = get_collector()
    collector.print_summary()
