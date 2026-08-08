#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for threshold configuration.

Validates: threshold.yml format, required fields, category structure.
"""

import os
import sys
import pytest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None
    pytest.skip("PyYAML not installed", allow_module_level=True)

THRESHOLDS_FILE = Path(__file__).parent.parent / "thresholds.yml"
APPROVED_FILE = Path(__file__).parent.parent / "baselines" / "approved_thresholds.yml"


def test_thresholds_yaml_valid():
    """Test thresholds.yml is valid YAML."""
    content = THRESHOLDS_FILE.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    assert data is not None


def test_thresholds_has_version():
    """Test thresholds.yml has version."""
    data = yaml.safe_load(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    assert "version" in data
    assert "status" in data


def test_thresholds_has_endpoint_section():
    """Test thresholds.yml has endpoint thresholds."""
    data = yaml.safe_load(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    assert "endpoints" in data
    assert len(data["endpoints"]) > 0


def test_thresholds_endpoint_fields():
    """Test each endpoint threshold has required fields."""
    data = yaml.safe_load(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    for ep in data["endpoints"]:
        assert "pattern" in ep, f"Endpoint missing 'pattern': {ep}"
        assert "target_p95_ms" in ep, f"Endpoint missing 'target_p95_ms': {ep.get('pattern')}"
        assert "blocking_p95_ms" in ep, f"Endpoint missing 'blocking_p95_ms': {ep.get('pattern')}"


def test_thresholds_has_system_section():
    """Test thresholds.yml has system-level thresholds."""
    data = yaml.safe_load(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    assert "system" in data
    sys_data = data["system"]
    assert "max_error_rate" in sys_data
    assert "max_db_connections" in sys_data


def test_thresholds_has_environment_anomalies():
    """Test thresholds.yml has environment anomaly section."""
    data = yaml.safe_load(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    assert "environment_anomalies" in data


def test_approved_thresholds_empty_or_valid():
    """Test approved_thresholds.yml is either empty or has valid structure."""
    data = yaml.safe_load(APPROVED_FILE.read_text(encoding="utf-8"))
    assert data is not None
    # The DR builder's version uses 'baselines' key (empty dict when no baselines)
    assert "baselines" in data, "approved_thresholds.yml missing 'baselines' key"
    # When empty, baselines should be an empty dict
    if data["baselines"]:
        # If not empty, each baseline should have metrics
        for name, baseline in data["baselines"].items():
            assert "metrics" in baseline or "date" in baseline, \
                f"Baseline '{name}' missing required fields"


def test_blocking_higher_than_target():
    """Test blocking thresholds are higher than target thresholds."""
    data = yaml.safe_load(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    for ep in data["endpoints"]:
        if "target_p95_ms" in ep and "blocking_p95_ms" in ep:
            if ep["target_p95_ms"] is not None and ep["blocking_p95_ms"] is not None:
                assert ep["blocking_p95_ms"] > ep["target_p95_ms"], \
                    f"Blocking should be higher than target for {ep['pattern']}"
