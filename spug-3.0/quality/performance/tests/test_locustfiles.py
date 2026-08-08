#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for performance locustfiles.

Validates: locustfile imports, task definitions, endpoint coverage.
Does NOT execute load tests - only static validation.
"""

import os
import sys
import ast
import pytest
from pathlib import Path

# Add performance root to path
PERF_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PERF_ROOT))

LOCUSTFILES_DIR = PERF_ROOT / "locustfiles"


def get_locustfiles():
    """Get all locustfiles."""
    return sorted(LOCUSTFILES_DIR.glob("*.py"))


@pytest.mark.parametrize("locustfile", get_locustfiles())
def test_locustfile_parseable(locustfile):
    """Test that each locustfile can be parsed as valid Python."""
    content = locustfile.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(locustfile))
    assert tree is not None, f"Failed to parse {locustfile.name}"


@pytest.mark.parametrize("locustfile", get_locustfiles())
def test_locustfile_has_safety_import(locustfile):
    """Test that each locustfile imports safety helpers."""
    content = locustfile.read_text(encoding="utf-8")
    assert "safety" in content.lower(), \
        f"{locustfile.name} does not import safety helpers"
    assert "check_safety" in content or "SafetyGuard" in content, \
        f"{locustfile.name} does not use check_safety or SafetyGuard"


@pytest.mark.parametrize("locustfile", get_locustfiles())
def test_locustfile_has_exit_on_unsafe(locustfile):
    """Test that each locustfile has exit mechanism for unsafe environment."""
    content = locustfile.read_text(encoding="utf-8")
    assert "sys.exit" in content or "check_safety" in content, \
        f"{locustfile.name} does not have exit mechanism (sys.exit or check_safety)"


def test_smoke_load_has_tasks():
    """Test smoke_load.py has task definitions."""
    content = (LOCUSTFILES_DIR / "smoke_load.py").read_text(encoding="utf-8")
    assert "@task" in content, "smoke_load.py has no @task decorators"


def test_read_workflows_coverage():
    """Test read_workflows.py covers key endpoints."""
    content = (LOCUSTFILES_DIR / "read_workflows.py").read_text(encoding="utf-8")
    required_endpoints = [
        "/api/home/",
        "/api/document/",
        "/api/device/",
        "/api/logs/",
    ]
    for endpoint in required_endpoints:
        assert endpoint in content, f"read_workflows.py missing endpoint pattern: {endpoint}"


def test_write_workflows_has_prefix():
    """Test write_workflows.py uses PERF_ prefix."""
    content = (LOCUSTFILES_DIR / "write_workflows.py").read_text(encoding="utf-8")
    assert "PERF" in content or "make_name" in content or "TestDataGenerator" in content, \
        "write_workflows.py does not use PERF_ prefix or TestDataGenerator"


def test_write_workflows_has_max_limit():
    """Test write_workflows.py has max creation limit."""
    content = (LOCUSTFILES_DIR / "write_workflows.py").read_text(encoding="utf-8")
    assert "max" in content.lower() or "limit" in content.lower() or "track_creation" in content, \
        "write_workflows.py does not enforce max creation limit"


def test_file_workflows_has_size_limit():
    """Test file_workflows.py has file size limit."""
    content = (LOCUSTFILES_DIR / "file_workflows.py").read_text(encoding="utf-8")
    assert "MAX_FILE" in content or "max_file" in content or "file_size" in content.lower(), \
        "file_workflows.py does not enforce file size/count limits"


def test_mixed_workflows_has_safety_branch():
    """Test mixed_workflows.py checks safety level."""
    content = (LOCUSTFILES_DIR / "mixed_workflows.py").read_text(encoding="utf-8")
    assert "WRITE" in content or "write" in content.lower(), \
        "mixed_workflows.py does not check write access level"


def test_no_production_urls():
    """Test no locustfile hardcodes production URLs."""
    for lf in get_locustfiles():
        content = lf.read_text(encoding="utf-8")
        # Allow "tdyw-test" but not bare "http://tdyw" without "-test"
        lines = content.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "http://tdyw" in stripped and "tdyw-test" not in stripped and "tdyw-drill" not in stripped:
                if "forbidden" not in stripped.lower() and "not" not in stripped.lower():
                    pytest.fail(f"{lf.name} may contain production URL: {stripped}")
