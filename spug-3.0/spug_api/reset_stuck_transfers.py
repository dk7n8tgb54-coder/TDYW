#!/usr/bin/env python3
"""
重置卡住的MERGING传输任务
"""
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "spug.settings")

import django
django.setup()

from apps.document.models import DocumentTransfer
from apps.document.constants import TransferStatus

def reset_stuck_transfers():
    # 重置卡住的MERGING任务为UPLOADING，让用户可以重新合并
    stuck = DocumentTransfer.objects.filter(status=TransferStatus.MERGING.value)
    print(f"Found {stuck.count()} stuck MERGING transfers")
    for t in stuck:
        t.status = TransferStatus.UPLOADING.value
        t.save()
        print(f"Reset transfer {t.id}: {t.file_name}")
    print("Done!")

if __name__ == "__main__":
    reset_stuck_transfers()
