"""
Test data generation for performance testing.

All generated data uses the PERF_ prefix for identification and cleanup.
Max creation limits are enforced to prevent runaway data creation.

Usage:

    from helpers.test_data import TestDataGenerator

    gen = TestDataGenerator()
    record = gen.make_record("radio_license", seq=1)
    # record = {"license_no": "PERF-LIC-1", "station_name": "PERF测试台站1", ...}
"""

import os
import sys
import threading
import time
import uuid
import random
import string
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from helpers.safety import get_safety_context


class TestDataGenerator:
    """
    Generates test data with PERF_ prefix.

    Features:
    - All data uses PERF_ prefix for identification
    - Max creation limit enforced per entity type
    - Thread-safe counter for sequence numbers
    - Unique UUID suffix for collision avoidance
    """

    # Templates for each entity type
    TEMPLATES = {
        "radio_license": {
            "license_no": "PERF-LIC-{seq}",
            "station_name": "PERF测试台站{seq}",
            "frequency": "98.5",
            "power": "100",
            "applicant": "PERF测试申请人",
        },
        "station_frequency_approval": {
            "approval_no": "PERF-APP-{seq}",
            "station_name": "PERF测试台站{seq}",
            "frequency": "98.5",
            "power": "100",
        },
        "contract_agreement": {
            "title": "PERF测试合同{seq}",
            "contract_no": "PERF-CON-{seq}",
            "party_a": "PERF甲方",
            "party_b": "PERF乙方",
            "amount": "10000",
        },
        "runlog": {
            "title": "PERF测试跨日事项{seq}",
            "content": "PERF自动化测试创建的跨日事项记录",
            "duty_person": "PERF测试人",
        },
        "duty_log": {
            "title": "PERF测试值班日志{seq}",
            "content": "PERF自动化测试创建的值班日志",
            "shift": "day",
        },
        "dept_duty_log": {
            "department": "PERF测试部门",
            "content": "PERF自动化测试创建的部门值班日志",
        },
        "interference": {
            "title": "PERF测试干扰记录{seq}",
            "description": "PERF自动化测试创建的干扰记录",
            "frequency": "98.5",
            "location": "PERF测试地点",
        },
        "fault": {
            "title": "PERF测试故障记录{seq}",
            "description": "PERF自动化测试创建的故障记录",
            "device_name": "PERF测试设备",
            "fault_type": "hardware",
        },
        "reminder": {
            "title": "PERF测试提醒{seq}",
            "content": "PERF自动化测试创建的提醒事项",
        },
        "device": {
            "name": "PERF测试设备{seq}",
            "model": "PERF-MODEL-001",
            "manufacturer": "PERF测试厂商",
        },
        "upgrade": {
            "title": "PERF测试升级记录{seq}",
            "description": "PERF自动化测试创建的升级记录",
            "version": f"PERF-v1.0.{int(time.time()) % 1000}",
        },
        "regulation": {
            "title": "PERF测试规章{seq}",
            "content": "PERF自动化测试创建的规章内容",
            "category": "PERF测试分类",
        },
        "document_folder": {
            "name": "PERF测试文件夹{seq}",
        },
        "document_file": {
            "name": "PERF测试文件{seq}.txt",
            "description": "PERF自动化测试文件",
        },
        "notice": {
            "title": "PERF测试公告{seq}",
            "content": "PERF自动化测试创建的公告内容",
        },
        "navigation": {
            "name": "PERF测试导航{seq}",
            "icon": "dashboard",
            "path": f"/perf/test/{int(time.time()) % 10000}",
        },
    }

    def __init__(self):
        ctx = get_safety_context()
        self.prefix = ctx["prefix"]
        self.max_create = ctx["limits"]["max_create"]
        self._counters = {}  # entity_type -> current count
        self._created_ids = {}  # entity_type -> list of IDs for cleanup
        self._lock = threading.Lock()

    def make_record(self, entity_type, seq=None):
        """
        Generate a test data record for the given entity type.

        Args:
            entity_type: Key in TEMPLATES
            seq: Optional sequence number. Auto-incremented if None.

        Returns:
            dict with generated field values

        Raises:
            ValueError if max creation limit is exceeded
        """
        if entity_type not in self.TEMPLATES:
            raise ValueError(f"Unknown entity type: {entity_type}")

        with self._lock:
            current_count = self._counters.get(entity_type, 0)
            if current_count >= self.max_create:
                raise ValueError(
                    f"Max creation limit ({self.max_create}) reached for '{entity_type}'. "
                    f" refusing to create more."
                )
            if seq is None:
                seq = current_count + 1
            self._counters[entity_type] = current_count + 1

        template = self.TEMPLATES[entity_type]
        record = {}
        for key, value in template.items():
            if "{seq}" in str(value):
                record[key] = value.replace("{seq}", str(seq))
            else:
                record[key] = value

        # Add unique run ID for traceability
        record["_perf_run_id"] = self._get_run_id()
        record["_perf_seq"] = seq
        record["_perf_entity_type"] = entity_type

        return record

    def register_created_id(self, entity_type, record_id):
        """Register a created record ID for later cleanup."""
        with self._lock:
            self._created_ids.setdefault(entity_type, []).append(record_id)

    def get_created_ids(self, entity_type=None):
        """Get created IDs for cleanup."""
        with self._lock:
            if entity_type:
                return list(self._created_ids.get(entity_type, []))
            return {k: list(v) for k, v in self._created_ids.items()}

    def get_all_created(self):
        """Get all created IDs across all entity types."""
        with self._lock:
            return {k: list(v) for k, v in self._created_ids.items()}

    def get_count(self, entity_type):
        """Get the number of records created for this entity type."""
        with self._lock:
            return self._counters.get(entity_type, 0)

    def get_total_count(self):
        """Get total records created across all entity types."""
        with self._lock:
            return sum(self._counters.values())

    def _get_run_id(self):
        """Get or create a unique run ID for this test session."""
        if not hasattr(self, "_run_id"):
            self._run_id = uuid.uuid4().hex[:8]
        return self._run_id

    def make_file_content(self, size_bytes=1024):
        """
        Generate file content of specified size for upload tests.

        Args:
            size_bytes: Desired file size (max MAX_FILE_SIZE from env)

        Returns:
            bytes: File content
        """
        ctx = get_safety_context()
        max_size = ctx["limits"]["max_file_size"]
        if size_bytes > max_size:
            raise ValueError(
                f"Requested file size {size_bytes} exceeds max allowed {max_size}"
            )

        # Generate content with PERF_ prefix for identification
        prefix = self.prefix.encode("utf-8")
        filler = b"0" * (size_bytes - len(prefix))
        return prefix + filler

    def make_filename(self, extension="txt"):
        """Generate a unique filename with PERF_ prefix."""
        run_id = self._get_run_id()
        seq = int(time.time() * 1000) % 1000000
        return f"{self.prefix}test_{run_id}_{seq}.{extension}"

    def reset(self):
        """Reset counters and created IDs. Called between test runs."""
        with self._lock:
            self._counters.clear()
            self._created_ids.clear()


# --- Global instance ---
_generator = None


def get_generator():
    """Get the global TestDataGenerator singleton."""
    global _generator
    if _generator is None:
        _generator = TestDataGenerator()
    return _generator
