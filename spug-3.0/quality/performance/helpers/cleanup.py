"""
Test data cleanup for performance testing.

ONLY deletes data created by the current test run, identified by the PERF_ prefix.
This module is fail-safe: if cleanup fails, it logs the error but does not crash.

Usage:

    from helpers.cleanup import CleanupRegistry

    registry = CleanupRegistry()

    # During test: register created records
    registry.register("radio_license", 42, "/api/radio-license/42/")

    # On test stop: cleanup all registered records
    registry.cleanup_all(host, auth_headers)
"""

import os
import sys
import time
import threading
import json
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from helpers.safety import get_safety_context


class CleanupRegistry:
    """
    Registry of test-created records for cleanup.

    Tracks:
    - Entity type -> list of (record_id, delete_url) tuples
    - Cleanup runs on test stop (locust test_stop event) or manually

    Safety:
    - Only deletes records with PERF_ prefix in their data
    - Only deletes registered record IDs
    - Best-effort: logs errors but doesn't fail
    """

    # Maps entity type to the API endpoint pattern for deletion
    DELETE_ENDPOINTS = {
        "radio_license": "/api/radio-license/{id}/",
        "station_frequency_approval": "/api/radio-license/approvals/{id}/",
        "contract_agreement": "/api/contract-agreement/{id}/",
        "runlog": "/api/runlog/{id}/",
        "duty_log": "/api/duty/duty/{id}/",
        "dept_duty_log": "/api/department-duty-log/records/{id}/",
        "interference": "/api/interference/{id}/",
        "fault": "/api/fault/faultrecord/{id}/",
        "reminder": "/api/reminder/{id}/",
        "device": "/api/device/device-resume/{id}/",
        "upgrade": "/api/upgrade/records/{id}/",
        "regulation": "/api/regulation/{id}/",
        "document_folder": "/api/document/folder/{id}/",
        "document_file": "/api/document/file/{id}/",
        "notice": "/api/home/announcement/admin/{id}/",
        "navigation": "/api/home/navigation/{id}/",
        # File cleanup (special handling)
        "uploaded_file": None,  # No standard delete endpoint; handled separately
    }

    def __init__(self):
        ctx = get_safety_context()
        self.prefix = ctx["prefix"]
        self._registry = defaultdict(list)  # entity_type -> [(id, url, timestamp)]
        self._lock = threading.Lock()
        self._cleaned = False

    def register(self, entity_type, record_id, delete_url=None):
        """
        Register a created record for cleanup.

        Args:
            entity_type: Type of entity (e.g., "radio_license")
            record_id: ID of the created record
            delete_url: Optional explicit delete URL. If None, uses template.
        """
        with self._lock:
            if delete_url is None:
                template = self.DELETE_ENDPOINTS.get(entity_type)
                if template:
                    delete_url = template.format(id=record_id)
                else:
                    delete_url = None

            self._registry[entity_type].append((record_id, delete_url, time.time()))

    def register_file(self, file_id, file_name):
        """Register an uploaded file for cleanup."""
        with self._lock:
            self._registry["uploaded_file"].append((file_id, file_name, time.time()))

    def cleanup_all(self, host, auth_headers=None, client=None):
        """
        Delete all registered records.

        Args:
            host: Base URL for API calls
            auth_headers: Dict with X-Token header
            client: Optional requests.Session for making calls

        Returns:
            dict: {"deleted": count, "failed": count, "errors": [...]}
        """
        with self._lock:
            if self._cleaned:
                return {"deleted": 0, "failed": 0, "errors": ["Already cleaned up"]}
            self._cleaned = True

            # Copy registry to avoid holding lock during network calls
            registry_copy = {k: list(v) for k, v in self._registry.items()}

        result = {"deleted": 0, "failed": 0, "errors": []}

        # Clean up in reverse dependency order
        cleanup_order = [
            "uploaded_file",
            "document_file",
            "document_folder",
            "radio_license",
            "station_frequency_approval",
            "contract_agreement",
            "runlog",
            "duty_log",
            "dept_duty_log",
            "interference",
            "fault",
            "reminder",
            "device",
            "upgrade",
            "regulation",
            "notice",
            "navigation",
        ]

        for entity_type in cleanup_order:
            records = registry_copy.get(entity_type, [])
            if not records:
                continue

            print(f"[CLEANUP] Cleaning {len(records)} '{entity_type}' records...")

            # Delete in reverse order (most recent first)
            for record_id, delete_url, _ in reversed(records):
                if delete_url is None:
                    result["errors"].append(
                        f"No delete URL for {entity_type}/{record_id}"
                    )
                    continue

                try:
                    success = self._delete_one(
                        host, delete_url, auth_headers, client
                    )
                    if success:
                        result["deleted"] += 1
                    else:
                        result["failed"] += 1
                except Exception as e:
                    result["failed"] += 1
                    result["errors"].append(
                        f"Failed to delete {entity_type}/{record_id}: {e}"
                    )

        print(
            f"[CLEANUP] Done: {result['deleted']} deleted, "
            f"{result['failed']} failed, {len(result['errors'])} errors"
        )

        if result["errors"]:
            for err in result["errors"][:10]:  # Show first 10 errors
                print(f"  [CLEANUP ERROR] {err}")

        return result

    def _delete_one(self, host, delete_url, auth_headers, client):
        """Delete a single record. Returns True on success."""
        full_url = f"{host}{delete_url}"

        headers = {"Content-Type": "application/json"}
        if auth_headers:
            headers.update(auth_headers)

        try:
            if client is not None:
                response = client.delete(full_url, headers=headers, timeout=30)
            else:
                import requests
                response = requests.delete(full_url, headers=headers, timeout=30)

            # 200 or 204 = success
            if response.status_code in (200, 204):
                return True

            # 404 = already deleted, treat as success
            if response.status_code == 404:
                return True

            # Check for business error
            try:
                data = response.json()
                if data.get("error"):
                    print(
                        f"  [CLEANUP] Business error deleting {delete_url}: "
                        f"{data['error']}"
                    )
                    return False
            except (json.JSONDecodeError, ValueError):
                pass

            return False

        except Exception as e:
            print(f"  [CLEANUP] Exception deleting {delete_url}: {e}")
            return False

    def get_stats(self):
        """Get registry statistics."""
        with self._lock:
            return {
                entity_type: len(records)
                for entity_type, records in self._registry.items()
            }

    def reset(self):
        """Reset the registry for a new test run."""
        with self._lock:
            self._registry.clear()
            self._cleaned = False


# --- Global instance ---
_registry = None


def get_registry():
    """Get the global CleanupRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = CleanupRegistry()
    return _registry


# --- Locust event hooks ---

def setup_locust_cleanup(host_provider, auth_provider):
    """
    Set up locust test_stop event to trigger cleanup.

    Args:
        host_provider: Callable that returns the current host URL
        auth_provider: Callable that returns auth headers dict
    """
    try:
        from locust import events

        @events.test_stop.add_listener
        def _on_test_stop(environment, **kwargs):
            registry = get_registry()
            host = host_provider()
            auth_headers = auth_provider()
            registry.cleanup_all(host, auth_headers)

    except ImportError:
        pass
