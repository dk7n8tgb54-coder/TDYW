#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for restore validation logic.

Validates: database validator functions, file validator functions,
checksum validator functions, application validator functions.

Tests the actual function-based API in validators/:
- database_validator: check_django_check, check_table_existence, etc.
- file_validator: check_file_count, check_total_size, etc.
- checksum_validator: compute_sha256, verify_full, verify_sampled
- application_validator: check_login, check_list_endpoints, etc.
"""

import os
import sys
import tempfile
import json
import hashlib
import pytest
from pathlib import Path

# Add DR root to path
DR_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(DR_ROOT))


class TestChecksumValidator:
    """Test checksum validator functions."""

    def test_compute_sha256_file(self):
        """Test SHA256 computation of a file."""
        from validators.checksum_validator import compute_sha256

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test content for checksum")
            f.flush()
            filepath = f.name

        try:
            h = compute_sha256(filepath)
            assert len(h) == 64  # SHA256 hex length
            assert all(c in "0123456789abcdef" for c in h)
        finally:
            os.unlink(filepath)

    def test_compute_sha256_consistent(self):
        """Test SHA256 is consistent for same content."""
        from validators.checksum_validator import compute_sha256

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("same content")
            f.flush()
            filepath = f.name

        try:
            h1 = compute_sha256(filepath)
            h2 = compute_sha256(filepath)
            assert h1 == h2
        finally:
            os.unlink(filepath)

    def test_compute_sha256_different_content(self):
        """Test SHA256 differs for different content."""
        from validators.checksum_validator import compute_sha256

        files = []
        for i in range(2):
            f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
            f.write(f"content {i}")
            f.flush()
            files.append(f.name)
            f.close()

        try:
            h1 = compute_sha256(files[0])
            h2 = compute_sha256(files[1])
            assert h1 != h2
        finally:
            for fp in files:
                os.unlink(fp)

    def test_load_sha256sums(self):
        """Test loading SHA256SUMS file."""
        from validators.checksum_validator import load_sha256sums

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("abc123  file1.txt\n")
            f.write("def456  file2.txt\n")
            f.flush()
            filepath = f.name

        try:
            sums = load_sha256sums(filepath)
            assert "file1.txt" in sums
            assert sums["file1.txt"] == "abc123"
            assert "file2.txt" in sums
            assert sums["file2.txt"] == "def456"
        finally:
            os.unlink(filepath)

    def test_verify_full_all_present(self):
        """Test verify_full with all files present."""
        from validators.checksum_validator import compute_sha256, verify_full

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            for i in range(3):
                with open(os.path.join(tmpdir, f"file_{i}.txt"), "w") as f:
                    f.write(f"content {i}")

            # Create SHA256SUMS
            sums_path = os.path.join(tmpdir, "SHA256SUMS")
            with open(sums_path, "w") as f:
                for i in range(3):
                    h = compute_sha256(os.path.join(tmpdir, f"file_{i}.txt"))
                    f.write(f"{h}  file_{i}.txt\n")

            result = verify_full(tmpdir, sums_path)
            assert result.passed is True
            assert result.data.get("total", 0) == 3


class TestDatabaseValidator:
    """Test database validator function-based API."""

    def test_check_django_check_exists(self):
        """Test that check_django_check function exists."""
        from validators.database_validator import check_django_check
        assert callable(check_django_check)

    def test_check_table_existence_exists(self):
        """Test that check_table_existence function exists."""
        from validators.database_validator import check_table_existence
        assert callable(check_table_existence)

    def test_check_migration_consistency_exists(self):
        """Test that check_migration_consistency function exists."""
        from validators.database_validator import check_migration_consistency
        assert callable(check_migration_consistency)

    def test_check_tenant_user_permission_exists(self):
        """Test that check_tenant_user_permission function exists."""
        from validators.database_validator import check_tenant_user_permission
        assert callable(check_tenant_user_permission)

    def test_check_orphan_fk_exists(self):
        """Test that check_orphan_fk function exists."""
        from validators.database_validator import check_orphan_fk
        assert callable(check_orphan_fk)

    def test_check_audit_log_structure_exists(self):
        """Test that check_audit_log_structure function exists."""
        from validators.database_validator import check_audit_log_structure
        assert callable(check_audit_log_structure)

    def test_run_all_exists(self):
        """Test that run_all function exists."""
        from validators.database_validator import run_all
        assert callable(run_all)

    def test_check_django_check_returns_result(self):
        """Test that check_django_check returns a result."""
        from validators.database_validator import check_django_check
        result = check_django_check({"DR_TARGET_DB_CONTAINER": "nonexistent"})
        assert hasattr(result, "passed") or hasattr(result, "valid")


class TestFileValidator:
    """Test file validator function-based API."""

    def test_check_file_count_exists(self):
        """Test that check_file_count function exists."""
        from validators.file_validator import check_file_count
        assert callable(check_file_count)

    def test_check_total_size_exists(self):
        """Test that check_total_size function exists."""
        from validators.file_validator import check_total_size
        assert callable(check_total_size)

    def test_check_db_file_mapping_exists(self):
        """Test that check_db_file_mapping function exists."""
        from validators.file_validator import check_db_file_mapping
        assert callable(check_db_file_mapping)

    def test_check_file_permissions_exists(self):
        """Test that check_file_permissions function exists."""
        from validators.file_validator import check_file_permissions
        assert callable(check_file_permissions)

    def test_run_all_exists(self):
        """Test that run_all function exists."""
        from validators.file_validator import run_all
        assert callable(run_all)

    def test_count_files_local(self):
        """Test count_files function with local directory."""
        from validators.file_validator import count_files
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                with open(os.path.join(tmpdir, f"f{i}.txt"), "w") as f:
                    f.write("x")
            counts = count_files(tmpdir)
            assert isinstance(counts, dict)


class TestApplicationValidator:
    """Test application validator function-based API."""

    def test_check_login_exists(self):
        """Test that check_login function exists."""
        from validators.application_validator import check_login
        assert callable(check_login)

    def test_check_list_endpoints_exists(self):
        """Test that check_list_endpoints function exists."""
        from validators.application_validator import check_list_endpoints
        assert callable(check_list_endpoints)

    def test_check_detail_endpoint_exists(self):
        """Test that check_detail_endpoint function exists."""
        from validators.application_validator import check_detail_endpoint
        assert callable(check_detail_endpoint)

    def test_check_crud_workflow_exists(self):
        """Test that check_crud_workflow function exists."""
        from validators.application_validator import check_crud_workflow
        assert callable(check_crud_workflow)

    def test_run_all_exists(self):
        """Test that run_all function exists."""
        from validators.application_validator import run_all
        assert callable(run_all)
