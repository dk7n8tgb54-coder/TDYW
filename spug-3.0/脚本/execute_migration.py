#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
执行数据库分表迁移脚本
通过Django连接数据库,直接执行SQL
"""
import os
import sys
import django

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, '/data/spug/spug_api')

django.setup()

from django.conf import settings
from django.db import connection
import traceback

def execute_sql_script():
    """执行SQL迁移脚本"""
    sql_script = """
-- 步骤1: 将原表 spug_document_folder 重命名为 spug_document_folder_private
RENAME TABLE spug_document_folder TO spug_document_folder_private;

-- 步骤2: 将原表 spug_document_file 重命名为 spug_document_file_private
RENAME TABLE spug_document_file TO spug_document_file_private;

-- 步骤3: 创建空的公共文件夹表
CREATE TABLE IF NOT EXISTS `spug_document_folder_public` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(200) NOT NULL COMMENT '文件夹名称',
  `parent_id` int(11) DEFAULT NULL COMMENT '父文件夹',
  `created_by_id` int(11) DEFAULT NULL COMMENT '创建人',
  `created_at` datetime(6) NOT NULL COMMENT '创建时间',
  `updated_at` datetime(6) NOT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `spug_document_folder_public_parent_id_idx` (`parent_id`),
  KEY `spug_document_folder_public_created_by_id_idx` (`created_by_id`),
  CONSTRAINT `spug_document_folder_public_created_by_id_fk` FOREIGN KEY (`created_by_id`) REFERENCES `spug_account_user` (`id`) ON DELETE SET NULL,
  CONSTRAINT `spug_document_folder_public_parent_id_fk` FOREIGN KEY (`parent_id`) REFERENCES `spug_document_folder_public` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='公共文档文件夹';

-- 步骤4: 创建空的公共文件表
CREATE TABLE IF NOT EXISTS `spug_document_file_public` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(200) NOT NULL COMMENT '文件名',
  `file_path` varchar(500) NOT NULL COMMENT '文件存储路径',
  `file_size` bigint(20) NOT NULL DEFAULT '0' COMMENT '文件大小(字节)',
  `file_type` varchar(500) NOT NULL COMMENT '文件类型',
  `folder_id` int(11) DEFAULT NULL COMMENT '所属文件夹',
  `created_by_id` int(11) DEFAULT NULL COMMENT '上传人',
  `created_at` datetime(6) NOT NULL COMMENT '上传时间',
  PRIMARY KEY (`id`),
  KEY `spug_document_file_public_folder_id_idx` (`folder_id`),
  KEY `spug_document_file_public_created_by_id_idx` (`created_by_id`),
  CONSTRAINT `spug_document_file_public_created_by_id_fk` FOREIGN KEY (`created_by_id`) REFERENCES `spug_account_user` (`id`) ON DELETE SET NULL,
  CONSTRAINT `spug_document_file_public_folder_id_fk` FOREIGN KEY (`folder_id`) REFERENCES `spug_document_folder_public` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='公共文档文件';

-- 步骤5: 更新Django迁移记录表
INSERT INTO django_migrations (app, name, applied) VALUES
('document', '0002_document_split_public_private', NOW())
ON DUPLICATE KEY UPDATE applied = NOW();
"""

    cursor = connection.cursor()

    # 先检查现有表
    print("=" * 60)
    print("检查现有表...")
    print("=" * 60)
    cursor.execute("SHOW TABLES LIKE 'spug_document%'")
    existing_tables = cursor.fetchall()
    for table in existing_tables:
        print(f"  - {table[0]}")

    # 检查私有表是否已存在
    if existing_tables:
        private_folder_exists = any('folder_private' in t[0] for t in existing_tables)
        private_file_exists = any('file_private' in t[0] for t in existing_tables)

        if private_folder_exists and private_file_exists:
            print("\n⚠️  分表已存在,跳过迁移!")
            return

    # 执行迁移
    print("\n" + "=" * 60)
    print("开始执行分表迁移...")
    print("=" * 60)

    try:
        # 分割SQL语句并逐个执行
        statements = [s.strip() for s in sql_script.split(';') if s.strip()]
        for i, statement in enumerate(statements, 1):
            print(f"\n执行步骤 {i}/{len(statements)}: {statement[:50]}...")
            try:
                cursor.execute(statement)
                print(f"  ✅ 成功")
            except Exception as e:
                print(f"  ❌ 失败: {e}")
                raise

        connection.commit()
        print("\n" + "=" * 60)
        print("✅ 迁移完成!")
        print("=" * 60)

        # 验证迁移结果
        print("\n验证迁移结果:")
        cursor.execute("SELECT COUNT(*) FROM spug_document_folder_private")
        private_folders = cursor.fetchone()[0]
        print(f"  私有文件夹: {private_folders} 条")

        cursor.execute("SELECT COUNT(*) FROM spug_document_file_private")
        private_files = cursor.fetchone()[0]
        print(f"  私有文件: {private_files} 条")

        cursor.execute("SELECT COUNT(*) FROM spug_document_folder_public")
        public_folders = cursor.fetchone()[0]
        print(f"  公共文件夹: {public_folders} 条")

        cursor.execute("SELECT COUNT(*) FROM spug_document_file_public")
        public_files = cursor.fetchone()[0]
        print(f"  公共文件: {public_files} 条")

        print(f"\n原有数据已安全保留在私有表中!")

    except Exception as e:
        connection.rollback()
        print("\n" + "=" * 60)
        print("❌ 迁移失败!")
        print("=" * 60)
        print(f"错误信息: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        cursor.close()

if __name__ == '__main__':
    execute_sql_script()
