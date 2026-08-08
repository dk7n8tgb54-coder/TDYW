"""
Secret Redaction

Redacts sensitive information from logs and output before writing.
Catches: passwords, tokens, API keys, private keys, cookies, session IDs.
"""

import re
from typing import List, Pattern, Tuple


# ---- Redaction Patterns ----
# Each entry is (compiled_regex, replacement_string)

REDACTION_PATTERNS: List[Tuple[Pattern, str]] = [
    # Passwords: password=xxx, password: xxx, PASSWORD xxx
    (
        re.compile(r"(?i)(password|passwd|pwd)\s*[=:]\s*\S+"),
        r"\1=REDACTED",
    ),
    # MariaDB/MySQL connection strings with password
    (
        re.compile(r"mysql://[^:]+:[^@]+@", re.IGNORECASE),
        "mysql://USER:REDACTED@",
    ),
    # Redis URLs with password
    (
        re.compile(r"redis://:[^@]+@", re.IGNORECASE),
        "redis://:REDACTED@",
    ),
    # Redis URLs with user:password
    (
        re.compile(r"redis://[^:]+:[^@]+@", re.IGNORECASE),
        "redis://USER:REDACTED@",
    ),
    # BORG_PASSPHRASE=xxx
    (
        re.compile(r"(?i)BORG_PASSPHRASE\s*=\s*\S+"),
        "BORG_PASSPHRASE=REDACTED",
    ),
    # SECRET_KEY=xxx
    (
        re.compile(r"(?i)SECRET_KEY\s*=\s*\S+"),
        "SECRET_KEY=REDACTED",
    ),
    # API keys: api_key=xxx, apikey=xxx, x-api-key: xxx
    (
        re.compile(r"(?i)(api[_-]?key)\s*[=:]\s*\S+"),
        r"\1=REDACTED",
    ),
    # Tokens: token=xxx, access_token=xxx, x-token: xxx
    (
        re.compile(r"(?i)(access[_-]?token|auth[_-]?token|refresh[_-]?token|x[_-]?token|token)\s*[=:]\s*\S+"),
        r"\1=REDACTED",
    ),
    # Cookies: Cookie: xxx, Set-Cookie: xxx
    (
        re.compile(r"(?i)(cookie|set[_-]?cookie)\s*:\s*[^\r\n]+"),
        r"\1: REDACTED",
    ),
    # Session IDs: session_id=xxx, sessionid=xxx
    (
        re.compile(r"(?i)(session[_-]?id|sessionid)\s*[=:]\s*\S+"),
        r"\1=REDACTED",
    ),
    # SSH private key blocks
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
        "-----BEGIN PRIVATE KEY [REDACTED]-----",
    ),
    # JWT tokens (eyJ... pattern)
    (
        re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
        "JWT_REDACTED",
    ),
    # Authorization headers
    (
        re.compile(r"(?i)(authorization)\s*:\s*(bearer\s+)?[^\r\n]+"),
        r"\1: REDACTED",
    ),
    # MYSQL_ROOT_PASSWORD=xxx, MYSQL_PASSWORD=xxx
    (
        re.compile(r"(?i)(mysql[_-]?root[_-]?password|mysql[_-]?password)\s*=\s*\S+"),
        r"\1=REDACTED",
    ),
    # Generic key=value patterns for known secret keys
    (
        re.compile(r"(?i)(private[_-]?key|secret|passphrase|credential)\s*[=:]\s*\S+"),
        r"\1=REDACTED",
    ),
]


def redact(text: str) -> str:
    """
    Redact all known secret patterns from a text string.
    Returns the redacted text.
    """
    if not text:
        return text
    for pattern, replacement in REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_dict(data: dict) -> dict:
    """
    Redact sensitive values in a dictionary.
    Keys matching known secret patterns will have their values replaced.
    """
    sensitive_key_patterns = [
        "password", "passwd", "pwd", "secret", "token", "api_key", "apikey",
        "passphrase", "private_key", "session_id", "sessionid", "cookie",
        "authorization", "credential", "borg_passphrase",
    ]

    def _redact_value(key: str, value):
        key_lower = key.lower()
        if isinstance(value, str):
            for pattern in sensitive_key_patterns:
                if pattern in key_lower:
                    return "REDACTED"
            # Also redact string values that contain secrets
            return redact(value)
        elif isinstance(value, dict):
            return {k: _redact_value(k, v) for k, v in value.items()}
        elif isinstance(value, list):
            return [_redact_value(key, item) for item in value]
        return value

    return {k: _redact_value(k, v) for k, v in data.items()}


def redact_lines(lines: List[str]) -> List[str]:
    """Redact each line in a list of strings."""
    return [redact(line) for line in lines]


class RedactingWriter:
    """
    A wrapper around a file-like object that redacts all output before writing.
    Usage:
        with open('log.txt', 'w') as f:
            writer = RedactingWriter(f)
            writer.write("password=secret123\n")
            # log.txt will contain: password=REDACTED
    """

    def __init__(self, stream):
        self._stream = stream

    def write(self, text: str):
        self._stream.write(redact(text))

    def writelines(self, lines: List[str]):
        self._stream.writelines(redact_lines(lines))

    def flush(self):
        self._stream.flush()

    def close(self):
        self._stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
