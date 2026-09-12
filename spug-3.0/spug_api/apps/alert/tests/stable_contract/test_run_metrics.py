import json
import os
import tempfile
from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.alert.metrics import aggregate_window
from apps.alert.models import HealthProbeSample, RunMetric


class RunMetricsContractTest(TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False)
        self.addCleanup(lambda: os.path.exists(self.tmp.name) and os.unlink(self.tmp.name))
        self.bucket = timezone.now().replace(second=0, microsecond=0)
        self.bucket -= timedelta(minutes=self.bucket.minute % 5)

    def write(self, **values):
        self.tmp.write(json.dumps(values) + '\n')
        self.tmp.flush()

    @override_settings(RUN_METRICS_NGINX_LOG='')
    def test_window_upsert_and_unknown_without_probe(self):
        aggregate_window(self.bucket)
        aggregate_window(self.bucket)
        metric = RunMetric.objects.get(bucket_start=self.bucket)
        self.assertEqual(metric.request_count, 0)
        self.assertEqual(metric.probe_count, 0)

    @override_settings(RUN_METRICS_NGINX_LOG='')
    def test_gateway_error_and_probe_failure_are_aggregated(self):
        HealthProbeSample.objects.create(timestamp=self.bucket + timedelta(minutes=1), success=False, http_status=503)
        HealthProbeSample.objects.create(timestamp=self.bucket + timedelta(minutes=2), success=False, http_status=503)
        HealthProbeSample.objects.create(timestamp=self.bucket + timedelta(minutes=3), success=False, http_status=503)
        metric = aggregate_window(self.bucket)
        self.assertEqual(metric['probe_count'], 3)
        self.assertEqual(metric['probe_success_count'], 0)
