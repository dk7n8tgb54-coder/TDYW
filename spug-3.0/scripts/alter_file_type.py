import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()
from django.db import connection
cursor = connection.cursor()

# 修改 file_type 字段长度
cursor.execute('ALTER TABLE spug_document_file_private MODIFY COLUMN file_type VARCHAR(100)')
cursor.execute('ALTER TABLE spug_document_file_public MODIFY COLUMN file_type VARCHAR(100)')

print('成功修改 file_type 字段长度为 100')
