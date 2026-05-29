#!/usr/bin/env python3
"""
Transfer state transition smoke test (single + batch).

Usage:
  python verify_transfer_state_transitions.py \
    --base-url http://127.0.0.1:80 \
    --cookie "sessionid=xxx; csrftoken=xxx" \
    --csrf-token xxx \
    --transfer-ids 101,102,103

Or (token auth):
  python verify_transfer_state_transitions.py \
    --base-url http://127.0.0.1:80 \
    --x-token "<token>" \
    --transfer-ids 101,102,103

Or (auto login with username/password):
  python verify_transfer_state_transitions.py \
    --base-url http://127.0.0.1:80 \
    --username admin \
    --password Admin888 \
    --transfer-ids 101,102,103
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, List, Tuple
from urllib import request, error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify transfer state transition APIs")
    parser.add_argument("--base-url", required=True, help="API host, e.g. http://127.0.0.1:80")
    parser.add_argument("--cookie", default="", help="Cookie header value")
    parser.add_argument("--x-token", default="", help="x-token header value (Spug access_token)")
    parser.add_argument("--authorization", default="", help="Authorization header value, e.g. Bearer <token>")
    parser.add_argument("--csrf-token", default="", help="X-CSRFToken header if required")
    parser.add_argument("--username", default="", help="Login username for auto token fetch")
    parser.add_argument("--password", default="", help="Login password for auto token fetch")
    parser.add_argument("--transfer-ids", required=True, help="Comma separated transfer ids, e.g. 101,102")
    args = parser.parse_args()
    has_user_pass = bool(args.username and args.password)
    if not args.cookie and not args.authorization and not args.x_token and not has_user_pass:
        parser.error("At least one auth method is required: --cookie or --authorization or --x-token")
    return args


def post_json(
    url: str,
    payload: Dict,
    cookie: str,
    csrf_token: str,
    x_token: str,
    authorization: str,
) -> Tuple[int, Dict]:
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
    }
    if cookie:
        headers["Cookie"] = cookie
    if x_token:
        headers["x-token"] = x_token
    if authorization:
        headers["Authorization"] = authorization
    if csrf_token:
        headers["X-CSRFToken"] = csrf_token
    req = request.Request(url=url, data=data, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {"raw": body}
        return e.code, parsed
    except Exception as e:
        return 0, {"error": str(e)}


def print_result(title: str, status: int, payload: Dict) -> None:
    print(f"\n[{title}] HTTP {status}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def fetch_access_token(base_url: str, username: str, password: str) -> str:
    status, payload = post_json(
        f"{base_url}/api/account/login/",
        {"username": username, "password": password, "type": "default"},
        cookie="",
        csrf_token="",
        x_token="",
        authorization="",
    )
    if status != 200:
        print_result("login", status, payload)
        return ""
    data = payload.get("data") if isinstance(payload, dict) else None
    token = data.get("access_token", "") if isinstance(data, dict) else ""
    if not token:
        print_result("login", status, payload)
    return token


def main() -> int:
    args = parse_args()
    base = args.base_url.rstrip("/")
    if not args.x_token and args.username and args.password:
        token = fetch_access_token(base, args.username, args.password)
        if not token:
            print("\nAuto login failed, cannot continue.")
            return 3
        args.x_token = token
        print("\n[login] Auto fetched x-token successfully.")

    ids: List[int] = [int(x.strip()) for x in args.transfer_ids.split(",") if x.strip()]
    if not ids:
        print("No transfer ids provided")
        return 2

    first_id = ids[0]

    status, payload = post_json(
        f"{base}/api/document/transfers/batch/pause/",
        {"transfer_ids": ids},
        args.cookie,
        args.csrf_token,
        args.x_token,
        args.authorization,
    )
    print_result("batch pause", status, payload)

    status, payload = post_json(
        f"{base}/api/document/transfers/batch/resume/",
        {"transfer_ids": ids},
        args.cookie,
        args.csrf_token,
        args.x_token,
        args.authorization,
    )
    print_result("batch resume", status, payload)

    status, payload = post_json(
        f"{base}/api/document/transfers/{first_id}/status/",
        {"status": "PAUSED"},
        args.cookie,
        args.csrf_token,
        args.x_token,
        args.authorization,
    )
    print_result("single status to PAUSED", status, payload)

    status, payload = post_json(
        f"{base}/api/document/transfers/{first_id}/status/",
        {"status": "UPLOADING"},
        args.cookie,
        args.csrf_token,
        args.x_token,
        args.authorization,
    )
    print_result("single status to UPLOADING", status, payload)

    status, payload = post_json(
        f"{base}/api/document/transfers/{first_id}/cancel/",
        {},
        args.cookie,
        args.csrf_token,
        args.x_token,
        args.authorization,
    )
    print_result("single cancel", status, payload)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
