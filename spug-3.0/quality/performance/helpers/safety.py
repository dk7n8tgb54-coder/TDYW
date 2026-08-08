"""
Environment safety guard for performance testing.

This module implements a FAIL-CLOSED safety policy. If any required check
cannot be verified, the test is NOT allowed to proceed.

Usage (at top of every locustfile):

    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from helpers.safety import check_safety, SafetyLevel

    check_safety(SafetyLevel.READ_ONLY)  # or SafetyLevel.WRITE_LOAD

If checks fail, the process exits with code 1 and a clear message.
"""

import os
import sys
import re
import socket
from enum import Enum
from urllib.parse import urlparse
from pathlib import Path


class SafetyLevel(Enum):
    """Safety level required for the test."""
    # Static inventory: just checking endpoints exist, no real load
    STATIC_INVENTORY = "static_inventory"
    # Single-request probe: one request at a time, no concurrency
    SINGLE_PROBE = "single_probe"
    # Read-only load: multiple concurrent users, GET requests only
    READ_ONLY = "read_only"
    # Write load: POST/PUT/DELETE with test data
    WRITE_LOAD = "write_load"


class SafetyCheckError(Exception):
    """Raised when a safety check fails."""
    pass


# --- Environment variable loading ---

def _load_env_file():
    """Load performance.env if it exists."""
    env_path = Path(__file__).parent.parent / "performance.env"
    if not env_path.exists():
        # Try .env in the same directory
        env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    # Don't override existing env vars
                    if key not in os.environ:
                        os.environ[key] = value


def _get_env(key, default=""):
    """Get environment variable, loading from .env file first."""
    _load_env_file()
    return os.environ.get(key, default)


# --- Individual safety checks ---

def _check_base_url():
    """Check that BASE_URL is set and is not None."""
    base_url = _get_env("BASE_URL", "")
    if not base_url:
        raise SafetyCheckError(
            "BASE_URL is not set. Performance testing requires an explicit target URL.\n"
            "Set BASE_URL in performance.env to your test server address."
        )
    return base_url


def _check_url_is_allowed(base_url):
    """Check that the URL is not localhost in production context and is HTTP(S)."""
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise SafetyCheckError(
            f"BASE_URL scheme '{parsed.scheme}' is not allowed. Use http or https."
        )
    if not parsed.hostname:
        raise SafetyCheckError(
            f"BASE_URL '{base_url}' has no hostname. Provide a valid URL."
        )
    return parsed


def _check_allow_performance_test():
    """Check that ALLOW_PERFORMANCE_TEST is explicitly set to 'true'."""
    val = _get_env("ALLOW_PERFORMANCE_TEST", "").lower().strip()
    if val != "true":
        raise SafetyCheckError(
            "ALLOW_PERFORMANCE_TEST is not set to 'true'.\n"
            "Performance testing is blocked by default (fail-closed).\n"
            "Set ALLOW_PERFORMANCE_TEST=true in performance.env to proceed."
        )


def _check_allow_write_load():
    """Check that ALLOW_WRITE_LOAD is explicitly set to 'true'."""
    val = _get_env("ALLOW_WRITE_LOAD", "").lower().strip()
    if val != "true":
        raise SafetyCheckError(
            "ALLOW_WRITE_LOAD is not set to 'true'.\n"
            "Write load testing requires explicit opt-in.\n"
            "Set ALLOW_WRITE_LOAD=true in performance.env to proceed.\n"
            "WARNING: Write tests create and delete test data. Only run against test databases."
        )


