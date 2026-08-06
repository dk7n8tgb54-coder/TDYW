import os, sys
sys.path.insert(0, '/data/spug/spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django; django.setup()
from apps.document.models import DocumentTransfer, DocumentFilePublic
from apps.document.constants import TransferStatus

print('=== Latest 6 transfers ===')
for t in DocumentTransfer.objects.order_by('-id')[:6]:
    fp = t.file_path[:70] if t.file_path else 'EMPTY'
    ctid = (t.celery_task_id[:30] + '...') if t.celery_task_id else 'None'
    print(f'id={t.id} name={t.file_name[:20]} status={t.status} file_path={fp} celery_task_id={ctid}')

print()
print('=== Transfer 280/281 detail ===')
for tid in [280, 281]:
    t = DocumentTransfer.objects.filter(id=tid).first()
    if t:
        print(f'id={t.id} name={t.file_name} status={t.status} file_path={repr(t.file_path)} celery_task_id={repr(t.celery_task_id)} file_hash={t.file_hash[:30]}')

print()
print('=== File records with same hash as 280/281 ===')
for tid in [280, 281]:
    t = DocumentTransfer.objects.filter(id=tid).first()
    if t and t.file_hash:
        # Find OLD completed transfers with same hash
        old = DocumentTransfer.objects.filter(
            file_hash=t.file_hash,
            status=TransferStatus.COMPLETED.value
        ).exclude(id=tid).order_by('-id')
        for o in old:
            print(f'  OLD: id={o.id} name={o.file_name[:20]} status={o.status} file_path={repr(o.file_path[:50])}')
        # Find file records
        files = DocumentFilePublic.objects.filter(name__contains=t.file_name[:10])
        for f in files:
            print(f'  FILE: id={f.id} name={f.name[:20]} physical_name={f.physical_name[:30]} folder_id={f.folder_id}')
