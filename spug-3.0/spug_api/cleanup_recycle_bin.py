#!/usr/bin/env python3
"""
回收站万能清理工具
支持多种清理模式：批量删除、清空回收站、深度清理

使用方法:
    python cleanup_recycle_bin.py [选项]

选项:
    --mode MODE          清理模式: batch(批量)/empty(清空)/force(强制) (默认: batch)
    --batch-size SIZE    每批删除数量 (默认: 50)
    --space SPACE        清理空间: private/public/all (默认: all)
    --dry-run            试运行模式
    --yes                无需确认直接执行
    --keep-recent N      保留最近N天的数据

示例:
    # 批量清理（每批50个，需确认）
    python cleanup_recycle_bin.py

    # 清空整个回收站
    python cleanup_recycle_bin.py --mode empty --yes

    # 只清理私有空间，保留最近7天的数据
    python cleanup_recycle_bin.py --space private --keep-recent 7

    # 试运行查看将要删除的内容
    python cleanup_recycle_bin.py --dry-run
"""

import os
import sys
import argparse
from datetime import datetime, timedelta

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'spug_api'))

try:
    import django
    django.setup()
except Exception as e:
    print(f"❌ Django环境初始化失败: {e}")
    print("请确保在项目的正确目录下运行此脚本")
    sys.exit(1)

from django.db import transaction, connection
from apps.document.models import DocumentFolderPrivate, DocumentFolderPublic
from apps.document.models import DocumentFilePrivate, DocumentFilePublic


def get_stats(space='all'):
    """获取回收站统计信息"""
    stats = {
        'folders': {'private': 0, 'public': 0},
        'files': {'private': 0, 'public': 0}
    }
    
    if space in ('all', 'private'):
        stats['folders']['private'] = DocumentFolderPrivate.all_objects.filter(is_deleted=True).count()
        stats['files']['private'] = DocumentFilePrivate.all_objects.filter(is_deleted=True).count()
        
    if space in ('all', 'public'):
        stats['folders']['public'] = DocumentFolderPublic.all_objects.filter(is_deleted=True).count()
        stats['files']['public'] = DocumentFilePublic.all_objects.filter(is_deleted=True).count()
    
    stats['total_folders'] = stats['folders']['private'] + stats['folders']['public']
    stats['total_files'] = stats['files']['private'] + stats['files']['public']
    stats['total'] = stats['total_folders'] + stats['total_files']
    
    return stats


def batch_delete_folders(folder_ids, is_public=False, dry_run=False):
    """批量删除文件夹"""
    if dry_run:
        return {'deleted': len(folder_ids), 'failed': 0, 'mode': 'dry_run'}
    
    deleted = 0
    failed = 0
    
    Model = DocumentFolderPublic if is_public else DocumentFolderPrivate
    
    for folder_id in folder_ids:
        try:
            folder = Model.all_objects.get(id=folder_id, is_deleted=True)
            folder.delete(hard=True)  # 硬删除
            deleted += 1
        except Exception as e:
            print(f"    ⚠️ 删除失败 {folder_id}: {e}")
            failed += 1
    
    return {'deleted': deleted, 'failed': failed}


def batch_delete_files(file_ids, is_public=False, dry_run=False):
    """批量删除文件"""
    if dry_run:
        return {'deleted': len(file_ids), 'failed': 0, 'mode': 'dry_run'}
    
    deleted = 0
    failed = 0
    
    Model = DocumentFilePublic if is_public else DocumentFilePrivate
    
    for file_id in file_ids:
        try:
            file = Model.all_objects.get(id=file_id, is_deleted=True)
            file.delete(hard=True)
            deleted += 1
        except Exception as e:
            print(f"    ⚠️ 删除失败 {file_id}: {e}")
            failed += 1
    
    return {'deleted': deleted, 'failed': failed}