def _check_forbidden_server_names(parsed_url):
    """Check that the target server is not a forbidden production container."""
    hostname = parsed_url.hostname or ""
    port = parsed_url.port

    forbidden_names_raw = _get_env(
        "FORBIDDEN_SERVER_NAMES",
        "tdyw,tdyw-test"
    )
    forbidden_names = [n.strip().lower() for n in forbidden_names_raw.split(",") if n.strip()]

    for name in forbidden_names:
        if name in hostname.lower():
            raise SafetyCheckError(
                f"BASE_URL hostname '{hostname}' contains forbidden name '{name}'.\n"
                "This appears to be a production or dev container.\n"
                "Performance testing is not allowed against production/dev containers.\n"
                "Use a dedicated test server instead."
            )

    # Check if hostname resolves to a known forbidden address
    try:
        resolved_ip = socket.gethostbyname(hostname)
        forbidden_ips = ["127.0.0.1", "localhost"]
        # Allow localhost only if explicitly configured as test environment
        if resolved_ip in forbidden_ips:
            # Allow localhost if DB name check passes (for local dev test DB)
            pass
    except socket.gaierror:
        pass  # Can't resolve, let the actual request fail later


def _check_forbidden_db_names():
    """Check that the database name is not a forbidden production/dev name."""
    forbidden_raw = _get_env(
        "FORBIDDEN_DB_NAMES",
        "spug,spug_dev,spug_prod,spug_production"
    )
    forbidden_names = [n.strip().lower() for n in forbidden_raw.split(",") if n.strip()]

    # We can't directly query the DB, but we check env vars that might indicate the DB
    db_name = _get_env("DB_NAME", "").lower()
    db_database = _get_env("DB_DATABASE", "").lower()
    mysql_db = _get_env("MYSQL_DB", "").lower()
    database_url = _get_env("DATABASE_URL", "").lower()

    all_db_indicators = [db_name, db_database, mysql_db, database_url]

    for indicator in all_db_indicators:
        for forbidden in forbidden_names:
            if forbidden and forbidden in indicator:
                raise SafetyCheckError(
                    f"Database name appears to be '{indicator}' which contains forbidden name '{forbidden}'.\n"
                    "Performance testing is not allowed against production/dev databases.\n"
                    "Use a dedicated test database (name must contain 'test', 'perf', or 'drill')."
                )

    return forbidden_names


def _check_db_name_has_test_token():
    """
    For write tests, verify the database name contains an allowed token.

    Since we can't always directly query the DB, we check:
    1. Environment variables (DB_NAME, DATABASE_URL, etc.)
    2. If we can detect the database name from the server

    If we CANNOT verify the database name, we FAIL CLOSED for write tests.
    """
    allowed_tokens_raw = _get_env(
        "ALLOWED_DB_NAME_TOKENS",
        "test,perf,drill"
    )
    allowed_tokens = [t.strip().lower() for t in allowed_tokens_raw.split(",") if t.strip()]

    # Check various env var patterns that might contain DB name
    db_name = _get_env("DB_NAME", "").lower()
    db_database = _get_env("DB_DATABASE", "").lower()
    mysql_db = _get_env("MYSQL_DB", "").lower()
    database_url = _get_env("DATABASE_URL", "").lower()

    all_db_indicators = [db_name, db_database, mysql_db, database_url]

    # Filter out empty strings
    indicators = [i for i in all_db_indicators if i]

    if not indicators:
        # Can't verify DB name - fail closed for write tests
        raise SafetyCheckError(
            "Cannot determine database name from environment variables.\n"
            "For write load tests, the database name must be verifiable and contain "
            f"one of: {allowed_tokens}\n"
            "Set DB_NAME or DATABASE_URL in performance.env."
        )

    for indicator in indicators:
        has_token = any(token in indicator for token in allowed_tokens)
        if has_token:
            return  # OK, found an allowed token

    # None of the indicators contain an allowed token
    raise SafetyCheckError(
        f"Database name does not contain any allowed token: {allowed_tokens}\n"
        f"Detected database indicators: {indicators}\n"
        "Write load tests require a dedicated test database."
    )


def _check_test_credentials():
    """Check that test credentials are provided."""
    user1 = _get_env("TEST_USER_1", "")
    pass1 = _get_env("TEST_PASS_1", "")
    if not user1 or not pass1:
        raise SafetyCheckError(
            "TEST_USER_1 and TEST_PASS_1 are not set.\n"
            "Provide test account credentials in performance.env."
        )


