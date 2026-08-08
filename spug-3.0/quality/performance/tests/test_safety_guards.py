#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for performance safety guards.

Validates: fail-closed behavior, forbidden URLs, forbidden databases,
write protection, container checks.

Tests the actual API in helpers/safety.py:
- SafetyLevel enum
- check_safety() function (exits on failure)
- get_safety_context() function
- SafetyCheckError exception
"""

import os
import sys
import pytest
from pathlib import Path

# Add performance root to path
PERF_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PERF_ROOT))

from helpers.safety import SafetyLevel, SafetyCheckError, _get_env, _load_env_file


class TestSafetyLevelEnum:
    """Test SafetyLevel enum values."""

    def test_safety_levels_exist(self):
        """Test all expected safety levels exist."""
        assert hasattr(SafetyLevel, "STATIC_INVENTORY")
        assert hasattr(SafetyLevel, "SINGLE_PROBE")
        assert hasattr(SafetyLevel, "READ_ONLY")
        assert hasattr(SafetyLevel, "WRITE_LOAD")

    def test_safety_level_ordering(self):
        """Test safety levels are ordered correctly."""
        levels = list(SafetyLevel)
        assert levels.index(SafetyLevel.STATIC_INVENTORY) < levels.index(SafetyLevel.READ_ONLY)
        assert levels.index(SafetyLevel.READ_ONLY) < levels.index(SafetyLevel.WRITE_LOAD)


class TestEnvironmentVariableChecks:
    """Test individual environment variable checks."""

    def test_get_env_returns_default(self):
        """Test _get_env returns default when var not set."""
        val = _get_env("NONEXISTENT_VAR_12345", "default_value")
        assert val == "default_value"

    def test_get_env_returns_value(self, monkeypatch):
        """Test _get_env returns actual value when set."""
        monkeypatch.setenv("TEST_VAR_12345", "test_value")
        val = _get_env("TEST_VAR_12345", "default")
        assert val == "test_value"

    def test_check_base_url_missing(self, monkeypatch):
        """Test that missing BASE_URL raises SafetyCheckError."""
        from helpers.safety import _check_base_url
        monkeypatch.delenv("BASE_URL", raising=False)
        with pytest.raises(SafetyCheckError):
            _check_base_url()

    def test_check_allow_performance_test_missing(self, monkeypatch):
        """Test that missing ALLOW_PERFORMANCE_TEST raises SafetyCheckError."""
        from helpers.safety import _check_allow_performance_test
        monkeypatch.delenv("ALLOW_PERFORMANCE_TEST", raising=False)
        with pytest.raises(SafetyCheckError):
            _check_allow_performance_test()

    def test_check_allow_performance_test_false(self, monkeypatch):
        """Test that ALLOW_PERFORMANCE_TEST=false raises SafetyCheckError."""
        from helpers.safety import _check_allow_performance_test
        monkeypatch.setenv("ALLOW_PERFORMANCE_TEST", "false")
        with pytest.raises(SafetyCheckError):
            _check_allow_performance_test()

    def test_check_allow_performance_test_true(self, monkeypatch):
        """Test that ALLOW_PERFORMANCE_TEST=true passes."""
        from helpers.safety import _check_allow_performance_test
        monkeypatch.setenv("ALLOW_PERFORMANCE_TEST", "true")
        _check_allow_performance_test()  # Should not raise

    def test_check_allow_write_load_missing(self, monkeypatch):
        """Test that missing ALLOW_WRITE_LOAD raises SafetyCheckError."""
        from helpers.safety import _check_allow_write_load
        monkeypatch.delenv("ALLOW_WRITE_LOAD", raising=False)
        with pytest.raises(SafetyCheckError):
            _check_allow_write_load()

    def test_check_allow_write_load_true(self, monkeypatch):
        """Test that ALLOW_WRITE_LOAD=true passes."""
        from helpers.safety import _check_allow_write_load
        monkeypatch.setenv("ALLOW_WRITE_LOAD", "true")
        _check_allow_write_load()  # Should not raise


class TestForbiddenChecks:
    """Test forbidden URL and database name checks."""

    def test_forbidden_server_names_default(self, monkeypatch):
        """Test that default forbidden server names include tdyw."""
        from helpers.safety import _check_forbidden_server_names, _check_url_is_allowed
        monkeypatch.setenv("FORBIDDEN_SERVER_NAMES", "tdyw,tdyw-test")
        parsed = _check_url_is_allowed("http://tdyw")
        with pytest.raises(SafetyCheckError):
            _check_forbidden_server_names(parsed)

    def test_forbidden_db_names_default(self, monkeypatch):
        """Test that default forbidden DB names include spug."""
        from helpers.safety import _check_forbidden_db_names
        monkeypatch.setenv("DB_NAME", "spug")
        monkeypatch.delenv("DB_DATABASE", raising=False)
        monkeypatch.delenv("MYSQL_DB", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(SafetyCheckError):
            _check_forbidden_db_names()

    def test_test_db_name_allowed(self, monkeypatch):
        """Test that a test DB name not containing 'spug' is not forbidden."""
        from helpers.safety import _check_forbidden_db_names
        # Use a name that doesn't contain 'spug' (safety.py checks substring)
        monkeypatch.setenv("DB_NAME", "test_database_001")
        monkeypatch.delenv("DB_DATABASE", raising=False)
        monkeypatch.delenv("MYSQL_DB", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        _check_forbidden_db_names()  # Should not raise

    def test_db_name_has_test_token(self, monkeypatch):
        """Test that test DB name token check passes for test_database."""
        from helpers.safety import _check_db_name_has_test_token
        monkeypatch.setenv("DB_NAME", "test_database_001")
        monkeypatch.delenv("DB_DATABASE", raising=False)
        monkeypatch.delenv("MYSQL_DB", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        _check_db_name_has_test_token()  # Should not raise

    def test_db_name_missing_token_fails(self, monkeypatch):
        """Test that DB name without test token fails."""
        from helpers.safety import _check_db_name_has_test_token
        monkeypatch.setenv("DB_NAME", "production_db")
        monkeypatch.delenv("DB_DATABASE", raising=False)
        monkeypatch.delenv("MYSQL_DB", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(SafetyCheckError):
            _check_db_name_has_test_token()

    def test_db_name_not_set_fails(self, monkeypatch):
        """Test that missing DB name fails for write tests."""
        from helpers.safety import _check_db_name_has_test_token
        monkeypatch.delenv("DB_NAME", raising=False)
        monkeypatch.delenv("DB_DATABASE", raising=False)
        monkeypatch.delenv("MYSQL_DB", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(SafetyCheckError):
            _check_db_name_has_test_token()


class TestMaxLimits:
    """Test max creation/file limits."""

    def test_max_create_limit_default(self, monkeypatch):
        """Test default max create limit."""
        from helpers.safety import _check_max_limits
        monkeypatch.delenv("MAX_CREATE_LIMIT", raising=False)
        monkeypatch.delenv("MAX_FILE_SIZE", raising=False)
        monkeypatch.delenv("MAX_FILE_COUNT", raising=False)
        limits = _check_max_limits()
        assert limits["max_create"] == 50
        assert limits["max_file_count"] == 10

    def test_max_create_limit_too_high(self, monkeypatch):
        """Test that max create limit > 100 fails."""
        from helpers.safety import _check_max_limits
        monkeypatch.setenv("MAX_CREATE_LIMIT", "200")
        with pytest.raises(SafetyCheckError):
            _check_max_limits()

    def test_max_file_count_too_high(self, monkeypatch):
        """Test that max file count > 20 fails."""
        from helpers.safety import _check_max_limits
        monkeypatch.setenv("MAX_FILE_COUNT", "50")
        with pytest.raises(SafetyCheckError):
            _check_max_limits()
