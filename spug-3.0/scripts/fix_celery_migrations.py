#!/usr/bin/env python
import os
import sys
sys.path.insert(0, '/data/spug/spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django
django.setup()

from django.db import connection
cursor = connection.cursor()

# 获取当前最大id
cursor.execute("SELECT MAX(id) FROM django_migrations")
max_id = cursor.fetchone()[0] or 0

# 插入 django_celery_results 的迁移记录
migrations = [
    ('django_celery_results', '0001_initial'),
    ('django_celery_results', '0002_add_task_name_args_kwargs'),
    ('django_celery_results', '0003_auto_20181106_1101'),
    ('django_celery_results', '0004_auto_20190516_0412'),
    ('django_celery_results', '0005_taskresult_worker'),
    ('django_celery_results', '0006_taskresult_date_created'),
    ('django_celery_results', '0007_remove_taskresult_hidden'),
    ('django_celery_results', '0008_chordcounter'),
    ('django_celery_results', '0009_groupresult'),
    ('django_celery_results', '0010_remove_duplicate_indices'),
    ('django_celery_results', '0011_taskresult_periodic_task_name'),
]

for app, name in migrations:
    max_id += 1
    cursor.execute(
        "INSERT INTO django_migrations (id, app, name, applied) VALUES (%s, %s, %s, NOW())",
        [max_id, app, name]
    )
    print(f"Inserted: {app} - {name}")

print("\nDone!")
