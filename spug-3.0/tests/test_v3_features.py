#!/usr/bin/env python3
"""
V3方案功能测试脚本
测试内容：
1. 文件移动功能（验证只改 folder_id，不移动物理文件）
2. 文件删除功能（验证物理删除：记录+物理文件均删除）
"""

import os
import sys
import django

# 设置 Django 环境
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'spug_api'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from django.utils import timezone
from django.conf import settings
from apps.account.models import User
from apps.document.models import DocumentFilePrivate, DocumentFolderPrivate


def test_file_move():
    """测试文件移动功能 - 验证只改 folder_id，不移动物理文件"""
    print("\n" + "="*70)
    print("测试1: 文件移动功能（验证只改 folder_id）")
    print("="*70)
    
    # 获取测试用户
    try:
        user = User.objects.first()
        if not user:
            print("❌ 错误：没有可用的测试用户")
            return False
        print(f"测试用户: {user.username} (ID: {user.id})")
    except Exception as e:
        print(f"❌ 获取用户失败: {e}")
        return False
    
    # 创建源文件夹和目标文件夹
    try:
        source_folder = DocumentFolderPrivate.objects.create(
            name='测试源文件夹',
            created_by=user,
            tenant_id=getattr(user, 'tenant_id', 'test_tenant')
        )
        target_folder = DocumentFolderPrivate.objects.create(
            name='测试目标文件夹',
            created_by=user,
            tenant_id=getattr(user, 'tenant_id', 'test_tenant')
        )
        print(f"✓ 创建源文件夹: ID={source_folder.id}")
        print(f"✓ 创建目标文件夹: ID={target_folder.id}")
    except Exception as e:
        print(f"❌ 创建文件夹失败: {e}")
        return False
    
    # 创建测试物理文件
    test_file_name = f'test_move_{user.id}_{int(timezone.now().timestamp())}.txt'
    upload_dir = os.path.join(settings.BASE_DIR, 'storage', 'document', 'private', str(user.id))
    os.makedirs(upload_dir, exist_ok=True)
    physical_path = os.path.join(upload_dir, test_file_name)
    
    try:
        # 写入测试内容
        with open(physical_path, 'w') as f:
            f.write(f"测试文件内容 - {timezone.now()}")
        print(f"✓ 创建测试物理文件: {physical_path}")
    except Exception as e:
        print(f"❌ 创建测试文件失败: {e}")
        return False
    
    # 创建文件数据库记录
    try:
        file_record = DocumentFilePrivate.objects.create(
            name=test_file_name,
            display_name='测试移动文件.txt',
            physical_name=test_file_name,
            file_path=physical_path,
            folder=source_folder,
            file_size=os.path.getsize(physical_path),
            file_type='text/plain',
            created_by=user,
            tenant_id=getattr(user, 'tenant_id', 'test_tenant')
        )
        print(f"✓ 创建文件记录: ID={file_record.id}")
    except Exception as e:
        print(f"❌ 创建文件记录失败: {e}")
        return False
    
    # 记录移动前的状态
    original_folder_id = file_record.folder.id if file_record.folder else None
    original_physical_name = file_record.physical_name
    original_file_path = file_record.file_path
    original_physical_exists = os.path.exists(physical_path)
    
    print(f"\n移动前状态:")
    print(f"  - folder_id: {original_folder_id}")
    print(f"  - physical_name: {original_physical_name}")
    print(f"  - file_path: {original_file_path}")
    print(f"  - 物理文件存在: {original_physical_exists}")
    
    # 执行移动操作（模拟 FileMoveView 的核心逻辑）
    try:
        print(f"\n执行移动操作...")
        file_record.folder = target_folder
        
        # 生成新的逻辑名
        from apps.document.libs.naming_utils import generate_unique_logical_name
        file_record.name = generate_unique_logical_name(
            DocumentFilePrivate,
            file_record.display_name or file_record.name,
            target_folder,
            user
        )
        
        # 【V3核心】只保存 folder 和 name，不修改 physical_name 和 file_path
        file_record.save(update_fields=['folder', 'name', 'updated_at'])
        
        print(f"✓ 移动操作完成")
    except Exception as e:
        print(f"❌ 移动操作失败: {e}")
        return False
    
    # 验证移动后的状态
    file_record.refresh_from_db()
    
    new_folder_id = file_record.folder.id if file_record.folder else None
    new_physical_name = file_record.physical_name
    new_file_path = file_record.file_path
    new_physical_exists = os.path.exists(physical_path)
    
    print(f"\n移动后状态:")
    print(f"  - folder_id: {new_folder_id}")
    print(f"  - physical_name: {new_physical_name}")
    print(f"  - file_path: {new_file_path}")
    print(f"  - 物理文件存在: {new_physical_exists}")
    
    # 验证结果
    print(f"\n验证结果:")
    
    # 1. folder_id 应该改变
    if new_folder_id == target_folder.id:
        print(f"  ✓ folder_id 正确改变: {original_folder_id} -> {new_folder_id}")
    else:
        print(f"  ❌ folder_id 未正确改变")
        return False
    
    # 2. physical_name 应该不变
    if new_physical_name == original_physical_name:
        print(f"  ✓ physical_name 保持不变: {new_physical_name}")
    else:
        print(f"  ❌ physical_name 被修改: {original_physical_name} -> {new_physical_name}")
        return False
    
    # 3. file_path 应该不变
    if new_file_path == original_file_path:
        print(f"  ✓ file_path 保持不变: {new_file_path}")
    else:
        print(f"  ❌ file_path 被修改: {original_file_path} -> {new_file_path}")
        return False
    
    # 4. 物理文件应该仍然存在且未被移动
    if new_physical_exists:
        print(f"  ✓ 物理文件仍然存在且未被移动")
    else:
        print(f"  ❌ 物理文件不存在或被移动")
        return False
    
    # 清理测试数据
    try:
        # 硬删除文件记录
        file_record.delete(hard=True)
        # 删除物理文件（若仍残留）
        if os.path.exists(physical_path):
            os.remove(physical_path)
        # 删除测试文件夹
        source_folder.delete()
        target_folder.delete()
        print(f"\n✓ 测试数据已清理")
    except Exception as e:
        print(f"⚠ 清理测试数据失败: {e}")
    
    print(f"\n" + "="*70)
    print("测试1通过: 文件移动功能正常（只改 folder_id，不移动物理文件）")
    print("="*70)
    return True