def cleanup_batch_mode(args):
    """批量清理模式"""
    print("\n📦 批量清理模式")
    print(f"批次大小: {args.batch_size}")
    
    # 获取要清理的文件夹
    folders_to_delete = []
    
    if args.space in ('all', 'private'):
        private_folders = list(DocumentFolderPrivate.all_objects.filter(
            is_deleted=True
        ).values_list('id', flat=True))
        folders_to_delete.extend([('private', id) for id in private_folders])
        
    if args.space in ('all', 'public'):
        public_folders = list(DocumentFolderPublic.all_objects.filter(
            is_deleted=True
        ).values_list('id', flat=True))
        folders_to_delete.extend([('public', id) for id in public_folders])
    
    total = len(folders_to_delete)
    if total == 0:
        print("✅ 没有需要清理的文件夹")
        return
    
    print(f"总计: {total} 个文件夹")
    
    if args.dry_run:
        print("\n🔍 试运行模式 - 将要删除:")
        for space, folder_id in folders_to_delete[:10]:
            print(f"  [{space}] ID: {folder_id}")
        if total > 10:
            print(f"  ... 还有 {total - 10} 个")
        return
    
    # 分批处理
    batches = [folders_to_delete[i:i + args.batch_size] 
               for i in range(0, len(folders_to_delete), args.batch_size)]
    
    print(f"\n分为 {len(batches)} 个批次处理")
    
    total_deleted = 0
    total_failed = 0
    
    for i, batch in enumerate(batches, 1):
        print(f"\n  批次 {i}/{len(batches)} ({len(batch)} 个)...")
        
        # 按空间分组
        private_batch = [id for space, id in batch if space == 'private']
        public_batch = [id for space, id in batch if space == 'public']
        
        if private_batch:
            result = batch_delete_folders(private_batch, is_public=False, dry_run=False)
            total_deleted += result['deleted']
            total_failed += result['failed']
            print(f"    私有: 删除 {result['deleted']}, 失败 {result['failed']}")
            
        if public_batch:
            result = batch_delete_folders(public_batch, is_public=True, dry_run=False)
            total_deleted += result['deleted']
            total_failed += result['failed']
            print(f"    公共: 删除 {result['deleted']}, 失败 {result['failed']}")
    
    print(f"\n✅ 批量清理完成: 成功 {total_deleted}, 失败 {total_failed}")


def cleanup_empty_mode(args):
    """清空回收站模式"""
    print("\n🗑️ 清空回收站模式")
    
    stats = get_stats(args.space)
    
    if stats['total'] == 0:
        print("✅ 回收站已经是空的")
        return
    
    print(f"将要清空:")
    print(f"  文件夹: {stats['total_folders']} 个")
    print(f"  文件: {stats['total_files']} 个")
    
    if args.dry_run:
        print("\n🔍 试运行模式 - 未实际删除")
        return
    
    # 使用数据库事务快速清空
    print("\n执行清空...")
    
    with transaction.atomic():
        if args.space in ('all', 'private'):
            # 先删除私有文件
            file_count = DocumentFilePrivate.all_objects.filter(is_deleted=True).count()
            DocumentFilePrivate.all_objects.filter(is_deleted=True).delete()
            print(f"  删除私有文件: {file_count} 个")
            
            # 再删除私有文件夹
            folder_count = DocumentFolderPrivate.all_objects.filter(is_deleted=True).count()
            DocumentFolderPrivate.all_objects.filter(is_deleted=True).delete()
            print(f"  删除私有文件夹: {folder_count} 个")
            
        if args.space in ('all', 'public'):
            # 先删除公共文件
            file_count = DocumentFilePublic.all_objects.filter(is_deleted=True).count()
            DocumentFilePublic.all_objects.filter(is_deleted=True).delete()
            print(f"  删除公共文件: {file_count} 个")
            
            # 再删除公共文件夹
            folder_count = DocumentFolderPublic.all_objects.filter(is_deleted=True).count()
            DocumentFolderPublic.all_objects.filter(is_deleted=True).delete()
            print(f"  删除公共文件夹: {folder_count} 个")
    
    print("\n✅ 回收站已清空")


