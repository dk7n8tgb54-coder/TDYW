#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for DR environment guard.

Validates: fail-closed behavior, forbidden databases, forbidden containers,
restore drill protection.

Tests the actual function-based API in helpers/environment_guard.py:
- run_all_checks(env_dict) -> GuardReport
- check_allow_restore_drill(env) -> CheckResult
- check_target_db_name(env) -> CheckResult
- check_target_db_container(env) -> CheckResult
- check_file_restore_path(env) -> CheckResult
"""

import os
import sys
import pytest
from pathlib import Path

# Add DR root to path
DR_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(DR_ROOT))

from helpers.environment_guard import (
    run_all_checks,
    check_allow_restore_drill,
    check_target_db_name,
    check_target_db_container,
    check_file_restore_path,
    ALLOWED_DB_NAME_PATTERNS,
    FORBIDDEN_DB_NAMES,
    FORBIDDEN_CONTAINERS,
    FORBIDDEN_FILE_PATHS,
    GuardReport,
    CheckResult,
)


class TestCheckAllowRestoreDrill:
    """Test ALLOW_RESTORE_DRILL flag check."""

    def test_missing_flag_fails(self):
        """Missing ALLOW_RESTORE_DRILL should fail."""
        result = check_allow_restore_drill({})
        assert result.passed is False

    def test_false_flag_fails(self):
        """ALLOW_RESTORE_DRILL=false should fail."""
        result = check_allow_restore_drill({"ALLOW_RESTORE_DRILL": "false"})
        assert result.passed is False

    def test_true_flag_passes(self):
        """ALLOW_RESTORE_DRILL=true should pass."""
        result = check_allow_restore_drill({"ALLOW_RESTORE_DRILL": "true"})
        assert result.passed is True


class TestCheckTargetDbName:
    """Test database name validation."""

    def test_missing_db_name_fails(self):
        """Missing DR_TARGET_DB should fail."""
        result = check_target_db_name({})
        assert result.passed is False

    def test_dev_db_blocked(self):
        """Dev database (spug) should be blocked."""
        result = check_target_db_name({"DR_TARGET_DB": "spug"})
        assert result.passed is False

    def test_production_db_blocked(self):
        """Production database should be blocked."""
        result = check_target_db_name({"DR_TARGET_DB": "spug_prod"})
        assert result.passed is False

    def test_test_db_allowed(self):
        """Test database should be allowed."""
        result = check_target_db_name({"DR_TARGET_DB": "test_database_001"})
        assert result.passed is True

    def test_perf_db_allowed(self):
        """Perf database should be allowed."""
        result = check_target_db_name({"DR_TARGET_DB": "perf_db_001"})
        assert result.passed is True

    def test_drill_db_allowed(self):
        """Drill database should be allowed."""
        result = check_target_db_name({"DR_TARGET_DB": "drill_db_001"})
        assert result.passed is True


class TestCheckTargetDbContainer:
    """Test target container validation."""

    def test_missing_container_fails(self):
        """Missing DR_TARGET_DB_CONTAINER should fail."""
        result = check_target_db_container({})
        assert result.passed is False

    def test_production_container_blocked(self):
        """Production container (tdyw) should be blocked."""
        result = check_target_db_container({"DR_TARGET_DB_CONTAINER": "tdyw"})
        assert result.passed is False

    def test_test_container_blocked(self):
        """Dev test container (tdyw-test) should also be blocked."""
        result = check_target_db_container({"DR_TARGET_DB_CONTAINER": "tdyw-test"})
        assert result.passed is False

    def test_drill_container_allowed(self):
        """Drill container should be allowed."""
        result = check_target_db_container({"DR_TARGET_DB_CONTAINER": "tdyw-drill-001"})
        assert result.passed is True


class TestCheckFileRestorePath:
    """Test file restore path validation."""

    def test_missing_path_fails(self):
        """Missing DR_FILE_RESTORE_ROOT should fail."""
        result = check_file_restore_path({})
        assert result.passed is False

    def test_production_path_blocked(self):
        """Production file path should be blocked."""
        for forbidden_path in FORBIDDEN_FILE_PATHS:
            result = check_file_restore_path({"DR_FILE_RESTORE_ROOT": forbidden_path})
            assert result.passed is False, f"Path {forbidden_path} should be forbidden"

    def test_temp_path_allowed(self):
        """Temp file path should be allowed."""
        result = check_file_restore_path({"DR_FILE_RESTORE_ROOT": "/tmp/drill_files_001"})
        assert result.passed is True

    def test_drill_path_allowed(self):
        """Drill path should be allowed."""
        result = check_file_restore_path({"DR_FILE_RESTORE_ROOT": "/drill/restore_001"})
        assert result.passed is True


class TestRunAllChecks:
    """Test the combined run_all_checks function.

    Note: run_all_checks may call Docker subprocesses which can fail on
    Windows. Tests focus on verifying the report structure rather than
    the overall pass/fail result when Docker is unavailable.
    """

    def test_empty_env_returns_report(self):
        """Empty environment should return a GuardReport (even if checks fail)."""
        try:
            report = run_all_checks(env_dict={})
            assert isinstance(report, GuardReport)
            assert len(report.checks) > 0
        except OSError:
            pytest.skip("Docker not available on this system")

    def test_dev_env_has_failed_checks(self):
        """Dev environment should have failed checks."""
        try:
            report = run_all_checks(env_dict={
                "ALLOW_RESTORE_DRILL": "true",
                "DR_TARGET_DB": "spug",
                "DR_TARGET_DB_CONTAINER": "tdyw",
                "DR_FILE_RESTORE_ROOT": "/data/spug/storage",
            })
            assert isinstance(report, GuardReport)
            failed_count = sum(1 for c in report.checks if not c.passed)
            assert failed_count >= 2, f"Expected at least 2 failures, got {failed_count}"
        except OSError:
            pytest.skip("Docker not available on this system")

    def test_report_has_checks(self):
        """Report should contain individual check results."""
        try:
            report = run_all_checks(env_dict={})
            assert hasattr(report, "checks")
            assert len(report.checks) > 0
        except OSError:
            pytest.skip("Docker not available on this system")

    def test_report_checks_are_check_results(self):
        """Report checks should be CheckResult objects."""
        try:
            report = run_all_checks(env_dict={})
            for c in report.checks:
                assert isinstance(c, CheckResult)
                assert hasattr(c, "passed")
                assert hasattr(c, "name")
                assert hasattr(c, "detail")
        except OSError:
            pytest.skip("Docker not available on this system")

    def test_report_has_summary_method(self):
        """Report should have a summary() method."""
        try:
            report = run_all_checks(env_dict={})
            summary = report.summary()
            assert isinstance(summary, str)
            assert "GUARD" in summary.upper() or "OVERALL" in summary.upper() or "PASS" in summary.upper()
        except OSError:
            pytest.skip("Docker not available on this system")
