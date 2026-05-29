#!/usr/bin/env python3
import pymysql

# 数据库连接配置
conn = pymysql.connect(
    host='db',
    user='root',
    password='spug.cc',
    database='spug'
)

try:
    with conn.cursor() as cursor:
        print("步骤1: 删除旧的外键约束...")
        cursor.execute("""
            ALTER TABLE spug_document_file
            DROP FOREIGN KEY spug_document_file_folder_id_refs_id
        """)

        print("步骤2: 将原表重命名为私有表...")
        cursor.execute("ALTER TABLE spug_document_folder RENAME TO spug_document_folder_private")
        cursor.execute("ALTER TABLE spug_document_file RENAME TO spug_document_file_private")

        print("步骤3: 重新添加外键到私有表...")
        cursor.execute("""
            ALTER TABLE spug_document_file_private
            ADD CONSTRAINT spug_document_file_private_folder_id_refs_id
            FOREIGN KEY (folder_id) REFERENCES spug_document_folder_private(id) ON DELETE CASCADE
        """)

        print("步骤4: 创建公共文件夹表...")
        cursor.execute("""
            CREATE TABLE spug_document_folder_public (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(200) NOT NULL COMMENT '文件夹名称',
                parent_id INT NULL COMMENT '父文件夹ID',
                created_by_id INT NULL COMMENT '创建人ID',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                INDEX idx_parent_id (parent_id),
                INDEX idx_created_by (created_by_id),
                INDEX idx_created_at (created_at),
                FOREIGN KEY (parent_id) REFERENCES spug_document_folder_public(id) ON DELETE CASCADE,
                FOREIGN KEY (created_by_id) REFERENCES users(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='公共文档文件夹'
        """)

        print("步骤5: 创建公共文件表...")
        cursor.execute("""
            CREATE TABLE spug_document_file_public (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(200) NOT NULL COMMENT '文件名',
                folder_id INT NULL COMMENT '所属文件夹ID',
                file_path VARCHAR(500) NOT NULL COMMENT '文件存储路径',
                file_size BIGINT NOT NULL DEFAULT 0 COMMENT '文件大小(字节)',
                file_type VARCHAR(500) NOT NULL COMMENT '文件类型',
                created_by_id INT NULL COMMENT '上传人ID',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '上传时间',
                INDEX idx_folder_id (folder_id),
                INDEX idx_created_by (created_by_id),
                INDEX idx_created_at (created_at),
                UNIQUE KEY uk_folder_name (folder_id, name),
                FOREIGN KEY (folder_id) REFERENCES spug_document_folder_public(id) ON DELETE CASCADE,
                FOREIGN KEY (created_by_id) REFERENCES users(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='公共文档文件'
        """)

    conn.commit()
    print("\n✓ 分表完成!")
except Exception as e:
    conn.rollback()
    print(f"\n✗ 错误: {e}")
finally:
    conn.close()
