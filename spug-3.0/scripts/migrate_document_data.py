#!/usr/bin/env python3
import pymysql
import logging

# 配置日志
logging.basicConfig(
    filename='document_migration.log',
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)

# 数据库连接配置
conn = pymysql.connect(
    host='localhost',
    user='root',
    password='spug.cc',
    database='spug'
)

try:
    with conn.cursor() as cursor:
        logging.info("开始迁移文档数据...")
        
        # 1. 迁移文件夹数据：按created_by关联租户ID
        logging.info("迁移私有文件夹数据...")
        cursor.execute("""
            UPDATE spug_document_folder_private f
            LEFT JOIN spug_account_user u ON f.created_by_id = u.id
            SET f.tenant_id = COALESCE(u.tenant_id, 'admin')
            WHERE f.tenant_id = '' OR f.tenant_id IS NULL
        """)
        private_folder_updated = cursor.rowcount
        logging.info(f"更新了 {private_folder_updated} 条私有文件夹记录")
        
        # 2. 迁移文件数据：按created_by关联租户ID
        logging.info("迁移私有文件数据...")
        cursor.execute("""
            UPDATE spug_document_file_private fi
            LEFT JOIN spug_account_user u ON fi.created_by_id = u.id
            SET fi.tenant_id = COALESCE(u.tenant_id, 'admin')
            WHERE fi.tenant_id = '' OR fi.tenant_id IS NULL
        """)
        private_file_updated = cursor.rowcount
        logging.info(f"更新了 {private_file_updated} 条私有文件记录")
        
        # 3. 确保公共表的tenant_id为NULL
        logging.info("更新公共表tenant_id为NULL...")
        cursor.execute("""
            UPDATE spug_document_folder_public
            SET tenant_id = NULL
            WHERE tenant_id IS NOT NULL
        """)
        public_folder_updated = cursor.rowcount
        logging.info(f"更新了 {public_folder_updated} 条公共文件夹记录")
        
        cursor.execute("""
            UPDATE spug_document_file_public
            SET tenant_id = NULL
            WHERE tenant_id IS NOT NULL
        """)
        public_file_updated = cursor.rowcount
        logging.info(f"更新了 {public_file_updated} 条公共文件记录")
        
        # 4. 校验数据一致性
        logging.info("校验数据一致性...")
        
        # 检查私有表是否还有空tenant_id
        cursor.execute("""
            SELECT COUNT(*) FROM spug_document_folder_private
            WHERE tenant_id = '' OR tenant_id IS NULL
        """)
        empty_folder_tenant = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM spug_document_file_private
            WHERE tenant_id = '' OR tenant_id IS NULL
        """)
        empty_file_tenant = cursor.fetchone()[0]
        
        if empty_folder_tenant == 0 and empty_file_tenant == 0:
            logging.info("数据迁移成功：所有私有表记录都已分配租户ID")
        else:
            logging.warning(f"数据迁移存在问题：还有 {empty_folder_tenant} 个文件夹和 {empty_file_tenant} 个文件的tenant_id为空")
        
        conn.commit()
        logging.info("文档数据迁移完成！")
        print("文档数据迁移完成！")
        print(f"更新了 {private_folder_updated} 条私有文件夹记录")
        print(f"更新了 {private_file_updated} 条私有文件记录")
        print(f"更新了 {public_folder_updated} 条公共文件夹记录")
        print(f"更新了 {public_file_updated} 条公共文件记录")
        
except Exception as e:
    conn.rollback()
    logging.error(f"迁移失败：{str(e)}")
    print(f"迁移失败：{str(e)}")
finally:
    conn.close()