"""
Smoke load test - verifies auth and basic endpoint availability.

1-3 users, short duration. Safe to run in any environment with ALLOW_PERFORMANCE_TEST=true.

Run:
    locust -f locustfiles/smoke_load.py --headless -u 1 -r 1 --run-time 30s
"""

import os
import sys
import time
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


class SmokeTestUser(TokenPoolHttpUser):
    """Smoke test user - single user, short wait time."""

    wait_time = between(1, 3)
    host = BASE_URL

    @task(1)
    def smoke_login_check(self):
        """Verify auth token is valid."""
        resp = self.api_get("/api/account/self/")
        if resp.status_code == 401:
            self.check_and_refresh_token(resp)
            resp = self.api_get("/api/account/self/")

        collector = get_collector()
        collector.record("GET", "/api/account/self/", resp.elapsed_ms if hasattr(resp, "elapsed_ms") else 0, resp.status_code)

        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("error"):
                    collector.record_business_error("GET", "/api/account/self/")
            except Exception:
                pass

    @task(2)
    def smoke_navigation(self):
        """Verify navigation endpoint."""
        resp = self.api_get("/api/home/navigation/")
        if resp.status_code == 401:
            self.check_and_refresh_token(resp)
            resp = self.api_get("/api/home/navigation/")

        collector = get_collector()
        collector.record("GET", "/api/home/navigation/", resp.elapsed_ms if hasattr(resp, "elapsed_ms") else 0, resp.status_code)

    @task(3)
    def smoke_settings(self):
        """Verify settings endpoint."""
        resp = self.api_get("/api/setting/")
        if resp.status_code == 401:
            self.check_and_refresh_token(resp)
            resp = self.api_get("/api/setting/")

        collector = get_collector()
        collector.record("GET", "/api/setting/", resp.elapsed_ms if hasattr(resp, "elapsed_ms") else 0, resp.status_code)


@events.test_stop.add_listener
def _on_smoke_stop(environment, **kwargs):
    """Print metrics summary on test stop."""
    collector = get_collector()
    collector.print_summary()
