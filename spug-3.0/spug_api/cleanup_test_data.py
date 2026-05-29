import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()
from django.db import connection

cursor = connection.cursor()

# 删除测试文件夹
test_folder_names = ['test_folder_a', 'test_folder_b', 'common_name', 'copy_source_a', 'copy_dest_a', 'copy_source_b', 'copy_dest_b', 'move_source_a', 'move_target_a', 'move_source_b', 'move_target_b', 'folder_a', 'folder_b', 'test_target', 'test_target_b', 'existing_folder']
for name in test_folder_names:
    cursor.execute("DELETE FROM spug_document_folder_private WHERE name = %s", [name])

# 删除公共空间测试文件夹
cursor.execute("DELETE FROM spug_document_folder_public WHERE name = 'public_test_folder'")

# 删除测试文件
test_file_names = ['file_a.docx', 'file_b.docx', 'duplicate_a.docx', 'duplicate_b.docx', 'move_file_a.docx', 'move_file_b.docx']
for name in test_file_names:
    cursor.execute("DELETE FROM spug_document_file_private WHERE name = %s", [name])

# 删除公共空间测试文件
cursor.execute("DELETE FROM spug_document_file_public WHERE name = 'public_file.docx'")

# 删除测试用户（不级联删除，避免 todos 表错误）
cursor.execute("DELETE FROM user_role_rel WHERE user_id IN (SELECT id FROM users WHERE username IN ('test_tenant_a', 'test_tenant_b'))")
cursor.execute("DELETE FROM users WHERE username IN ('test_tenant_a', 'test_tenant_b')")

connection.commit()
print('测试数据清理完成')
