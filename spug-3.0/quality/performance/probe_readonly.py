#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Read-only single-request probe for performance baseline.

Executes single GET requests to key endpoints and measures response time.
Safe to run in any environment - no load, no writes.

Usage:
    python quality/performance/probe_readonly.py --base-url http://localhost
"""

import os
import sys
import time
import json
import statistics
import argparse
import csv
from pathlib import Path

# Add helpers to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def login(base_url, username, password):
    """Login and get token."""
    import urllib.request
    import urllib.error

    url = f"{base_url}/api/account/login/"
    data = json.dumps({"username": username, "password": password, "type": "default"}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("error"):
                return None
            return (result.get("data") or {}).get("access_token")
    except Exception as e:
        print(f"Login failed: {e}")
        return None


def probe_endpoint(base_url, token, method, path, params=None, name=None):
    """Execute a single request and measure response time."""
    import urllib.request
    import urllib.error
    import urllib.parse

    url = f"{base_url}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {
        "X-Token": token,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
    }

    req = urllib.request.Request(url, headers=headers, method=method)
    name = name or f"{method} {path}"

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            duration_ms = (time.perf_counter() - start) * 1000
            status = resp.status
            # Check for business error
            try:
                data = json.loads(body)
                biz_error = data.get("error", "")
            except Exception:
                biz_error = ""
            return {
                "name": name,
                "method": method,
                "path": path,
                "status_code": status,
                "duration_ms": round(duration_ms, 2),
                "success": status == 200 and not biz_error,
                "error": biz_error,
            }
    except urllib.error.HTTPError as e:
        duration_ms = (time.perf_counter() - start) * 1000
        return {
            "name": name,
            "method": method,
            "path": path,
            "status_code": e.code,
            "duration_ms": round(duration_ms, 2),
            "success": False,
            "error": f"HTTP {e.code}",
        }
    except Exception as e:
        duration_ms = (time.perf_counter() - start) * 1000
        return {
            "name": name,
            "method": method,
            "path": path,
            "status_code": 0,
            "duration_ms": round(duration_ms, 2),
            "success": False,
            "error": str(e)[:100],
        }


def run_probes(base_url, token, iterations=3):
    """Run probes on all key endpoints."""
    # Define endpoints to probe
    endpoints = [
        # Basic APIs
        ("GET", "/api/home/statistic/", {}, "home_statistic"),
        ("GET", "/api/home/navigation/", {}, "navigation"),
        ("GET", "/api/data-analysis/overview/", {}, "data_analysis"),
        # Daily business
        ("GET", "/api/department-duty-log/records/", {"page": 1, "page_size": 5}, "dept_duty_logs"),
        ("GET", "/api/duty/duty/", {"page": 1, "page_size": 5}, "duty_records"),
        ("GET", "/api/runlog/", {"page": 1, "page_size": 5}, "runlogs"),
        ("GET", "/api/reminder/", {"page": 1, "page_size": 5}, "reminders"),
        # Documents & administration
        ("GET", "/api/radio-license/", {"page": 1, "page_size": 5}, "radio_licenses"),
        ("GET", "/api/radio-license/approvals/", {"page": 1, "page_size": 5}, "station_approvals"),
        ("GET", "/api/contract-agreement/", {"page": 1, "page_size": 5}, "contracts"),
        ("GET", "/api/document/folder/", {"is_public": "false", "page": 1, "page_size": 5}, "doc_folders"),
        ("GET", "/api/document/file/", {"is_public": "false", "page": 1, "page_size": 5}, "doc_files"),
        ("GET", "/api/regulation/", {"page": 1, "page_size": 5}, "regulations"),
        # Technical operations
        ("GET", "/api/device/device-resume/", {"page": 1, "page_size": 5}, "devices"),
        ("GET", "/api/fault/records/", {"page": 1, "page_size": 5}, "faults"),
        ("GET", "/api/upgrade/records/", {"page": 1, "page_size": 5}, "upgrade_records"),
        ("GET", "/api/upgrade/statistics/", {}, "upgrade_stats"),
        ("GET", "/api/interference/", {"page": 1, "page_size": 5}, "interferences"),
        ("GET", "/api/alert/", {"page": 1, "page_size": 5}, "alerts"),
        # System management
        ("GET", "/api/account/user/", {"page": 1, "page_size": 5}, "account_users"),
        ("GET", "/api/account/role/", {}, "account_roles"),
        ("GET", "/api/account/tenant/", {}, "account_tenants"),
        ("GET", "/api/logs/audit/", {"page": 1, "page_size": 5}, "audit_logs"),
        ("GET", "/api/setting/", {}, "system_settings"),
    ]

    results = []
    for method, path, params, name in endpoints:
        # Cold cache: first request
        r = probe_endpoint(base_url, token, method, path, params, f"{name} (cold)")
        r["cache_state"] = "cold"
        r["endpoint_name"] = name
        results.append(r)

        # Hot cache: subsequent requests
        for i in range(iterations - 1):
            r = probe_endpoint(base_url, token, method, path, params, f"{name} (hot{i+1})")
            r["cache_state"] = "hot"
            r["endpoint_name"] = name
            results.append(r)

    return results


def main():
    parser = argparse.ArgumentParser(description="Read-only performance probe")
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://localhost"))
    parser.add_argument("--username", default=os.environ.get("PROBE_USERNAME", "admin"))
    parser.add_argument("--password", default=os.environ.get("PROBE_PASSWORD", ""))
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--output-dir", default="quality/reports/performance/artifacts")
    args = parser.parse_args()

    if not args.password:
        print("ERROR: No password provided. Set PROBE_PASSWORD env var.")
        sys.exit(1)

    print(f"Base URL: {args.base_url}")
    print(f"Username: {args.username}")
    print(f"Iterations: {args.iterations}")
    print()

    # Login
    print("Logging in...")
    token = login(args.base_url, args.username, args.password)
    if not token:
        print("Login failed. Exiting.")
        sys.exit(1)
    print("Login successful.")
    print()

    # Run probes
    print("Running probes...")
    results = run_probes(args.base_url, token, args.iterations)

    # Print results
    print(f"\n{'Endpoint':<30} {'Cold (ms)':>10} {'Hot Avg (ms)':>12} {'Status':>8} {'Error':>20}")
    print("-" * 85)

    by_endpoint = {}
    for r in results:
        name = r["endpoint_name"]
        if name not in by_endpoint:
            by_endpoint[name] = {"cold": [], "hot": [], "errors": []}
        if r["cache_state"] == "cold":
            by_endpoint[name]["cold"].append(r["duration_ms"])
        else:
            by_endpoint[name]["hot"].append(r["duration_ms"])
        if not r["success"]:
            by_endpoint[name]["errors"].append(r["error"])

    for name, data in by_endpoint.items():
        cold = data["cold"][0] if data["cold"] else 0
        hot_avg = statistics.mean(data["hot"]) if data["hot"] else 0
        status = "OK" if not data["errors"] else "ERR"
        error = data["errors"][0][:20] if data["errors"] else ""
        print(f"{name:<30} {cold:>10.1f} {hot_avg:>12.1f} {status:>8} {error:>20}")

    # Export CSV
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "endpoint_baseline.csv"

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "run_id", "module", "method", "endpoint", "scenario",
            "requests", "failures", "error_rate", "rps",
            "avg_ms", "p50_ms", "p95_ms", "p99_ms", "max_ms", "notes"
        ])
        writer.writeheader()
        run_id = f"probe_{int(time.time())}"
        for name, data in by_endpoint.items():
            all_times = sorted(data["cold"] + data["hot"])
            n = len(all_times)
            errors = len(data["errors"])
            writer.writerow({
                "run_id": run_id,
                "module": name,
                "method": "GET",
                "endpoint": name,
                "scenario": "single_probe",
                "requests": n,
                "failures": errors,
                "error_rate": round(errors / n * 100, 2) if n else 0,
                "rps": 0,
                "avg_ms": round(statistics.mean(all_times), 2) if all_times else 0,
                "p50_ms": round(statistics.median(all_times), 2) if all_times else 0,
                "p95_ms": round(all_times[-1] if all_times else 0, 2),
                "p99_ms": round(all_times[-1] if all_times else 0, 2),
                "max_ms": round(max(all_times), 2) if all_times else 0,
                "notes": "cold_cache" if not data["hot"] else "cold+hot",
            })

    print(f"\nCSV exported to: {csv_path}")
    print(f"Total endpoints probed: {len(by_endpoint)}")
    print(f"Total requests: {len(results)}")


if __name__ == "__main__":
    main()
