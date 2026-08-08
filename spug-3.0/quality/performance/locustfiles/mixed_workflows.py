"""
Mixed workflow locustfile - simulates real user behavior.

Combines read, write, and file operations in realistic proportions.
REQUIRES ALLOW_WRITE_LOAD=true for write/file portions.
Read-only portions run even without ALLOW_WRITE_LOAD.

Run:
    locust -f locustfiles/mixed_workflows.py --headless -u 15 -r 3 --run-time 5m
"""

import os
import sys
import time
import random
import io
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from helpers.safety import check_safety, SafetyLevel
from helpers.auth import TokenPoolHttpUser
from helpers.metrics import get_collector
from helpers.test_data import get_generator
from helpers.cleanup import get_registry

# Safety check - mixed workflows require write load
safety_ctx = check_safety(SafetyLevel.WRITE_LOAD)
BASE_URL = safety_ctx["base_url"]
MAX_CREATE = safety_ctx["limits"]["max_create"]
MAX_FILE_SIZE = safety_ctx["limits"]["max_file_size"]
MAX_FILE_COUNT = safety_ctx["limits"]["max_file_count"]

from locust import task, between, events
import threading


class MixedWorkflowUser(TokenPoolHttpUser):
    """
    Mixed workflow user simulating real usage patterns.

    Task distribution (~70% read, ~20% write, ~10% file):
    - Read: navigation, notices, lists, dashboards
    - Write: create reminders, runlogs, duty logs
    - File: upload small files, list documents
    """

    wait_time = between(2, 8)
    host = BASE_URL

    # Shared file upload counter
    _upload_count = 0
    _upload_lock = threading.Lock()

    def _safe_get(self, endpoint, name=None):
        """GET with 401 retry and metrics."""
        if name is None:
            name = f"GET {endpoint}"

        resp = self.api_get(endpoint, name=name)

        if resp.status_code == 401:
            self.check_and_refresh_token(resp)
            resp = self.api_get(endpoint, name=name)

        collector = get_collector()
        try:
            elapsed_ms = int(resp.elapsed.total_seconds() * 1000)
        except AttributeError:
            elapsed_ms = 0
        collector.record("GET", endpoint, elapsed_ms, resp.status_code)

        if resp.status_code == 200:
            try:
                data = resp.json()
                if isinstance(data, dict) and data.get("error"):
                    collector.record_business_error("GET", endpoint)
            except Exception:
                pass

        return resp

    def _safe_post(self, endpoint, json_data=None, name=None):
        """POST with 401 retry and metrics."""
        if name is None:
            name = f"POST {endpoint}"

        resp = self.api_post(endpoint, json_data=json_data, name=name)

        if resp.status_code == 401:
            self.check_and_refresh_token(resp)
            resp = self.api_post(endpoint, json_data=json_data, name=name)

        collector = get_collector()
        try:
            elapsed_ms = int(resp.elapsed.total_seconds() * 1000)
        except AttributeError:
            elapsed_ms = 0
        collector.record("POST", endpoint, elapsed_ms, resp.status_code)

        if resp.status_code == 200:
            try:
                data = resp.json()
                if isinstance(data, dict) and data.get("error"):
                    collector.record_business_error("POST", endpoint)
                    return None
                return data
            except Exception:
                pass

        return None

    # === Read tasks (high weight - simulate browsing) ===

    @task(15)
    def browse_home(self):
        """Browse home dashboard."""
        self._safe_get("/api/home/navigation/")
        self._safe_get("/api/home/statistic/")

    @task(8)
    def browse_runlog(self):
        """Browse runlog list."""
        self._safe_get("/api/runlog/")

    @task(6)
    def browse_duty(self):
        """Browse duty logs."""
        self._safe_get("/api/duty/duty/")

    @task(6)
    def browse_reminders(self):
        """Browse reminders."""
        self._safe_get("/api/reminder/")

    @task(5)
    def browse_radio_license(self):
        """Browse radio licenses."""
        self._safe_get("/api/radio-license/")

    @task(5)
    def browse_contracts(self):
        """Browse contract agreements."""
        self._safe_get("/api/contract-agreement/")

    @task(5)
    def browse_documents(self):
        """Browse document folders and files."""
        self._safe_get("/api/document/folder/")
        self._safe_get("/api/document/file/")

    @task(4)
    def browse_regulations(self):
        """Browse regulations."""
        self._safe_get("/api/regulation/")

    @task(4)
    def browse_devices(self):
        """Browse devices."""
        self._safe_get("/api/device/device-resume/")

    @task(4)
    def browse_faults(self):
        """Browse fault records."""
        self._safe_get("/api/fault/faultrecord/")

    @task(4)
    def browse_upgrades(self):
        """Browse upgrade records."""
        self._safe_get("/api/upgrade/records/")

    @task(3)
    def browse_interference(self):
        """Browse interference records."""
        self._safe_get("/api/interference/")

    @task(3)
    def browse_alerts(self):
        """Browse alert rules."""
        self._safe_get("/api/alert/")

    @task(3)
    def browse_data_analysis(self):
        """Browse data analysis dashboard."""
        self._safe_get("/api/data-analysis/overview/")

    @task(2)
    def browse_audit_logs(self):
        """Browse audit logs."""
        self._safe_get("/api/logs/audit/")

    @task(2)
    def browse_settings(self):
        """Browse settings."""
        self._safe_get("/api/setting/")

    # === Write tasks (lower weight - simulate occasional data entry) ===

    @task(4)
    def create_reminder(self):
        """Create a reminder (simulates user adding a todo)."""
        gen = get_generator()
        registry = get_registry()

        try:
            record = gen.make_record("reminder")
        except ValueError:
            return

        send_data = {k: v for k, v in record.items() if not k.startswith("_")}
        data = self._safe_post("/api/reminder/", send_data)
        if data and data.get("id"):
            registry.register("reminder", data["id"])

    @task(3)
    def create_runlog(self):
        """Create a runlog entry."""
        gen = get_generator()
        registry = get_registry()

        try:
            record = gen.make_record("runlog")
        except ValueError:
            return

        send_data = {k: v for k, v in record.items() if not k.startswith("_")}
        data = self._safe_post("/api/runlog/", send_data)
        if data and data.get("id"):
            registry.register("runlog", data["id"])

    @task(3)
    def create_duty_log(self):
        """Create a duty log entry."""
        gen = get_generator()
        registry = get_registry()

        try:
            record = gen.make_record("duty_log")
        except ValueError:
            return

        send_data = {k: v for k, v in record.items() if not k.startswith("_")}
        data = self._safe_post("/api/duty/duty/", send_data)
        if data and data.get("id"):
            registry.register("duty_log", data["id"])

    @task(2)
    def create_interference(self):
        """Create an interference record."""
        gen = get_generator()
        registry = get_registry()

        try:
            record = gen.make_record("interference")
        except ValueError:
            return

        send_data = {k: v for k, v in record.items() if not k.startswith("_")}
        data = self._safe_post("/api/interference/", send_data)
        if data and data.get("id"):
            registry.register("interference", data["id"])

    # === File tasks (low weight - simulate occasional file ops) ===

    @task(2)
    def upload_file(self):
        """Upload a small file."""
        with MixedWorkflowUser._upload_lock:
            if MixedWorkflowUser._upload_count >= MAX_FILE_COUNT:
                return
            MixedWorkflowUser._upload_count += 1

        gen = get_generator()
        registry = get_registry()

        file_size = random.choice([1024, 10240, 10240])  # 1KB or 10KB
        file_content = gen.make_file_content(file_size)
        filename = gen.make_filename("txt")

        headers = self.get_auth_headers()
        headers.pop("Content-Type", None)

        files = {
            "file": (filename, io.BytesIO(file_content), "text/plain"),
        }

        try:
            resp = self.client.post(
                "/api/document/file/upload/",
                files=files,
                headers=headers,
                name="POST /api/document/file/upload/ (mixed)",
            )

            if resp.status_code == 401:
                self.check_and_refresh_token(resp)
                headers = self.get_auth_headers()
                headers.pop("Content-Type", None)
                resp = self.client.post(
                    "/api/document/file/upload/",
                    files=files,
                    headers=headers,
                    name="POST /api/document/file/upload/ (mixed)",
                )

            collector = get_collector()
            try:
                elapsed_ms = int(resp.elapsed.total_seconds() * 1000)
            except AttributeError:
                elapsed_ms = 0
            collector.record("POST", "/api/document/file/upload/", elapsed_ms, resp.status_code)

            if resp.status_code in (200, 201):
                try:
                    data = resp.json()
                    file_id = data.get("id") or data.get("data", {}).get("id")
                    if file_id:
                        registry.register_file(file_id, filename)
                except Exception:
                    pass

        except Exception as e:
            collector = get_collector()
            collector.record("POST", "/api/document/file/upload/", 0, 0, error=str(e))


@events.test_start.add_listener
def _on_mixed_test_start(environment, **kwargs):
    """Reset counters on test start."""
    MixedWorkflowUser._upload_count = 0
    gen = get_generator()
    gen.reset()
    registry = get_registry()
    registry.reset()


@events.test_stop.add_listener
def _on_mixed_stop(environment, **kwargs):
    """Print metrics summary and run cleanup on test stop."""
    collector = get_collector()
    collector.print_summary()

    # Print creation stats
    gen = get_generator()
    created = gen.get_all_created()
    if any(created.values()):
        print(f"\n[CREATED] Records created this run: {gen.get_stats()}")
    print(f"[FILE] Files uploaded this run: {MixedWorkflowUser._upload_count}")

    # Run cleanup
    registry = get_registry()
    stats = registry.get_stats()
    if any(stats.values()):
        print(f"\n[CLEANUP] Starting cleanup. Items: {stats}")
        host = environment.host.rstrip("/") if environment.host else BASE_URL
        from helpers.auth import get_token_pool
        pool = get_token_pool()
        try:
            auth_headers = pool.get_auth_headers(host, 0)
        except Exception:
            auth_headers = None
        registry.cleanup_all(host, auth_headers)
    else:
        print("[CLEANUP] No records to clean up.")
