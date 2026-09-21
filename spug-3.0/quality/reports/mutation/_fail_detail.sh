#!/bin/sh
echo "=== radio_license concurrency ==="
python manage.py test apps.radio_license.tests.release_gate.test_performance.ConcurrentWriteTests.test_concurrent_distinct_creates_all_persisted --keepdb --parallel 1 2>&1 | tail -20
echo "=== document instant_upload ==="
python manage.py test apps.document.tests.test_no_instant_upload.TestNoInstantUpload.test_10_independent_file_paths_via_naming --keepdb --parallel 1 2>&1 | tail -20
echo "=== fault legacy loader ==="
python manage.py test apps.fault.tests.legacy_characterization --keepdb --parallel 1 2>&1 | tail -12
