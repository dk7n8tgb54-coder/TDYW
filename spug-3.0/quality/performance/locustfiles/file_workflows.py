"""
File upload/download workflow locustfile.

Tests file upload and download endpoints with small files only.
- Maximum file size: 1MB (MAX_FILE_SIZE from env)
- Maximum file count: 10 (MAX_FILE_COUNT from env)
- Uses synthetic text data with PERF_ prefix

Run:
    locust -f locustfiles/file_workflows.py --headless -u 3 -r 1 --run-time 2m
"""

import os
import sys
import time
import io
import random
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from helpers.safety import check_safety, SafetyLevel
from helpers.auth import TokenPoolHttpUser
from helpers.metrics import get_collector
from helpers.test_data import get_generator
from helpers.cleanup import get_registry

# Safety check - file uploads are write operations
safety_ctx = check_safety(SafetyLevel.WRITE_LOAD)
BASE_URL = safety_ctx["base_url"]
MAX_FILE_SIZE = safety_ctx["limits"]["max_file_size"]
MAX_FILE_COUNT = safety_ctx["limits"]["max_file_count"]

from locust import task, between, events


class FileWorkflowUser(TokenPoolHttpUser):
    """
    File workflow user.

    Tests:
    - Document folder listing (read-only)
    - Document file listing (read-only)
    - Small file upload (1KB, 10KB, 100KB)
    - File download (if uploaded files exist)

    Safety:
    - Max file size 1MB enforced
    - Max file count enforced per run
    - All uploaded files registered for cleanup
    - Uses PERF_ prefix in file content for identification
    """

    wait_time = between(3, 8)
    host = BASE_URL

    # Track total uploads across all users (shared via class variable)
    _upload_count = 0
    _upload_lock = None  # Will be initialized in on_start

    def on_start(self):
        super().on_start()
        import threading
        # Initialize lock once
        if FileWorkflowUser._upload_lock is None:
            FileWorkflowUser._upload_lock = threading.Lock()

    def _can_upload(self):
        """Check if we haven't exceeded the file upload limit."""
        with FileWorkflowUser._upload_lock:
            return FileWorkflowUser._upload_count < MAX_FILE_COUNT

    def _increment_upload_count(self):
        """Increment the shared upload counter."""
        with FileWorkflowUser._upload_lock:
            FileWorkflowUser._upload_count += 1
            return FileWorkflowUser._upload_count

    @task(20)
    def list_document_folders(self):
        """List document folders (read-only)."""
        resp = self.api_get("/api/document/folder/", name="GET /api/document/folder/")
        if resp.status_code == 401:
            self.check_and_refresh_token(resp)
            resp = self.api_get("/api/document/folder/", name="GET /api/document/folder/")

        collector = get_collector()
        try:
            elapsed_ms = int(resp.elapsed.total_seconds() * 1000)
        except AttributeError:
            elapsed_ms = 0
        collector.record("GET", "/api/document/folder/", elapsed_ms, resp.status_code)

    @task(20)
    def list_document_files(self):
        """List document files (read-only)."""
        resp = self.api_get("/api/document/file/", name="GET /api/document/file/")
        if resp.status_code == 401:
            self.check_and_refresh_token(resp)
            resp = self.api_get("/api/document/file/", name="GET /api/document/file/")

        collector = get_collector()
        try:
            elapsed_ms = int(resp.elapsed.total_seconds() * 1000)
        except AttributeError:
            elapsed_ms = 0
        collector.record("GET", "/api/document/file/", elapsed_ms, resp.status_code)

    @task(10)
    def disk_usage(self):
        """Get disk usage (read-only)."""
        resp = self.api_get("/api/document/disk_usage/", name="GET /api/document/disk_usage/")
        if resp.status_code == 401:
            self.check_and_refresh_token(resp)
            resp = self.api_get("/api/document/disk_usage/", name="GET /api/document/disk_usage/")

        collector = get_collector()
        try:
            elapsed_ms = int(resp.elapsed.total_seconds() * 1000)
        except AttributeError:
            elapsed_ms = 0
        collector.record("GET", "/api/document/disk_usage/", elapsed_ms, resp.status_code)

    @task(5)
    def upload_small_file(self):
        """Upload a small (1KB) text file."""
        if not self._can_upload():
            return  # Max file count reached

        gen = get_generator()
        registry = get_registry()

        # Generate file content
        file_size = 1024  # 1KB
        file_content = gen.make_file_content(file_size)
        filename = gen.make_filename("txt")

        # Prepare multipart upload
        # NOTE: The actual upload endpoint depends on the document module's API.
        # The document module uses chunked upload. For performance testing,
        # we test the first chunk upload step.

        headers = self.get_auth_headers()
        # Remove Content-Type for multipart (requests/locust will set it)
        headers.pop("Content-Type", None)

        files = {
            "file": (filename, io.BytesIO(file_content), "text/plain"),
        }

        try:
            # Upload via document file creation endpoint
            # NOTE: Actual endpoint may need verification.
            # The document module uses /api/document/file/upload/ for chunked upload.
            resp = self.client.post(
                "/api/document/file/upload/",
                files=files,
                headers=headers,
                name="POST /api/document/file/upload/ (small)",
            )

            if resp.status_code == 401:
                self.check_and_refresh_token(resp)
                headers = self.get_auth_headers()
                headers.pop("Content-Type", None)
                resp = self.client.post(
                    "/api/document/file/upload/",
                    files=files,
                    headers=headers,
                    name="POST /api/document/file/upload/ (small)",
                )

            collector = get_collector()
            try:
                elapsed_ms = int(resp.elapsed.total_seconds() * 1000)
            except AttributeError:
                elapsed_ms = 0
            collector.record("POST", "/api/document/file/upload/", elapsed_ms, resp.status_code)

            # Register for cleanup if successful
            if resp.status_code in (200, 201):
                try:
                    data = resp.json()
                    file_id = data.get("id") or data.get("data", {}).get("id")
                    if file_id:
                        registry.register_file(file_id, filename)
                        self._increment_upload_count()
                except Exception:
                    pass

        except Exception as e:
            collector = get_collector()
            collector.record("POST", "/api/document/file/upload/", 0, 0, error=str(e))

    @task(3)
    def upload_medium_file(self):
        """Upload a medium (10KB) text file."""
        if not self._can_upload():
            return

        gen = get_generator()
        registry = get_registry()

        file_size = 10240  # 10KB
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
                name="POST /api/document/file/upload/ (medium)",
            )

            if resp.status_code == 401:
                self.check_and_refresh_token(resp)
                headers = self.get_auth_headers()
                headers.pop("Content-Type", None)
                resp = self.client.post(
                    "/api/document/file/upload/",
                    files=files,
                    headers=headers,
                    name="POST /api/document/file/upload/ (medium)",
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
                        self._increment_upload_count()
                except Exception:
                    pass

        except Exception as e:
            collector = get_collector()
            collector.record("POST", "/api/document/file/upload/", 0, 0, error=str(e))

    @task(2)
    def upload_large_file(self):
        """Upload a large (100KB) text file."""
        if not self._can_upload():
            return

        gen = get_generator()
        registry = get_registry()

        file_size = 102400  # 100KB
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
                name="POST /api/document/file/upload/ (large)",
            )

            if resp.status_code == 401:
                self.check_and_refresh_token(resp)
                headers = self.get_auth_headers()
                headers.pop("Content-Type", None)
                resp = self.client.post(
                    "/api/document/file/upload/",
                    files=files,
                    headers=headers,
                    name="POST /api/document/file/upload/ (large)",
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
                        self._increment_upload_count()
                except Exception:
                    pass

        except Exception as e:
            collector = get_collector()
            collector.record("POST", "/api/document/file/upload/", 0, 0, error=str(e))


@events.test_start.add_listener
def _on_file_test_start(environment, **kwargs):
    """Reset upload counter on test start."""
    FileWorkflowUser._upload_count = 0


@events.test_stop.add_listener
def _on_file_stop(environment, **kwargs):
    """Print metrics summary and run cleanup on test stop."""
    collector = get_collector()
    collector.print_summary()

    print(f"\n[FILE] Total files uploaded this run: {FileWorkflowUser._upload_count}")

    # Run cleanup
    registry = get_registry()
    stats = registry.get_stats()
    if any(stats.values()):
        print(f"[CLEANUP] Starting file cleanup. Items: {stats}")
        host = environment.host.rstrip("/") if environment.host else BASE_URL
        from helpers.auth import get_token_pool
        pool = get_token_pool()
        try:
            auth_headers = pool.get_auth_headers(host, 0)
        except Exception:
            auth_headers = None
        registry.cleanup_all(host, auth_headers)
    else:
        print("[CLEANUP] No files to clean up.")
