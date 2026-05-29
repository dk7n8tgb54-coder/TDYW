import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.runlog.models import RunLog

print(f'总记录数: {RunLog.objects.count()}')
print(f'in_progress: {RunLog.objects.filter(status="in_progress").count()}')
print(f'resolved: {RunLog.objects.filter(status="resolved").count()}')
print(f'P0: {RunLog.objects.filter(severity="P0").count()}')
print(f'P1: {RunLog.objects.filter(severity="P1").count()}')
print(f'P2: {RunLog.objects.filter(severity="P2").count()}')

from django.db import connection
with connection.cursor() as cursor:
    cursor.execute("SHOW INDEX FROM runlog_run_logs")
    indexes = cursor.fetchall()
    print(f'\n当前索引数量: {len(indexes)}')
    for idx in indexes:
        print(f'  - {idx[2]} on ({idx[4]})')
