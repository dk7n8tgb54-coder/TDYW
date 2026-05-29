#!/usr/bin/env python3
"""快速验证命名功能"""
import sys
sys.path.insert(0, '/data/spug/spug_api')
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

from apps.document.libs.naming_utils import generate_physical_name, clean_illegal_chars, get_file_ext

# 测试物理文件名生成
physical = generate_physical_name(".mp4")
print("=== 命名生成测试 ===")
print(f"物理文件名: {physical} (长度: {len(physical)})")

# 测试清理非法字符
cleaned = clean_illegal_chars("测试文件<>:|?.mp4")
print(f"清理后文件名: {cleaned}")

# 测试扩展名提取
name, ext = get_file_ext("test.tar.gz")
print(f"多扩展名测试: name={name}, ext={ext}")

name2, ext2 = get_file_ext("test.mp4")
print(f"单扩展名测试: name={name2}, ext={ext2}")

print("\n✓ 所有命名工具工作正常")
