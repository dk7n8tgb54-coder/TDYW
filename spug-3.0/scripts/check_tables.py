import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()
from django.db import connection
cursor = connection.cursor()
cursor.execute("SHOW TABLES LIKE 'spug_document%'")
tables = cursor.fetchall()
for t in tables:
    print(t[0])