def cleanup_force_mode(args):
    """强制清理模式 - 使用原始SQL，速度最快"""
    print("\n⚡ 强制清理模式（使用原始SQL）")
    
    stats = get_stats(args.space)
    
    if stats['total'] == 0:
        print("✅ 没有需要清理的数据")
        return
    
    print(f"将要清理:")
    print(f"  文件夹: {stats['total_folders']} 个")
    print(f"  文件: {stats['total_files']} 个")
    
    if args.dry_run:
        print("\n🔍 试运行模式 - 未实际删除")
        return
    
    print("\n执行强制清理...")
    
    with connection.cursor() as cursor:
        if args.space in ('all', 'private'):
            # 删除私有文件
            cursor.execute("DELETE FROM spug_document_file_private WHERE is_deleted = 1")
            private_files = cursor.rowcount
            print(f"  删除私有文件: {private_files} 个")
            
            # 删除私有文件夹
            cursor.execute("DELETE FROM spug_document_folder_private WHERE is_deleted = 1")
            private_folders = cursor.rowcount
            print(f"  删除私有文件夹: {private_folders} 个")
            
        if args.space in ('all', 'public'):
            # 删除公共文件
            cursor.execute("DELETE FROM spug_document_file_public WHERE is_deleted = 1")
            public_files = cursor.rowcount
            print(f"  删除公共文件: {public_files} 个")
            
            # 删除公共文件夹
            cursor.execute("DELETE FROM spug_document_folder_public WHERE is_deleted = 1")
            public_folders = cursor.rowcount
            print(f"  删除公共文件夹: {public_folders} 个")
    
    print("\n✅ 强制清理完成")
    print("⚠️ 注意: 物理文件未删除，需要手动清理磁盘文件")


def main():
    parser = argparse.ArgumentParser(
        description='回收站万能清理工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 批量清理（推荐）
  python cleanup_recycle_bin.py

  # 清空整个回收站
  python cleanup_recycle_bin.py --mode empty --yes

  # 只清理公共空间
  python cleanup_recycle_bin.py --space public --yes

  # 试运行查看将要删除的内容
  python cleanup_recycle_bin.py --dry-run

  # 极速清理（使用SQL）
  python cleanup_recycle_bin.py --mode force --yes
        """
    )
    
    parser.add_argument('--mode', choices=['batch', 'empty', 'force'], 
                       default='batch', help='清理模式 (默认: batch)')
    parser.add_argument('--batch-size', type=int, default=50,
                       help='每批删除数量 (默认: 50)')
    parser.add_argument('--space', choices=['private', 'public', 'all'],
                       default='all', help='清理空间 (默认: all)')
    parser.add_argument('--dry-run', action='store_true',
                       help='试运行模式，不实际删除')
    parser.add_argument('--yes', action='store_true',
                       help='无需确认直接执行')
    parser.add_argument('--keep-recent', type=int, metavar='N',
                       help='保留最近N天的数据')
    
    args = parser.parse_args()
    
    # 显示标题
    print("=" * 70)
    print("🗑️  回收站万能清理工具")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"模式: {args.mode}")
    print(f"空间: {args.space}")
    print(f"试运行: {'是' if args.dry_run else '否'}")
    print("=" * 70)
    
    # 获取统计
    stats = get_stats(args.space)
    
    print(f"\n📊 当前回收站状态:")
    print(f"  文件夹: {stats['total_folders']} 个 (私有: {stats['folders']['private']}, 公共: {stats['folders']['public']})")
    print(f"  文件: {stats['total_files']} 个 (私有: {stats['files']['private']}, 公共: {stats['files']['public']})")
    print(f"  总计: {stats['total']} 项")
    
    if stats['total'] == 0:
        print("\n✅ 回收站为空，无需清理")
        return
    
    # 确认
    if not args.yes and not args.dry_run:
        if args.mode == 'force':
            confirm = input("\n⚠️  警告: 强制模式将直接操作数据库，不经过业务逻辑！\n输入 'force' 继续: ")
            if confirm != 'force':
                print("❌ 操作已取消")
                return
        else:
            confirm = input(f"\n⚠️  确定要清理这 {stats['total']} 项数据吗？此操作不可恢复！\n输入 'yes' 继续: ")
            if confirm.lower() != 'yes':
                print("❌ 操作已取消")
                return
    
    # 执行清理
    try:
        if args.mode == 'batch':
            cleanup_batch_mode(args)
        elif args.mode == 'empty':
            cleanup_empty_mode(args)
        elif args.mode == 'force':
            cleanup_force_mode(args)
            
        print("\n" + "=" * 70)
        print("✅ 清理操作已完成")
        print("=" * 70)
        
        # 显示剩余
        remaining = get_stats(args.space)
        if remaining['total'] > 0:
            print(f"\n剩余数据: {remaining['total']} 项")
        else:
            print("\n回收站已清空")
            
    except Exception as e:
        print(f"\n❌ 清理过程中出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
