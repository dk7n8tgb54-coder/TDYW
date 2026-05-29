#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import django
import time

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, '/data/spug/spug_api')
django.setup()

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.libs.document_utils import get_document_absolute_path, get_file_model, get_folder_model
from apps.account.models import User

# 测试参数
is_public = True
user_id = 5
folder_id = None

print("=" * 60)
print("测试上传路径生成")
print("=" * 60)

# 1. 测试路径生成
try:
    upload_dir = get_document_absolute_path(
        is_public=is_public,
        user_id=user_id,
        folder_id=folder_id
    )
    print(f"✓ 路径生成成功: {upload_dir}")
except Exception as e:
    print(f"✗ 路径生成失败: {e}")
    sys.exit(1)

# 2. 测试目录创建
try:
    os.makedirs(upload_dir, exist_ok=True)
    print(f"✓ 目录创建成功")
except Exception as e:
    print(f"✗ 目录创建失败: {e}")
    sys.exit(1)

# 3. 测试文件保存
try:
    test_content = b"This is a test file content"
    file_ext = '.txt'
    file_base = 'test_file'
    timestamp = int(time.time())
    unique_name = f"{file_base}_{user_id}_{timestamp}{file_ext}"
    file_path = os.path.join(upload_dir, unique_name)

    with open(file_path, 'wb+') as f:
        f.write(test_content)

    print(f"✓ 文件保存成功: {file_path}")
    print(f"  文件大小: {os.path.getsize(file_path)} bytes")
except Exception as e:
    print(f"✗ 文件保存失败: {e}")
    sys.exit(1)

# 4. 测试模型操作
try:
    user = User.objects.get(id=user_id)
    FileModel = get_file_model(is_public=is_public)
    FolderModel = get_folder_model(is_public=is_public)

    folder = None
    if folder_id:
        folder = FolderModel.objects.filter(pk=folder_id).first()

    file_record = FileModel.objects.create(
        name='test_file.txt',
        folder=folder,
        file_path=file_path,
        file_size=len(test_content),
        file_type='text/plain',
        created_by=user
    )
    print(f"✓ 数据库记录创建成功: ID={file_record.id}")
except Exception as e:
    print(f"✗ 数据库操作失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("=" * 60)
print("所有测试通过!")
print("=" * 60)

# 清理测试数据
try:
    file_record.delete()
    os.remove(file_path)
    print("✓ 测试数据已清理")
except:
    print("⚠ 测试数据清理失败(非严重错误)")