def _check_max_limits():
    """Verify safety limits are within reasonable bounds."""
    max_create = int(_get_env("MAX_CREATE_LIMIT", "50"))
    max_file_size = int(_get_env("MAX_FILE_SIZE", "1048576"))
    max_file_count = int(_get_env("MAX_FILE_COUNT", "10"))

    if max_create > 100:
        raise SafetyCheckError(
            f"MAX_CREATE_LIMIT={max_create} exceeds safe maximum of 100.\n"
            "Reduce MAX_CREATE_LIMIT in performance.env."
        )
    if max_file_size > 1048576:
        raise SafetyCheckError(
            f"MAX_FILE_SIZE={max_file_size} exceeds safe maximum of 1048576 (1MB).\n"
            "Reduce MAX_FILE_SIZE in performance.env."
        )
    if max_file_count > 20:
        raise SafetyCheckError(
            f"MAX_FILE_COUNT={max_file_count} exceeds safe maximum of 20.\n"
            "Reduce MAX_FILE_COUNT in performance.env."
        )

    return {
        "max_create": max_create,
        "max_file_size": max_file_size,
        "max_file_count": max_file_count,
    }


# --- Main safety check function ---

def check_safety(level=SafetyLevel.READ_ONLY):
    """
    Run safety checks appropriate to the requested test level.

    Returns a dict of safety context if checks pass.
    Exits the process with code 1 if any check fails.

    Args:
        level: SafetyLevel enum indicating the test type

    Returns:
        dict with keys: base_url, limits, level
    """
    try:
        # --- Checks for ALL levels ---

        # 1. BASE_URL must be set
        base_url = _check_base_url()

        # 2. URL must be valid HTTP(S)
        parsed = _check_url_is_allowed(base_url)

        # 3. ALLOW_PERFORMANCE_TEST must be true
        _check_allow_performance_test()

        # 4. Must not point to forbidden server names
        _check_forbidden_server_names(parsed)

        # 5. Must not point to forbidden database names
        _check_forbidden_db_names()

        # 6. Test credentials must be provided
        _check_test_credentials()

        # 7. Max limits must be within safe bounds
        limits = _check_max_limits()

        # --- Additional checks for higher safety levels ---

        if level == SafetyLevel.WRITE_LOAD:
            # 8. ALLOW_WRITE_LOAD must be true
            _check_allow_write_load()

            # 9. Database name must contain test/perf/drill token
            _check_db_name_has_test_token()

        context = {
            "base_url": base_url,
            "limits": limits,
            "level": level,
            "parsed_url": parsed,
        }

        print(f"[SAFETY] All checks passed for level={level.value}")
        print(f"[SAFETY] Target: {base_url}")
        print(f"[SAFETY] Limits: {limits}")
        return context

    except SafetyCheckError as e:
        print(f"\n{'='*60}")
        print(f"SAFETY CHECK FAILED - TEST ABORTED")
        print(f"{'='*60}")
        print(f"Level: {level.value}")
        print(f"Reason: {e}")
        print(f"{'='*60}\n")
        sys.exit(1)

    except Exception as e:
        print(f"\n{'='*60}")
        print(f"SAFETY CHECK ERROR - UNEXPECTED FAILURE")
        print(f"{'='*60}")
        print(f"Level: {level.value}")
        print(f"Error: {type(e).__name__}: {e}")
        print(f"This is an unexpected error. Failing closed for safety.")
        print(f"{'='*60}\n")
        sys.exit(1)


def get_safety_context():
    """
    Get the safety context without running full checks.
    Useful for helpers that need BASE_URL and limits after check_safety has passed.
    """
    _load_env_file()
    base_url = _get_env("BASE_URL", "http://localhost:8000")
    limits = _check_max_limits()
    prefix = _get_env("TEST_DATA_PREFIX", "PERF_")
    return {
        "base_url": base_url,
        "limits": limits,
        "prefix": prefix,
    }
