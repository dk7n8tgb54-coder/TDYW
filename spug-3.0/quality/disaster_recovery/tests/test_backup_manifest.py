#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for backup manifest parsing and validation.

Tests the actual API in helpers/manifest.py:
- load_inventory(path) -> BackupInventory
- validate_inventory(inventory) -> ValidationResult
- get_objects_by_risk(inventory, risk) -> List[BackupObject]
- get_unverified_objects(inventory) -> List[BackupObject]
"""

import os
import sys
import re
import pytest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None
    pytest.skip("PyYAML not installed", allow_module_level=True)

# Add DR root to path
DR_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(DR_ROOT))

from helpers.manifest import (
    load_inventory,
    validate_inventory,
    get_objects_by_risk,
    get_unverified_objects,
    get_undocumented_objects,
    BackupInventory,
    ValidationResult,
)

BACKUP_INVENTORY = DR_ROOT / "backup_inventory.yml"


class TestBackupInventoryFile:
    """Test backup_inventory.yml file structure."""

    def test_inventory_exists(self):
        """Test backup_inventory.yml exists."""
        assert BACKUP_INVENTORY.exists()

    def test_inventory_valid_yaml(self):
        """Test backup_inventory.yml is valid YAML."""
        data = yaml.safe_load(BACKUP_INVENTORY.read_text(encoding="utf-8"))
        assert data is not None

    def test_inventory_has_version(self):
        """Test inventory has version field."""
        data = yaml.safe_load(BACKUP_INVENTORY.read_text(encoding="utf-8"))
        assert "inventory_version" in data or "version" in data

    def test_inventory_has_objects(self):
        """Test inventory has objects section."""
        data = yaml.safe_load(BACKUP_INVENTORY.read_text(encoding="utf-8"))
        assert "objects" in data or "components" in data

    def test_no_passwords_in_inventory(self):
        """Test no plaintext passwords in inventory."""
        content = BACKUP_INVENTORY.read_text(encoding="utf-8")
        patterns = [
            r"password\s*[=:]\s*['\"]\S+",
            r"passwd\s*[=:]\s*['\"]\S+",
            r"secret\s*[=:]\s*['\"]\S{10,}",
            r"token\s*[=:]\s*['\"]\S{20,}",
        ]
        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            assert len(matches) == 0, f"Potential secret found in backup_inventory.yml: {pattern}"


class TestLoadInventory:
    """Test load_inventory function."""

    def test_load_returns_backup_inventory(self):
        """Test that load_inventory returns BackupInventory."""
        inv = load_inventory(str(BACKUP_INVENTORY))
        assert isinstance(inv, BackupInventory)

    def test_loaded_inventory_has_objects(self):
        """Test that loaded inventory has objects."""
        inv = load_inventory(str(BACKUP_INVENTORY))
        assert len(inv.objects) > 0

    def test_loaded_inventory_has_systems(self):
        """Test that loaded inventory has systems."""
        inv = load_inventory(str(BACKUP_INVENTORY))
        assert len(inv.systems) > 0

    def test_loaded_inventory_has_version(self):
        """Test that loaded inventory has version."""
        inv = load_inventory(str(BACKUP_INVENTORY))
        assert inv.version != ""


class TestValidateInventory:
    """Test validate_inventory function."""

    def test_validate_returns_validation_result(self):
        """Test that validate_inventory returns ValidationResult."""
        inv = load_inventory(str(BACKUP_INVENTORY))
        result = validate_inventory(inv)
        assert isinstance(result, ValidationResult)

    def test_validate_has_errors_list(self):
        """Test that validation result has errors list."""
        inv = load_inventory(str(BACKUP_INVENTORY))
        result = validate_inventory(inv)
        assert isinstance(result.errors, list)

    def test_validate_has_object_count(self):
        """Test that validation result has object count."""
        inv = load_inventory(str(BACKUP_INVENTORY))
        result = validate_inventory(inv)
        assert result.object_count > 0


class TestQueryFunctions:
    """Test query helper functions."""

    def test_get_objects_by_risk_critical(self):
        """Test getting critical objects."""
        inv = load_inventory(str(BACKUP_INVENTORY))
        critical = get_objects_by_risk(inv, "critical")
        assert isinstance(critical, list)
        # We should have at least some critical objects
        assert len(critical) > 0

    def test_get_objects_by_risk_low(self):
        """Test getting low risk objects."""
        inv = load_inventory(str(BACKUP_INVENTORY))
        low = get_objects_by_risk(inv, "low")
        assert isinstance(low, list)

    def test_get_unverified_objects(self):
        """Test getting unverified objects."""
        inv = load_inventory(str(BACKUP_INVENTORY))
        unverified = get_unverified_objects(inv)
        assert isinstance(unverified, list)
        # Most objects should be unverified (restore not tested)
        assert len(unverified) > 0

    def test_get_undocumented_objects(self):
        """Test getting undocumented objects."""
        inv = load_inventory(str(BACKUP_INVENTORY))
        undocumented = get_undocumented_objects(inv)
        assert isinstance(undocumented, list)
