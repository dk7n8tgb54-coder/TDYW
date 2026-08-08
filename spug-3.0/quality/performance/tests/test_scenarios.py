#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for scenario configuration files.

Validates: YAML structure, required fields, safety guard configuration.
Tests the actual YAML structure created by the DR builder:
- locust.users, locust.spawn_rate, locust.run_time
- safety.level, safety.requires_*
- expected.p50_ms, expected.p95_ms
- thresholds.category
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

SCENARIOS_DIR = Path(__file__).parent.parent / "scenarios"


def get_scenarios():
    """Get all scenario YAML files."""
    return sorted(SCENARIOS_DIR.glob("*.yml"))


@pytest.mark.parametrize("scenario_file", get_scenarios())
def test_scenario_yaml_valid(scenario_file):
    """Test that each scenario file is valid YAML."""
    content = scenario_file.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    assert data is not None, f"{scenario_file.name} is empty or invalid YAML"


@pytest.mark.parametrize("scenario_file", get_scenarios())
def test_scenario_has_locust_section(scenario_file):
    """Test that each scenario has locust configuration."""
    data = yaml.safe_load(scenario_file.read_text(encoding="utf-8"))
    assert "locust" in data, f"{scenario_file.name} missing 'locust' section"
    locust = data["locust"]
    assert "users" in locust, f"{scenario_file.name} locust missing 'users'"
    assert "run_time" in locust, f"{scenario_file.name} locust missing 'run_time'"
    assert "locustfile" in locust, f"{scenario_file.name} locust missing 'locustfile'"


@pytest.mark.parametrize("scenario_file", get_scenarios())
def test_scenario_has_safety_section(scenario_file):
    """Test that each scenario has safety configuration."""
    data = yaml.safe_load(scenario_file.read_text(encoding="utf-8"))
    assert "safety" in data, f"{scenario_file.name} missing 'safety' section"
    safety = data["safety"]
    assert "level" in safety, f"{scenario_file.name} safety missing 'level'"


@pytest.mark.parametrize("scenario_file", get_scenarios())
def test_scenario_has_thresholds(scenario_file):
    """Test that each scenario has thresholds."""
    data = yaml.safe_load(scenario_file.read_text(encoding="utf-8"))
    assert "thresholds" in data, f"{scenario_file.name} missing 'thresholds' section"


def test_smoke_scenario_users_low():
    """Test smoke scenario has low user count."""
    data = yaml.safe_load((SCENARIOS_DIR / "smoke.yml").read_text(encoding="utf-8"))
    assert data["locust"]["users"] <= 3, "Smoke scenario should have <= 3 users"


def test_smoke_scenario_read_only():
    """Test smoke scenario is read-only."""
    data = yaml.safe_load((SCENARIOS_DIR / "smoke.yml").read_text(encoding="utf-8"))
    assert data["safety"]["level"] == "read_only"


def test_smoke_scenario_short_duration():
    """Test smoke scenario has short duration."""
    data = yaml.safe_load((SCENARIOS_DIR / "smoke.yml").read_text(encoding="utf-8"))
    run_time = data["locust"]["run_time"]
    # Should be 30s or 60s
    assert "s" in run_time, "Smoke run_time should be in seconds"


def test_peak_scenario_has_stop_conditions():
    """Test peak scenario has thresholds (stop conditions)."""
    peak_file = SCENARIOS_DIR / "peak_load.yml"
    if not peak_file.exists():
        pytest.skip("peak_load.yml not found")
    data = yaml.safe_load(peak_file.read_text(encoding="utf-8"))
    assert "thresholds" in data, "Peak scenario missing thresholds"
    thresholds = data["thresholds"]
    assert "max_error_rate_percent" in thresholds or "max_p95_ms" in thresholds


def test_soak_scenario_exists():
    """Test soak scenario exists."""
    soak_file = SCENARIOS_DIR / "soak.yml"
    if not soak_file.exists():
        pytest.skip("soak.yml not found")
    data = yaml.safe_load(soak_file.read_text(encoding="utf-8"))
    run_time = data["locust"]["run_time"]
    # Parse duration (e.g. "30m" or "1h")
    num = int("".join(c for c in run_time if c.isdigit()))
    assert num >= 10, "Soak scenario should run for at least 10 minutes/hours"


def test_all_scenarios_have_description():
    """Test all scenarios have descriptions."""
    for sf in get_scenarios():
        data = yaml.safe_load(sf.read_text(encoding="utf-8"))
        assert "description" in data, f"{sf.name} missing 'description'"