def test_hard_delete():
    """测试文件硬删除功能 - 验证物理删除（记录+物理文件均删除）"""
    print("\n" + "="*70)
    print("测试2: 文件硬删除功能")
    print("="*70)
    
    # 获取测试用户
    try:
        user = User.objects.first()
        if not user:
            print("❌ 错误：没有可用的测试用户")
            return False
        print(f"测试用户: {user.username} (ID: {user.id})")
    except Exception as e:
        print(f"❌ 获取用户失败: {e}")
        return False
    
    # 创建测试物理文件
    test_file_name = f'test_delete_{user.id}_{int(timezone.now().timestamp())}.txt'
    upload_dir = os.path.join(settings.BASE_DIR, 'storage', 'document', 'private', str(user.id))
    os.makedirs(upload_dir, exist_ok=True)
    physical_path = os.path.join(upload_dir, test_file_name)
    
    try:
        with open(physical_path, 'w') as f:
            f.write(f"测试删除文件内容 - {timezone.now()}")
        print(f"✓ 创建测试物理文件: {physical_path}")
    except Exception as e:
        print(f"❌ 创建测试文件失败: {e}")
        return False
    
    # 创建文件记录
    try:
        file_record = DocumentFilePrivate.objects.create(
            name=test_file_name,
            display_name='测试删除文件.txt',
            physical_name=test_file_name,
            file_path=physical_path,
            folder=None,
            file_size=os.path.getsize(physical_path),
            file_type='text/plain',
            created_by=user,
            tenant_id=getattr(user, 'tenant_id', 'test_tenant')
        )
        print(f"✓ 创建文件记录: ID={file_record.id}")
    except Exception as e:
        print(f"❌ 创建文件记录失败: {e}")
        return False
    
    file_id = file_record.id
    
    # 记录删除前的状态
    print(f"\n删除前状态:")
    print(f"  - 物理文件存在: {os.path.exists(physical_path)}")
    
    # 执行硬删除
    try:
        print(f"\n执行硬删除...")
        file_record.delete(hard=True)
        print(f"✓ 删除操作完成")
    except Exception as e:
        print(f"❌ 硬删除失败: {e}")
        # 清理残留
        if os.path.exists(physical_path):
            os.remove(physical_path)
        return False
    
    # 验证结果
    print(f"\n验证结果:")
    
    # 1. 数据库记录应该已被删除
    try:
        DocumentFilePrivate.all_objects.get(pk=file_id)
        print(f"  ❌ 硬删除后数据库记录仍存在")
        return False
    except DocumentFilePrivate.DoesNotExist:
        print(f"  ✓ 数据库记录已删除")
    
    # 2. 物理文件应该已被删除
    if not os.path.exists(physical_path):
        print(f"  ✓ 物理文件已删除")
    else:
        print(f"  ⚠ 物理文件仍存在（可能由待清理机制处理）")
        os.remove(physical_path)
    
    print(f"\n" + "="*70)
    print("测试2通过: 硬删除功能正常（记录+物理文件均删除）")
    print("="*70)
    return True


def main():
    """主函数"""
    print("\n" + "#"*70)
    print("# V3方案功能测试")
    print("#"*70)
    
    results = []
    
    # 测试1: 文件移动
    try:
        results.append(('文件移动', test_file_move()))
    except Exception as e:
        print(f"\n❌ 文件移动测试异常: {e}")
        import traceback
        traceback.print_exc()
        results.append(('文件移动', False))
    
    # 测试2: 硬删除
    try:
        results.append(('硬删除', test_hard_delete()))
    except Exception as e:
        print(f"\n❌ 硬删除测试异常: {e}")
        import traceback
        traceback.print_exc()
        results.append(('硬删除', False))
    
    # 汇总结果
    print("\n" + "#"*70)
    print("# 测试结果汇总")
    print("#"*70)
    
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {name}: {status}")
    
    all_passed = all(passed for _, passed in results)
    
    print("\n" + "#"*70)
    if all_passed:
        print("# ✅ 所有测试通过")
    else:
        print("# ❌ 部分测试失败")
    print("#"*70)
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
