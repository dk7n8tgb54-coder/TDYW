"""
Write workflow locustfile.

REQUIRES ALLOW_WRITE_LOAD=true and a test database (name contains test/perf/drill).
Creates test data with PERF_ prefix, limited by MAX_CREATE_LIMIT.
Cleanup runs automatically on test stop.

Run:
    locust -f locustfiles/write_workflows.py --headless -u 5 -r 1 --run-time 2m
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
from helpers.test_data import get_generator
from helpers.cleanup import get_registry

# Safety check - WRITE_LOAD level requires explicit opt-in and test DB
safety_ctx = check_safety(SafetyLevel.WRITE_LOAD)
BASE_URL = safety_ctx["base_url"]
MAX_CREATE = safety_ctx["limits"]["max_create"]

from locust import task, between, events


class WriteWorkflowUser(TokenPoolHttpUser):
    """
    Write workflow user.

    Creates test records with PERF_ prefix, reads them back, then
    cleanup runs on test stop to delete all PERF_ prefixed data.

    Safety:
    - Max MAX_CREATE_LIMIT records per entity type
    - All data uses PERF_ prefix
    - Cleanup registered immediately after creation
    - No real user data is touched
    """

    wait_time = between(2, 6)
    host = BASE_URL

    def _safe_post(self, endpoint, json_data, name=None):
        """Execute POST request with 401 retry and metrics."""
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

        # Check business error
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

    def _safe_get(self, endpoint, name=None):
        """Execute GET request with 401 retry and metrics."""
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
        return resp

    def _safe_put(self, endpoint, json_data, name=None):
        """Execute PUT request with 401 retry and metrics."""
        if name is None:
            name = f"PUT {endpoint}"

        resp = self.api_put(endpoint, json_data=json_data, name=name)

        if resp.status_code == 401:
            self.check_and_refresh_token(resp)
            resp = self.api_put(endpoint, json_data=json_data, name=name)

        collector = get_collector()
        try:
            elapsed_ms = int(resp.elapsed.total_seconds() * 1000)
        except AttributeError:
            elapsed_ms = 0

        collector.record("PUT", endpoint, elapsed_ms, resp.status_code)
        return resp

    def _safe_delete(self, endpoint, name=None):
        """Execute DELETE request with 401 retry and metrics."""
        if name is None:
            name = f"DELETE {endpoint}"

        resp = self.api_delete(endpoint, name=name)

        if resp.status_code == 401:
            self.check_and_refresh_token(resp)
            resp = self.api_delete(endpoint, name=name)

        collector = get_collector()
        try:
            elapsed_ms = int(resp.elapsed.total_seconds() * 1000)
        except AttributeError:
            elapsed_ms = 0

        collector.record("DELETE", endpoint, elapsed_ms, resp.status_code)
        return resp

    # === Write tasks ===

    @task(10)
    def create_runlog(self):
        """Create a test runlog record."""
        gen = get_generator()
        registry = get_registry()

        try:
            record = gen.make_record("runlog")
        except ValueError:
            return  # Max limit reached

        # Remove internal fields before sending
        send_data = {k: v for k, v in record.items() if not k.startswith("_")}

        data = self._safe_post("/api/runlog/", send_data)
        if data and data.get("id"):
            registry.register("runlog", data["id"])

    @task(8)
    def create_duty_log(self):
        """Create a test duty log record."""
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

    @task(6)
    def create_reminder(self):
        """Create a test reminder."""
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

    @task(5)
    def create_interference(self):
        """Create a test interference record."""
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

    @task(5)
    def create_fault(self):
        """Create a test fault record."""
        gen = get_generator()
        registry = get_registry()

        try:
            record = gen.make_record("fault")
        except ValueError:
            return

        send_data = {k: v for k, v in record.items() if not k.startswith("_")}

        data = self._safe_post("/api/fault/faultrecord/", send_data)
        if data and data.get("id"):
            registry.register("fault", data["id"])

    @task(4)
    def create_device(self):
        """Create a test device record."""
        gen = get_generator()
        registry = get_registry()

        try:
            record = gen.make_record("device")
        except ValueError:
            return

        send_data = {k: v for k, v in record.items() if not k.startswith("_")}

        data = self._safe_post("/api/device/device-resume/", send_data)
        if data and data.get("id"):
            registry.register("device", data["id"])

    @task(4)
    def create_upgrade(self):
        """Create a test upgrade record."""
        gen = get_generator()
        registry = get_registry()

        try:
            record = gen.make_record("upgrade")
        except ValueError:
            return

        send_data = {k: v for k, v in record.items() if not k.startswith("_")}

        data = self._safe_post("/api/upgrade/records/", send_data)
        if data and data.get("id"):
            registry.register("upgrade", data["id"])

    @task(3)
    def create_radio_license(self):
        """Create a test radio license record."""
        gen = get_generator()
        registry = get_registry()

        try:
            record = gen.make_record("radio_license")
        except ValueError:
            return

        send_data = {k: v for k, v in record.items() if not k.startswith("_")}

        data = self._safe_post("/api/radio-license/", send_data)
        if data and data.get("id"):
            registry.register("radio_license", data["id"])

    @task(3)
    def create_contract_agreement(self):
        """Create a test contract agreement."""
        gen = get_generator()
        registry = get_registry()

        try:
            record = gen.make_record("contract_agreement")
        except ValueError:
            return

        send_data = {k: v for k, v in record.items() if not k.startswith("_")}

        data = self._safe_post("/api/contract-agreement/", send_data)
        if data and data.get("id"):
            registry.register("contract_agreement", data["id"])

    # === Read-after-write verification ===

    @task(20)
    def read_created_data(self):
        """Read back created data to verify it exists."""
        registry = get_registry()
        gen = get_generator()

        all_created = gen.get_all_created()
        if not all_created:
            # No data created yet, read general lists
            self._safe_get("/api/runlog/")
            return

        # Pick a random entity type that has created records
        entity_types = [k for k, ids in all_created.items() if ids]
        if not entity_types:
            self._safe_get("/api/runlog/")
            return

        entity_type = random.choice(entity_types)
        endpoint_map = {
            "runlog": "/api/runlog/",
            "duty_log": "/api/duty/duty/",
            "reminder": "/api/reminder/",
            "interference": "/api/interference/",
            "fault": "/api/fault/faultrecord/",
            "device": "/api/device/device-resume/",
            "upgrade": "/api/upgrade/records/",
            "radio_license": "/api/radio-license/",
            "contract_agreement": "/api/contract-agreement/",
        }

        endpoint = endpoint_map.get(entity_type, "/api/runlog/")
        self._safe_get(endpoint)


@events.test_stop.add_listener
def _on_write_stop(environment, **kwargs):
    """Print metrics summary and run cleanup on test stop."""
    collector = get_collector()
    collector.print_summary()

    # Run cleanup
    registry = get_registry()
    stats = registry.get_stats()
    if any(stats.values()):
        print(f"\n[CLEANUP] Starting cleanup. Records to delete: {stats}")
        host = environment.host.rstrip("/") if environment.host else BASE_URL
        # Get auth headers from token pool
        from helpers.auth import get_token_pool
        pool = get_token_pool()
        try:
            auth_headers = pool.get_auth_headers(host, 0)
        except Exception:
            auth_headers = None
        registry.cleanup_all(host, auth_headers)
    else:
        print("[CLEANUP] No records to clean up.")
