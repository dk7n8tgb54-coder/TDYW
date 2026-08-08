#!/usr/bin/env python
"""Wrapper to run WP5 remediation tests inside Docker."""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()
# Now exec the test file
test_file = os.path.join(os.path.dirname(__file__), 'tests', 'tenant_isolation', 'test_wp5_remediation.py')
with open(test_file, encoding='utf-8') as f:
    code = f.read()
exec(compile(code, test_file, 'exec'), {'__name__': '__main__'})
