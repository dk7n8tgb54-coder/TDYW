"""
Metrics collection for performance testing.

Collects and aggregates response time metrics: P50/P90/P95/P99, RPS, error rate.
Also collects resource metrics when available.

Usage:

    from helpers.metrics import MetricsCollector

    collector = MetricsCollector()

    # Record a request
    collector.record("GET", "/api/home/navigation/", 150, 200)

    # Get summary
    summary = collector.summary()
    # {"GET /api/home/navigation/": {"p50": 150, "p90": 150, "p95": 150, "p99": 150, "count": 1, "errors": 0}}
"""

import os
import sys
import time
import threading
import statistics
from collections import defaultdict, deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class MetricsCollector:
    """
    Collects per-endpoint performance metrics.

    Thread-safe. Designed to be called from Locust tasks.
    """

    def __init__(self, max_samples=10000):
        self._lock = threading.Lock()
        self._samples = defaultdict(lambda: deque(maxlen=max_samples))
        self._errors = defaultdict(int)
        self._counts = defaultdict(int)
        self._start_time = time.time()
        self._resource_metrics = {
            "cpu_percent": deque(maxlen=300),
            "memory_percent": deque(maxlen=300),
            "db_connections": deque(maxlen=300),
        }

    def record(self, method, endpoint, response_time_ms, status_code, error=None):
        """
        Record a single request.

        Args:
            method: HTTP method (GET, POST, etc.)
            method: HTTP method
            endpoint: API endpoint path
            response_time_ms: Response time in milliseconds
            status_code: HTTP status code
            error: Optional error message if the request failed
        """
        key = f"{method} {endpoint}"

        with self._lock:
            self._samples[key].append(response_time_ms)
            self._counts[key] += 1

            # Count errors: non-2xx status codes or explicit errors
            if error or status_code >= 400:
                self._errors[key] += 1

    def record_business_error(self, method, endpoint):
        """
        Record a business error (HTTP 200 with error field).

        These are counted separately from HTTP errors.
        """
        key = f"{method} {endpoint}"
        with self._lock:
            self._errors[key] += 1

    def record_resource(self, metric_name, value):
        """Record a resource metric (CPU, memory, etc.)."""
        with self._lock:
            if metric_name in self._resource_metrics:
                self._resource_metrics[metric_name].append(value)

    def _percentile(self, sorted_data, percentile):
        """Calculate percentile from sorted data."""
        if not sorted_data:
            return 0
        k = (len(sorted_data) - 1) * (percentile / 100.0)
        f = int(k)
        c = min(f + 1, len(sorted_data) - 1)
        if f == c:
            return sorted_data[f]
        return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * (k - f)

    def summary(self):
        """
        Get aggregated metrics summary.

        Returns:
            dict keyed by "METHOD endpoint" with:
            - count: total requests
            - p50, p90, p95, p99: percentiles in ms
            - avg: average response time in ms
            - min, max: min/max response time in ms
            - errors: error count
            - error_rate: error rate percentage
            - rps: requests per second
        """
        elapsed = time.time() - self._start_time
        result = {}

        with self._lock:
            total_requests = 0
            total_errors = 0

            for key, samples in self._samples.items():
                if not samples:
                    continue

                sorted_samples = sorted(samples)
                count = len(sorted_samples)
                total_requests += count
                errors = self._errors.get(key, 0)
                total_errors += errors

                avg = statistics.mean(sorted_samples)

                result[key] = {
                    "count": count,
                    "p50": round(self._percentile(sorted_samples, 50), 2),
                    "p90": round(self._percentile(sorted_samples, 90), 2),
                    "p95": round(self._percentile(sorted_samples, 95), 2),
                    "p99": round(self._percentile(sorted_samples, 99), 2),
                    "avg": round(avg, 2),
                    "min": round(sorted_samples[0], 2),
                    "max": round(sorted_samples[-1], 2),
                    "errors": errors,
                    "error_rate": round((errors / count * 100) if count > 0 else 0, 2),
                    "rps": round(count / elapsed, 2) if elapsed > 0 else 0,
                }

            result["_summary"] = {
                "total_requests": total_requests,
                "total_errors": total_errors,
                "overall_error_rate": round(
                    (total_errors / total_requests * 100) if total_requests > 0 else 0, 2
                ),
                "elapsed_seconds": round(elapsed, 2),
                "overall_rps": round(total_requests / elapsed, 2) if elapsed > 0 else 0,
            }

        return result

    def check_thresholds(self, thresholds):
        """
        Check collected metrics against threshold definitions.

        Args:
            thresholds: dict from thresholds.yml (parsed)

        Returns:
            list of violations: [{"endpoint": ..., "metric": ..., "value": ..., "threshold": ..., "category": ...}]
        """
        summary = self.summary()
        violations = []

        global_blocking = thresholds.get("global", {}).get("blocking", {})
        endpoint_thresholds = thresholds.get("endpoints", {})

        for key, metrics in summary.items():
            if key == "_summary":
                continue

            # Parse endpoint from key
            parts = key.split(" ", 1)
            if len(parts) != 2:
                continue
            method, endpoint = parts

            # Get thresholds for this endpoint
            ep_thresholds = endpoint_thresholds.get(endpoint, {})
            blocking = ep_thresholds.get("blocking", global_blocking)

            # Check each metric
            for metric_name, threshold_value in blocking.items():
                if metric_name == "p50":
                    actual = metrics.get("p50", 0)
                    if actual > threshold_value:
                        violations.append({
                            "endpoint": endpoint,
                            "metric": "p50",
                            "value": actual,
                            "threshold": threshold_value,
                            "category": "blocking",
                        })
                elif metric_name == "p90":
                    actual = metrics.get("p90", 0)
                    if actual > threshold_value:
                        violations.append({
                            "endpoint": endpoint,
                            "metric": "p90",
                            "value": actual,
                            "threshold": threshold_value,
                            "category": "blocking",
                        })
                elif metric_name == "p95":
                    actual = metrics.get("p95", 0)
                    if actual > threshold_value:
                        violations.append({
                            "endpoint": endpoint,
                            "metric": "p95",
                            "value": actual,
                            "threshold": threshold_value,
                            "category": "blocking",
                        })
                elif metric_name == "p99":
                    actual = metrics.get("p99", 0)
                    if actual > threshold_value:
                        violations.append({
                            "endpoint": endpoint,
                            "metric": "p99",
                            "value": actual,
                            "threshold": threshold_value,
                            "category": "blocking",
                        })
                elif metric_name == "error_rate_max_percent":
                    actual = metrics.get("error_rate", 0)
                    if actual > threshold_value:
                        violations.append({
                            "endpoint": endpoint,
                            "metric": "error_rate",
                            "value": actual,
                            "threshold": threshold_value,
                            "category": "blocking",
                        })

        return violations

    def print_summary(self):
        """Print a formatted summary to stdout."""
        summary = self.summary()

        print("\n" + "=" * 80)
        print("PERFORMANCE TEST RESULTS SUMMARY")
        print("=" * 80)

        # Per-endpoint results
        print(f"\n{'Endpoint':<50} {'Count':>6} {'P50':>8} {'P90':>8} {'P95':>8} {'P99':>8} {'Err%':>6} {'RPS':>6}")
        print("-" * 100)

        for key, metrics in sorted(summary.items()):
            if key == "_summary":
                continue
            # Truncate endpoint name for display
            ep = key[:48] if len(key) > 48 else key
            print(
                f"{ep:<50} {metrics['count']:>6} "
                f"{metrics['p50']:>7.1f}ms {metrics['p90']:>7.1f}ms "
                f"{metrics['p95']:>7.1f}ms {metrics['p99']:>7.1f}ms "
                f"{metrics['error_rate']:>5.1f}% {metrics['rps']:>6.1f}"
            )

        # Overall summary
        s = summary.get("_summary", {})
        print("-" * 100)
        print(
            f"{'TOTAL':<50} {s.get('total_requests', 0):>6} "
            f"{'':>8} {'':>8} {'':>8} {'':>8} "
            f"{s.get('overall_error_rate', 0):>5.1f}% {s.get('overall_rps', 0):>6.1f}"
        )
        print(f"\nElapsed: {s.get('elapsed_seconds', 0):.1f}s")
        print("=" * 80 + "\n")


# --- Global instance ---
_collector = None


def get_collector():
    """Get the global MetricsCollector singleton."""
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector
