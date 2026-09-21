#!/bin/sh
# WP3 各模块失败定位探针
for app in radio_license document regulation coop_task; do
  echo "=== $app ==="
  python manage.py test "apps.$app.tests" --keepdb --parallel 1 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED' | head -8
done
echo "=== WP4 legacy 各模块 ==="
for app in device fault upgrade interference alert; do
  echo "=== $app ==="
  python manage.py test "apps.$app.tests.legacy_characterization" --keepdb --parallel 1 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED' | head -8
done
