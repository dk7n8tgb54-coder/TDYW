import os
import socket
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, '/data/spug/spug_api')

import django

django.setup()

print('RESOLVE db ->', socket.gethostbyname('db'))

from django.db import connection

with connection.cursor() as c:
    c.execute('SELECT @@hostname, @@port, @@version')
    print('SERVER', c.fetchone())
    c.execute('SHOW DATABASES')
    print('DATABASES', [r[0] for r in c.fetchall()])
    c.execute('SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s', ['spug'])
    print('SPUG_TABLE_COUNT', c.fetchone()[0])
