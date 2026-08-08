#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for secret redaction in DR logs and reports.

Tests the actual function-based API in helpers/redaction.py:
- redact(text) -> redacted text
- REDACTION_PATTERNS list
"""

import os
import sys
import pytest
from pathlib import Path

# Add DR root to path
DR_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(DR_ROOT))

from helpers.redaction import redact, REDACTION_PATTERNS


class TestRedactionPatterns:
    """Test that redaction patterns are defined."""

    def test_patterns_exist(self):
        """Test that redaction patterns are defined."""
        assert len(REDACTION_PATTERNS) > 0

    def test_patterns_are_tuples(self):
        """Test that patterns are (regex, replacement) tuples."""
        for pattern in REDACTION_PATTERNS:
            assert isinstance(pattern, (tuple, list))
            assert len(pattern) >= 2


class TestRedactFunction:
    """Test the redact() function."""

    def test_redact_password(self):
        """Test password redaction."""
        text = 'password = secret123'
        redacted = redact(text)
        assert "secret123" not in redacted

    def test_redact_passwd(self):
        """Test passwd redaction."""
        text = 'passwd: mypass'
        redacted = redact(text)
        assert "mypass" not in redacted

    def test_redact_token(self):
        """Test token redaction."""
        text = 'access_token = abcdef1234567890abcdef1234567890'
        redacted = redact(text)
        assert "abcdef1234567890abcdef1234567890" not in redacted

    def test_redact_x_token_header(self):
        """Test X-Token header redaction."""
        text = 'x-token: abcdef1234567890abcdef1234567890'
        redacted = redact(text)
        assert "abcdef1234567890abcdef1234567890" not in redacted

    def test_redact_mariadb_connection_string(self):
        """Test MariaDB connection string redaction."""
        text = 'mysql://user:secretpass@host:3306/db'
        redacted = redact(text)
        assert "secretpass" not in redacted

    def test_redact_redis_url_with_password(self):
        """Test Redis URL with password redaction."""
        text = 'redis://:secretpass@127.0.0.1:6379/1'
        redacted = redact(text)
        assert "secretpass" not in redacted

    def test_redact_private_key_block(self):
        """Test private key block redaction (requires BEGIN and END)."""
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
        redacted = redact(text)
        assert "MIIEpAIBAAKCAQEA" not in redacted
        assert "REDACTED" in redacted

    def test_redact_jwt_token(self):
        """Test JWT token redaction."""
        text = 'token = eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIx'
        redacted = redact(text)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted

    def test_redact_mysql_password_env(self):
        """Test MYSQL_PASSWORD env var redaction."""
        text = 'MYSQL_PASSWORD=mysecretpass'
        redacted = redact(text)
        assert "mysecretpass" not in redacted

    def test_redact_secret_key_assignment(self):
        """Test secret_key assignment redaction."""
        text = 'secret_key = abcdefghijklmnopqrstuvwxyz123456'
        redacted = redact(text)
        assert "abcdefghijklmnopqrstuvwxyz123456" not in redacted

    def test_redact_multiple_secrets(self):
        """Test redaction of multiple secrets in same text."""
        text = 'password = pass1 and token = tok12345678901234567890'
        redacted = redact(text)
        assert "pass1" not in redacted
        assert "tok12345678901234567890" not in redacted

    def test_no_false_positive_normal_text(self):
        """Test that normal text is not redacted."""
        text = "The user logged in successfully at 2026-08-08 10:00:00"
        redacted = redact(text)
        assert "logged in" in redacted
        assert "2026-08-08" in redacted

    def test_redact_log_line(self):
        """Test redaction of a typical log line."""
        text = '[2026-08-08 10:00:00] LOGIN user=admin token=abcdef1234567890abcdef1234567890'
        redacted = redact(text)
        assert "abcdef1234567890abcdef1234567890" not in redacted

    def test_empty_string(self):
        """Test redaction of empty string."""
        assert redact("") == ""

    def test_no_secrets_text_unchanged(self):
        """Test that text without secrets is unchanged."""
        text = "SELECT * FROM users WHERE id = 1"
        redacted = redact(text)
        assert "SELECT" in redacted
        assert "users" in redacted
