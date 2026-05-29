#!/usr/bin/env python3
"""
修复文件夹删除时级联删除文件的问题
将外键从 CASCADE 改为 SET NULL
"""
import os
import sys
import re

sys.path.insert(0, '/data/spug/spug_api')
os.environ['DJANGO_SETTINGS_MODULE'] = 'spug.settings'

import django
django.setup()
from django.db import connection

def get_foreign_key_info(cursor, table_name):
    """获取表的外键信息"""
    cursor.execute(f"SHOW CREATE TABLE {table_name}")
    row = cursor.fetchone()
    create_sql = row[1]
    
    # 解析外键约束
    fk_pattern = r"CONSTRAINT `([^`]+)` FOREIGN KEY \(`([^`]+)`\) REFERENCES `([^`]+)` \(`([^`]+)`\) ON DELETE (\w+)"
    fks = re.findall(fk_pattern, create_sql)
    return fks

def fix_foreign_keys():
    cursor = connection.cursor()
    
    tables = ['spug_document_file_private', 'spug_document_file_public']
    
    for table in tables:
        print(f"\n{'='*60}")
        print(f"Processing table: {table}")
        print('='*60)
        
        # 获取当前外键
        fks = get_foreign_key_info(cursor, table)
        print(f"Current foreign keys:")
        for fk in fks:
            print(f"  - {fk[0]}: {fk[1]} -> {fk[2]}.{fk[3]} ON DELETE {fk[4]}")
        
        # 找到 folder_id 外键
        folder_fk = None
        for fk in fks:
            if fk[1] == 'folder_id':
                folder_fk = fk[0]
                break
        
        if not folder_fk:
            print(f"  ⚠️ No folder_id foreign key found in {table}")
            continue
        
        # 删除旧的外键
        print(f"\nDropping foreign key: {folder_fk}")
        try:
            cursor.execute(f"ALTER TABLE {table} DROP FOREIGN KEY {folder_fk};")
            print(f"  ✅ Dropped successfully")
        except Exception as e:
            print(f"  ⚠️ Error: {e}")
        
        # 添加新的外键（SET NULL）
        ref_table = 'spug_document_folder_private' if 'private' in table else 'spug_document_folder_public'
        new_fk_name = f"{table}_folder_id_fk"
        
        print(f"\nAdding new foreign key: {new_fk_name}")
        print(f"  Reference: {ref_table}(id) ON DELETE SET NULL")
        try:
            cursor.execute(f"""
                ALTER TABLE {table} 
                ADD CONSTRAINT {new_fk_name} 
                FOREIGN KEY (folder_id) REFERENCES {ref_table}(id) ON DELETE SET NULL;
            """)
            print(f"  ✅ Added successfully")
        except Exception as e:
            print(f"  ❌ Error: {e}")
    
    # 验证结果
    print(f"\n{'='*60}")
    print("Verification")
    print('='*60)
    for table in tables:
        fks = get_foreign_key_info(cursor, table)
        print(f"\n{table}:")
        for fk in fks:
            if fk[1] == 'folder_id':
                print(f"  ✅ {fk[0]}: ON DELETE {fk[4]}")
    
    print("\n" + "="*60)
    print("✅ Foreign key fix completed!")
    print("="*60)

if __name__ == '__main__':
    fix_foreign_keys()
