import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, '/data/spug/spug_api')

import django

django.setup()

from django.conf import settings

d = settings.DATABASES['default']
print('DJANGO', django.get_version())
print('DB_HOST', d.get('HOST'))
print('DB_PORT', d.get('PORT'))
print('DB_NAME', d.get('NAME'))
print('DB_USER', d.get('USER'))
print('TEST_DB_NAME', d.get('TEST', {}).get('NAME'))

print('REDIS_HOST', getattr(settings, 'REDIS_HOST', None))
print('REDIS_PORT', getattr(settings, 'REDIS_PORT', None))
print('REDIS_DB', getattr(settings, 'REDIS_DB', None))
print('CELERY_BROKER', getattr(settings, 'CELERY_BROKER_URL', None))
print('MEDIA_ROOT', getattr(settings, 'MEDIA_ROOT', None))
print('KKFILEVIEW_API_URL', getattr(settings, 'KKFILEVIEW_API_URL', None))
print('KKFILEVIEW_SERVER_URL', getattr(settings, 'KKFILEVIEW_SERVER_URL', None))
print('ALLOWED_HOSTS', settings.ALLOWED_HOSTS)

for name in ('DOCUMENT_STORAGE_ROOT', 'DOCUMENT_ROOT', 'DOCUMENTS_ROOT',
             'DEFAULT_MAX_FILE_SIZE', 'CHUNK_SIZE', 'COOP_TASK_FILE_RETENTION_DAYS'):
    print(name, getattr(settings, name, 'N/A'))

from django.conf import settings as s
print('INSTALLED_DOCUMENT_APPS', [a for a in s.INSTALLED_APPS if 'document' in a or 'regulation' in a])

# 实际连通性
from django.db import connection
try:
    with connection.cursor() as c:
        c.execute('SELECT DATABASE()')
        print('DB_CONNECT_OK', c.fetchone()[0])
except Exception as e:
    print('DB_CONNECT_FAIL', e)

try:
    from django.core.cache import cache
    cache.set('__doc_probe__', '1', 10)
    print('REDIS_OK', cache.get('__doc_probe__'))
    cache.delete('__doc_probe__')
except Exception as e:
    print('REDIS_FAIL', type(e).__name__, e)

try:
    import redis
    r = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB)
    print('REDIS_PING', r.ping())
except Exception as e:
    print('REDIS_PING_FAIL', type(e).__name__, e)

# 文档存储根目录
try:
    from apps.document.libs import document_utils
    print('HAS_document_utils', True)
except Exception as e:
    print('HAS_document_utils', False, e)
