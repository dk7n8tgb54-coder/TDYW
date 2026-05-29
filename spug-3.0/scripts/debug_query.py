#!/usr/bin/env python3
import sys
sys.path.insert(0, '/data/spug/spug_api')
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django
django.setup()

from apps.checksheet.models import CheckSheetTemplate, CheckSheetRecord

template = CheckSheetTemplate.objects.get(project='导航科')
print(f'模板ID: {template.id}')
print(f'模板项目: {template.project}')

# 使用与 views.py 相同的查询
records = CheckSheetRecord.objects.filter(
    template=template,
    year=2026,
    month=3
)

print(f'\n查询条件: template_id={template.id}, year=2026, month=3')
print(f'记录数: {records.count()}')

print('\n所有记录:')
for r in records:
    print(f'  id={r.id}, template_id={r.template_id}, year={r.year}, month={r.month}, day={r.day}, item_index={r.item_index}, status={r.status}')

# 对比：不限制 month 的查询
print('\n不限制 month 的记录:')
for r in CheckSheetRecord.objects.filter(template=template, year=2026):
    print(f'  id={r.id}, month={r.month}, day={r.day}, item_index={r.item_index}')
