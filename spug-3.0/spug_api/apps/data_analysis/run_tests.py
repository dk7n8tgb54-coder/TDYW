"""通过 manage.py shell 运行的测试入口（无需 django.setup()）。
用法：python manage.py shell < apps/data_analysis/run_tests.py
"""
import sys, datetime
from unittest.mock import MagicMock
from django.test import RequestFactory
from apps.data_analysis.services.common import (
    parse_date_range, make_range_filter, build_distribution, build_monthly_trend,
    build_meta, calc_rate,
)
from apps.data_analysis.services.cache import get_cache_scope, cache_key

passed = 0
failed = 0

def eq(a, e, msg=''):
    global passed, failed
    if a == e: passed += 1
    else:
        failed += 1
        print(f'FAIL: {msg}: expected {e!r}, got {a!r}')

def inn(n, h, msg=''):
    global passed, failed
    if n in h: passed += 1
    else:
        failed += 1
        print(f'FAIL: {msg}: {n!r} not in {h!r}')

def nn(v, msg=''):
    global passed, failed
    if v is not None: passed += 1
    else:
        failed += 1
        print(f'FAIL: {msg}: expected not None')

def is_none(v, msg=''):
    global passed, failed
    if v is None: passed += 1
    else:
        failed += 1
        print(f'FAIL: {msg}: expected None, got {v!r}')

factory = RequestFactory()
today = datetime.date.today()

print('--- parse_date_range ---')
s, e, err = parse_date_range(factory.get('/'))
is_none(err, 'default no error')
eq(e, today, 'default end=today')
eq((today - s).days, 364, 'default 364d')

s, e, err = parse_date_range(factory.get('/', {'start_date': '2026-01-01', 'end_date': '2026-06-30'}))
is_none(err, 'custom no error')
eq(s, datetime.date(2026, 1, 1), 'custom start')
eq(e, datetime.date(2026, 6, 30), 'custom end')

s, e, err = parse_date_range(factory.get('/', {'start_date': '2026/01/01'}))
nn(err, 'invalid format error')
inn('YYYY-MM-DD', err, 'error mentions format')

s, e, err = parse_date_range(factory.get('/', {'start_date': '2026-06-30', 'end_date': '2026-01-01'}))
nn(err, 'start>end error')
inn('不能晚于', err, 'error start>end')

s, e, err = parse_date_range(factory.get('/', {'start_date': '2025-01-01', 'end_date': '2026-12-31'}))
nn(err, 'range too wide')
inn('不能超过', err, 'error range limit')

print('--- make_range_filter ---')
q = make_range_filter(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31), 'created_at')
children = dict(q.children)
inn('created_at__gte', children, 'has gte')
inn('created_at__lt', children, 'has lt')
eq(children['created_at__lt'], datetime.datetime(2026, 2, 1, 0, 0, 0), 'end=Feb1')

print('--- build_meta ---')
meta = build_meta(datetime.date(2026, 1, 1), datetime.date(2026, 6, 30))
eq(meta['start_date'], '2026-01-01', 'meta start')
eq(meta['end_date'], '2026-06-30', 'meta end')
eq(meta['timezone'], 'Asia/Shanghai', 'meta tz')
inn('generated_at', meta, 'meta generated_at')

print('--- calc_rate ---')
eq(calc_rate(1, 3), '33.3%', '1/3')
eq(calc_rate(0, 0), '0.0%', '0/0')
eq(calc_rate(3, 3), '100.0%', '3/3')

print('--- cache scope ---')
u = MagicMock(); u.is_supper = True; u.is_global_admin = False
eq(get_cache_scope(u), 'all', 'super=all')
u.is_supper = False; u.is_global_admin = True
eq(get_cache_scope(u), 'all', 'global_admin=all')
u.is_global_admin = False; u.tenant_id = 'tdyw'
eq(get_cache_scope(u), 'tenant:tdyw', 'normal=tenant:id')
eq(cache_key('overview', 'all', '2026-01-01', '2026-06-30'),
   'data_analysis:v1:overview:all:2026-01-01:2026-06-30', 'cache key')

print('--- build_monthly_trend ---')
from apps.fault.models import FaultRecord
qs = FaultRecord.objects.none()
r = build_monthly_trend(qs, 'fault_date', datetime.date(2026, 1, 1), datetime.date(2026, 6, 30))
eq(len(r), 6, '6 months')
eq(r[0]['month'], '2026-01', 'first')
eq(r[-1]['month'], '2026-06', 'last')
for item in r:
    eq(item['count'], 0, f'{item["month"]} =0')

r2 = build_monthly_trend(qs, 'fault_date', datetime.date(2025, 11, 1), datetime.date(2026, 2, 28))
eq(len(r2), 4, '4 months cross year')
eq(r2[0]['month'], '2025-11', 'cross first')
eq(r2[-1]['month'], '2026-02', 'cross last')

print('--- build_distribution ---')
r3 = build_distribution(qs, 'fault_level')
eq(r3, [], 'empty -> empty')

print(f'\n=== {passed} passed, {failed} failed ===')
