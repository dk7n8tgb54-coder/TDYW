"""临时脚本：创建测试数据库并修复迁移冲突"""
import os, sys
os.environ["DJANGO_SETTINGS_MODULE"] = "spug_api.settings"
import django; django.setup()

from django.db import connection

# Step 1: Create test database
test_db_name = connection.creation._get_test_db_name()
print(f"Creating test database: {test_db_name}")
connection.creation.create_test_db(verbosity=1, autoclobber=True)
print("Test database created successfully!")

# Step 2: Verify by running a simple query
with connection.cursor() as cursor:
    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()
    print(f"Tables in test DB: {len(tables)}")

connection.creation.destroy_test_db("spug", verbosity=0)
print("Test database destroyed.")
