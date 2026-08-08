"""
Authentication helper for performance testing.

Adapted from locustfile/_common.py patterns:
- Token pool: each account logs in once, token shared across users
- 401 triggers automatic token refresh
- Uses X-Token header for authentication
- API base path is /api/

Usage in locustfiles:

    from helpers.auth import TokenPoolHttpUser

    class MyUser(TokenPoolHttpUser):
        wait_time = between(1, 3)
        # token_pool and auth path inherited
"""

import os
import sys
import time
import threading
import json
from collections import defaultdict
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from helpers.safety import get_safety_context


# --- Token Pool Implementation ---

class TokenPool:
    """
    Shared token pool that manages authentication tokens for multiple accounts.

    Each account logs in once, and its token is shared across multiple Locust users.
    If a token expires (401), the pool automatically refreshes it.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._tokens = {}  # username -> token
        self._token_locks = {}  # username -> threading.Lock
        self._last_refresh = {}  # username -> timestamp
        self._refresh_cooldown = 30  # seconds between refresh attempts
        self._accounts = self._load_accounts()
        self._round_robin_idx = 0

    def _load_accounts(self):
        """Load test accounts from environment."""
        accounts = []
        ctx = get_safety_context()

        i = 1
        while True:
            username = os.environ.get(f"TEST_USER_{i}", "")
            password = os.environ.get(f"TEST_PASS_{i}", "")
            if not username or not password:
                break
            accounts.append({
                "username": username,
                "password": password,
            })
            i += 1

        if not accounts:
            # Fallback to defaults from safety context
            username = os.environ.get("TEST_USER_1", "admin")
            password = os.environ.get("TEST_PASS_1", "")
            accounts.append({
                "username": username,
                "password": password,
            })

        return accounts

    def _get_account_for_user(self, user_index):
        """Get account for a given user index (round-robin)."""
        if not self._accounts:
            raise RuntimeError("No test accounts configured")
        return self._accounts[user_index % len(self._accounts)]

    def obtain_token(self, host, account=None, client=None):
        """
        Login and obtain an access token.

        Args:
            host: Base URL (e.g., http://test-server:8000)
            account: Account dict with username/password, or None to pick from pool
            client: Optional requests.Session or locust Session for making the call

        Returns:
            str: access_token
        """
        if account is None:
            account = self._accounts[0]

        username = account["username"]
        password = account["password"]

        login_url = f"{host}/api/account/login/"
        payload = {
            "username": username,
            "password": password,
            "type": "default",
        }

        if client is not None:
            # Use provided client (locust or requests)
            response = client.post(login_url, json=payload)
            data = response.json() if hasattr(response, "json") else {}
        else:
            # Use requests directly
            import requests
            response = requests.post(login_url, json=payload, timeout=30)
            data = response.json()

        token = data.get("data", {}).get("access_token", "")
        if not token:
            error_msg = data.get("error", "Unknown error")
            raise RuntimeError(
                f"Login failed for user '{username}': {error_msg}\n"
                f"Response: {data}"
            )

        # Cache the token
        with self._lock:
            self._tokens[username] = token
            self._token_locks.setdefault(username, threading.Lock())
            self._last_refresh[username] = time.time()

        return token

    def get_token(self, host, user_index=0, client=None):
        """
        Get a token for the given user index.

        If token is cached and not expired, returns cached token.
        Otherwise, obtains a new token via login.

        Args:
            host: Base URL
            user_index: User index for round-robin account selection
            client: Optional HTTP client

        Returns:
            str: access_token
        """
        account = self._get_account_for_user(user_index)
        username = account["username"]

        # Check cache
        with self._lock:
            token = self._tokens.get(username)
            last_refresh = self._last_refresh.get(username, 0)

        if token and (time.time() - last_refresh < self._refresh_cooldown):
            return token

        # Need to obtain/refresh token
        lock = self._token_locks.setdefault(username, threading.Lock())
        with lock:
            # Double-check after acquiring lock
            token = self._tokens.get(username)
            last_refresh = self._last_refresh.get(username, 0)
            if token and (time.time() - last_refresh < self._refresh_cooldown):
                return token

            return self.obtain_token(host, account, client)

    def refresh_token(self, host, username, client=None):
        """
        Force refresh a token after 401.

        Respects cooldown to avoid refresh storms.
        """
        with self._lock:
            last_refresh = self._last_refresh.get(username, 0)
            if time.time() - last_refresh < 5:  # 5 second cooldown for forced refresh
                # Return existing token (might be stale, but avoid storm)
                return self._tokens.get(username, "")

        # Find the account
        account = None
        for acc in self._accounts:
            if acc["username"] == username:
                account = acc
                break

        if account is None:
            account = self._accounts[0]

        return self.obtain_token(host, account, client)

    def get_auth_headers(self, host, user_index=0, client=None):
        """
        Get authentication headers with X-Token.

        Returns:
            dict: {"X-Token": "access_token_value", "Content-Type": "application/json"}
        """
        token = self.get_token(host, user_index, client)
        return {
            "X-Token": token,
            "Content-Type": "application/json",
        }

    @property
    def account_count(self):
        return len(self._accounts)


# --- Global token pool instance ---
_token_pool = None


def get_token_pool():
    """Get the global TokenPool singleton."""
    global _token_pool
    if _token_pool is None:
        _token_pool = TokenPool()
    return _token_pool


# --- Locust HttpUser mixin ---

try:
    from locust import HttpUser
    from locust import events

    @events.test_start.add_listener
    def _on_test_start(environment, **kwargs):
        """Pre-warm token pool on test start."""
        pool = get_token_pool()
        host = environment.host or "http://localhost:8000"
        # Remove trailing slash
        host = host.rstrip("/")
        try:
            # Login all accounts
            for i, account in enumerate(pool._accounts):
                pool.obtain_token(host, account)
            print(f"[AUTH] Token pool warmed: {len(pool._accounts)} accounts")
        except Exception as e:
            print(f"[AUTH] Failed to warm token pool: {e}")

    class TokenPoolHttpUser(HttpUser):
        """
        Base HttpUser with token pool authentication.

        Automatically:
        - Obtains tokens on start
        - Adds X-Token header to all requests
        - Refreshes token on 401
        """

        abstract = True  # Must be subclassed
        token_pool = None
        _user_counter = 0
        _counter_lock = threading.Lock()

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.token_pool = get_token_pool()
            self._token = None
            self._account_index = 0

            # Assign a unique index to this user
            with TokenPoolHttpUser._counter_lock:
                self._account_index = TokenPoolHttpUser._user_counter
                TokenPoolHttpUser._user_counter += 1

        def on_start(self):
            """Called when user starts. Obtain initial token."""
            host = self.host.rstrip("/") if self.host else "http://localhost:8000"
            try:
                self._token = self.token_pool.get_token(host, self._account_index)
            except Exception as e:
                print(f"[AUTH] User start failed: {e}")
                # Don't raise - let the task fail naturally

        def get_auth_headers(self):
            """Get auth headers with current token."""
            if not self._token:
                host = self.host.rstrip("/") if self.host else "http://localhost:8000"
                self._token = self.token_pool.get_token(host, self._account_index)
            return {
                "X-Token": self._token or "",
                "Content-Type": "application/json",
            }

        def _get_account_username(self):
            """Get the username assigned to this user."""
            account = self.token_pool._get_account_for_user(self._account_index)
            return account["username"]

        def api_get(self, path, **kwargs):
            """GET request with auth headers."""
            headers = kwargs.pop("headers", {})
            headers.update(self.get_auth_headers())
            return self.client.get(path, headers=headers, **kwargs)

        def api_post(self, path, json_data=None, **kwargs):
            """POST request with auth headers."""
            headers = kwargs.pop("headers", {})
            headers.update(self.get_auth_headers())
            return self.client.post(path, json=json_data, headers=headers, **kwargs)

        def api_put(self, path, json_data=None, **kwargs):
            """PUT request with auth headers."""
            headers = kwargs.pop("headers", {})
            headers.update(self.get_auth_headers())
            return self.client.put(path, json=json_data, headers=headers, **kwargs)

        def api_delete(self, path, **kwargs):
            """DELETE request with auth headers."""
            headers = kwargs.pop("headers", {})
            headers.update(self.get_auth_headers())
            return self.client.delete(path, headers=headers, **kwargs)

        def check_and_refresh_token(self, response):
            """
            Check if response is 401 and refresh token if needed.

            Call this after any API request that might return 401.
            """
            if response.status_code == 401:
                host = self.host.rstrip("/") if self.host else "http://localhost:8000"
                username = self._get_account_username()
                self._token = self.token_pool.refresh_token(host, username)
                return True
            return False

except ImportError:
    # Locust not installed - provide stub for testing
    TokenPoolHttpUser = object
