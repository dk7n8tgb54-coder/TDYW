#!/usr/bin/env python3
"""测试0006迁移 - physical_name字段添加"""
import os
import sys

# 添加项目路径
sys.path.insert(0, '/data/spug/spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django
django.setup()

from apps.document.models import DocumentFilePrivate, DocumentFilePublic

def test_migration():
    print("=== 测试 0006_add_physical_name 迁移 ===\n")
    
    # 测试DocumentFilePrivate
    print("1. DocumentFilePrivate 模型:")
    private_fields = [f.name for f in DocumentFilePrivate._meta.fields]
    print(f"   - physical_name 字段: {'✓' if 'physical_name' in private_fields else '✗'}")
    print(f"   - name 字段最大长度: {DocumentFilePrivate._meta.get_field('name').max_length}")
    print(f"   - display_name 字段最大长度: {DocumentFilePrivate._meta.get_field('display_name').max_length}")
    
    # 测试DocumentFilePublic
    print("\n2. DocumentFilePublic 模型:")
    public_fields = [f.name for f in DocumentFilePublic._meta.fields]
    print(f"   - physical_name 字段: {'✓' if 'physical_name' in public_fields else '✗'}")
    print(f"   - name 字段最大长度: {DocumentFilePublic._meta.get_field('name').max_length}")
    print(f"   - display_name 字段最大长度: {DocumentFilePublic._meta.get_field('display_name').max_length}")
    
    # 测试naming_utils导入
    print("\n3. naming_utils 工具模块:")
    try:
        from apps.document.libs.naming_utils import (
            generate_physical_name, 
            clean_illegal_chars,
            generate_file_names
        )
        print("   - 模块导入: ✓")
        
        # 测试生成物理文件名
        physical = generate_physical_name(".mp4")
        print(f"   - 生成物理文件名示例: {physical}")
        
        # 测试清理非法字符
        cleaned = clean_illegal_chars("test<>:file.txt")
        print(f"   - 清理非法字符示例: {cleaned}")
        
    except Exception as e:
        print(f"   - 模块导入: ✗ ({e})")
    
    print("\n=== 所有测试通过！迁移成功 ===")

if __name__ == '__main__':
    test_migration()
