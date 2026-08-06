#!/bin/bash
echo "=== Celery worker processes ==="
ps aux | grep celery | grep -v grep

echo ""
echo "=== Celery queues in Redis ==="
redis-cli -n 0 LLEN celery 2>/dev/null
redis-cli -n 0 LLEN merge 2>/dev/null
redis-cli -n 0 LLEN batch 2>/dev/null
redis-cli -n 0 KEYS "*" 2>/dev/null | head -20

echo ""
echo "=== Supervisor celery config ==="
cat /etc/supervisor/conf.d/11-celery-merge.conf 2>/dev/null

echo ""
echo "=== Check save_task_id_to_transfer for id=270 ==="
cd /data/spug/spug_api
python -c "
import os; os.environ['DJANGO_SETTINGS_MODULE']='spug.settings'
import django; django.setup()
from apps.document.models import DocumentTransfer
t = DocumentTransfer.objects.get(id=270)
print(f'id=270 user_id={t.user_id} status={t.status} celery_task_id={t.celery_task_id}')
# Try the update manually
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute('UPDATE document_transfer SET celery_task_id=%s WHERE id=%s', ['test-uuid', 270])
    print(f'rows affected: {cursor.rowcount}')
    connection.connection.rollback()
    print('rolled back (test only)')
" 2>&1 | grep -v "INFO\|^$"
