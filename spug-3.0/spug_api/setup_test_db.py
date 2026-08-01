"""Create test database by copying schema from dev database."""
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()
import pymysql
from django.conf import settings

db = settings.DATABASES['default']
conn = pymysql.connect(host=db['HOST'], port=int(db['PORT']), user=db['USER'], password=db['PASSWORD'])
c = conn.cursor()

try:
    c.execute("SELECT Id FROM information_schema.processlist WHERE db='test_spug'")
    for row in c.fetchall():
        c.execute(f"KILL {row[0]}")
except Exception:
    pass
c.execute('DROP DATABASE IF EXISTS test_spug')
c.execute('CREATE DATABASE test_spug CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci')
conn.close()

conn = pymysql.connect(host=db['HOST'], port=int(db['PORT']), user=db['USER'], password=db['PASSWORD'], database='spug')
c = conn.cursor()
c.execute("SHOW TABLES")
tables = [row[0] for row in c.fetchall()]
conn.close()

conn = pymysql.connect(host=db['HOST'], port=int(db['PORT']), user=db['USER'], password=db['PASSWORD'], database='test_spug')
c = conn.cursor()
c.execute("SET FOREIGN_KEY_CHECKS=0")
for table in tables:
    c2 = conn.cursor()
    c2.execute(f"SHOW CREATE TABLE spug.{table}")
    create_sql = c2.fetchone()[1]
    try:
        c.execute(f"DROP TABLE IF EXISTS `{table}`")
        c.execute(create_sql)
    except Exception as e:
        print(f"Error creating {table}: {e}")
c.execute("SET FOREIGN_KEY_CHECKS=1")
conn.commit()
conn.close()
print(f"Copied {len(tables)} tables to test_spug")

conn = pymysql.connect(host=db['HOST'], port=int(db['PORT']), user=db['USER'], password=db['PASSWORD'], database='spug')
c = conn.cursor()
c.execute("SELECT app, name FROM django_migrations ORDER BY id")
migrations = c.fetchall()
conn.close()

conn = pymysql.connect(host=db['HOST'], port=int(db['PORT']), user=db['USER'], password=db['PASSWORD'], database='test_spug')
c = conn.cursor()
for app, name in migrations:
    c.execute("INSERT INTO django_migrations (app, name, applied) VALUES (%s, %s, NOW())", (app, name))
conn.commit()
conn.close()
print(f"Copied {len(migrations)} migration records to test_spug")
