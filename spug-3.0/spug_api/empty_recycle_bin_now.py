#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键清空回收站
最简单粗暴的清理方式，适合紧急清理大量测试数据

警告: 此操作不可恢复！

使用方法:
    python empty_recycle_bin_now.py
"""

import os
import sys

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'spug_api'))

import django
django.setup()

from django.db import connection

def main():
    print("=" * 60)
    print("🗑️  一键清空回收站")
    print("=" * 60)
    
    # 统计
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM tdyw_document_folder_private WHERE is_deleted = 1")
        private_folders = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tdyw_document_folder_public WHERE is_deleted = 1")
        public_folders = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tdyw_document_file_private WHERE is_deleted = 1")
        private_files = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tdyw_document_file_public WHERE is_deleted = 1")
        public_files = cursor.fetchone()[0]
        
        total = private_folders + public_folders + private_files + public_files
    
    if total == 0:
        print("\n✅ 回收站已经是空的")
        return
    
    print(f"\n发现数据:")
    print(f"  私有文件夹: {private_folders}")
    print(f"  公共文件夹: {public_folders}")
    print(f"  私有文件: {private_files}")
    print(f"  公共文件: {public_files}")
    print(f"  总计: {total}")
    
    confirm = input("\n⚠️  确定要全部清空吗？输入 '清空' 继续: ")
    if confirm != '清空':
        print("❌ 已取消")
        return
    
    print("\n正在清空...")
    
    with connection.cursor() as cursor:
        # 删除文件
        cursor.execute("DELETE FROM tdyw_document_file_private WHERE is_deleted = 1")
        cursor.execute("DELETE FROM tdyw_document_file_public WHERE is_deleted = 1")
        
        # 删除文件夹
        cursor.execute("DELETE FROM tdyw_document_folder_private WHERE is_deleted = 1")
        cursor.execute("DELETE FROM tdyw_document_folder_public WHERE is_deleted = 1")
    
    print(f"\n✅ 已清空 {total} 项数据")
    print("=" * 60)
    print("⚠️  注意: 数据库记录已删除，但物理文件可能仍存在")
    print("   如需清理磁盘空间，请手动删除 storage/documents 目录")
    print("=" * 60)

if __name__ == '__main__':
    main()
