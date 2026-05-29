#!/usr/bin/env python3
"""
回收站文件夹批量清理脚本
临时提升批量限制，快速清理大量回收站文件夹

使用方法:
    python cleanup_recycle_bin_folders.py

参数:
    --batch-size: 每批删除数量（默认100）
    --max-folders: 最多清理多少个（默认全部）
    --dry-run: 试运行模式（只显示不删除）
"""

import os
import sys
import django
import argparse
from datetime import datetime

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'spug_api'))
django.setup()

from django.db import transaction
from apps.document.models import DocumentFolderPrivate, DocumentFolderPublic
from apps.document.views.recycle_bin.folder_delete import RecycleBinFolderPermanentDeleteView


def get_all_deleted_folders():
    """获取所有已删除的文件夹"""
    private_folders = list(DocumentFolderPrivate.all_objects.filter(is_deleted=True).values_list('id', flat=True))
    public_folders = list(DocumentFolderPublic.all_objects.filter(is_deleted=True).values_list('id', flat=True))
    
    return {
        'private': private_folders,
        'public': public_folders,
        'total': len(private_folders) + len(public_folders)
    }


def cleanup_folders_batch(folder_ids, user_id, is_public=False, dry_run=False):
    """
    批量清理文件夹
    
    Args:
        folder_ids: 文件夹ID列表
        user_id: 用户ID（用于权限检查）
        is_public: 是否公共空间
        dry_run: 是否试运行
        
    Returns:
        dict: 清理结果
    """
    from apps.document.tasks.cleanup import async_batch_folder_permanent_delete
    
    if dry_run:
        return {
            'status': 'dry_run',
            'count': len(folder_ids),
            'folder_ids': folder_ids[:5]  # 只显示前5个
        }
    
    try:
        # 使用Celery异步任务清理
        task = async_batch_folder_permanent_delete.delay(folder_ids, user_id)
        return {
            'status': 'submitted',
            'task_id': str(task.id),
            'count': len(folder_ids)
        }
    except Exception as e:
        print(f"  ⚠️ 异步任务提交失败，使用同步清理: {e}")
        # 降级为同步清理
        return cleanup_folders_sync(folder_ids, user_id, is_public)


def cleanup_folders_sync(folder_ids, user_id, is_public=False):
    """同步清理文件夹"""
    from django.contrib.auth.models import User
    
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return {'status': 'error', 'error': f'用户不存在: {user_id}'}
    
    deleted_count = 0
    failed_count = 0
    
    for folder_id in folder_ids:
        try:
            # 根据空间类型选择模型
            if is_public:
                folder = DocumentFolderPublic.all_objects.get(id=folder_id, is_deleted=True)
            else:
                folder = DocumentFolderPrivate.all_objects.get(id=folder_id, is_deleted=True)
            
            # 执行删除
            folder.delete(hard=True)
            deleted_count += 1
            
            if deleted_count % 10 == 0:
                print(f"  已删除 {deleted_count}/{len(folder_ids)}...")
                
        except Exception as e:
            print(f"  ⚠️ 删除文件夹 {folder_id} 失败: {e}")
            failed_count += 1
    
    return {
        'status': 'completed',
        'deleted': deleted_count,
        'failed': failed_count
    }


def main():
    parser = argparse.ArgumentParser(description='清理回收站文件夹')
    parser.add_argument('--batch-size', type=int, default=100, help='每批删除数量（默认100）')
    parser.add_argument('--max-folders', type=int, default=None, help='最多清理多少个（默认全部）')
    parser.add_argument('--dry-run', action='store_true', help='试运行模式（只显示不删除）')
    parser.add_argument('--user-id', type=int, default=1, help='执行删除的用户ID（默认1）')
    args = parser.parse_args()
    
    print("=" * 70)
    print("回收站文件夹批量清理工具")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"批次大小: {args.batch_size}")
    print(f"试运行模式: {'是' if args.dry_run else '否'}")
    print("=" * 70)
    
    # 获取所有已删除的文件夹
    print("\n📊 扫描回收站...")
    folders = get_all_deleted_folders()
    
    print(f"  私有空间: {len(folders['private'])} 个")
    print(f"  公共空间: {len(folders['public'])} 个")
    print(f"  总计: {folders['total']} 个")
    
    if folders['total'] == 0:
        print("\n✅ 回收站为空，无需清理")
        return
    
    # 限制数量
    if args.max_folders and folders['total'] > args.max_folders:
        print(f"\n⚠️ 限制清理数量: {args.max_folders}/{folders['total']}")
        # 按比例分配
        private_limit = int(args.max_folders * len(folders['private']) / folders['total'])
        public_limit = args.max_folders - private_limit
        folders['private'] = folders['private'][:private_limit]
        folders['public'] = folders['public'][:public_limit]
        folders['total'] = len(folders['private']) + len(folders['public'])
    
    if args.dry_run:
        print("\n🔍 试运行模式 - 以下文件夹将被删除:")
        print(f"  私有: {folders['private'][:5]}...")
        print(f"  公共: {folders['public'][:5]}...")
        return
    
    # 确认删除
    confirm = input(f"\n⚠️ 确定要永久删除 {folders['total']} 个文件夹吗？此操作不可恢复！\n输入 'yes' 继续: ")
    if confirm.lower() != 'yes':
        print("\n❌ 操作已取消")
        return
    
    # 开始清理
    print("\n🗑️ 开始清理...")
    
    results = {
        'private': {'submitted': 0, 'batches': 0},
        'public': {'submitted': 0, 'batches': 0}
    }
    
    # 清理私有空间
    if folders['private']:
        print(f"\n清理私有空间: {len(folders['private'])} 个文件夹")
        for i in range(0, len(folders['private']), args.batch_size):
            batch = folders['private'][i:i + args.batch_size]
            print(f"  提交批次 {i//args.batch_size + 1}: {len(batch)} 个文件夹...")
            result = cleanup_folders_batch(batch, args.user_id, is_public=False, dry_run=args.dry_run)
            results['private']['submitted'] += result.get('count', 0)
            results['private']['batches'] += 1
    
    # 清理公共空间
    if folders['public']:
        print(f"\n清理公共空间: {len(folders['public'])} 个文件夹")
        for i in range(0, len(folders['public']), args.batch_size):
            batch = folders['public'][i:i + args.batch_size]
            print(f"  提交批次 {i//args.batch_size + 1}: {len(batch)} 个文件夹...")
            result = cleanup_folders_batch(batch, args.user_id, is_public=True, dry_run=args.dry_run)
            results['public']['submitted'] += result.get('count', 0)
            results['public']['batches'] += 1
    
    # 总结
    print("\n" + "=" * 70)
    print("清理完成")
    print("=" * 70)
    print(f"私有空间: {results['private']['submitted']} 个（{results['private']['batches']} 批次）")
    print(f"公共空间: {results['public']['submitted']} 个（{results['public']['batches']} 批次）")
    print(f"总计提交: {results['private']['submitted'] + results['public']['submitted']} 个")
    
    if not args.dry_run:
        print("\n⚠️ 异步任务已提交，请查看Celery日志确认删除进度")
        print("监控命令: celery -A spug worker -l info")
    
    print("=" * 70)


if __name__ == '__main__':
    main()
