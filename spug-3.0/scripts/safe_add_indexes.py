#!/usr/bin/env python3
import logging
import os
import configparser
import pymysql
from pymysql.err import OperationalError, ProgrammingError
import time

# 1. 配置化+日志标准化
config = configparser.ConfigParser()
config.read('db_config.ini')  # 抽离配置，避免硬编码

# 默认配置
LOG_LEVEL = config.get('log', 'level', fallback='INFO')
TABLE_SIZE_THRESHOLD = config.getint('index', 'size_threshold', fallback=10000)  # 可配置阈值

# 数据库连接配置
DB_HOST = config.get('database', 'host', fallback='localhost')
DB_USER = config.get('database', 'user', fallback='root')
DB_PASSWORD = config.get('database', 'password', fallback='spug.cc')
DB_NAME = config.get('database', 'name', fallback='spug')

# 日志配置（含操作人、时间、SQL、耗时）
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(user)s - %(levelname)s - %(sql)s - %(elapsed)s - %(message)s',
    filename='safe_add_indexes.log'
)

def add_index_safely(conn, table_name, index_name, index_columns):
    """
    安全添加索引：小表直接加，大表用Online DDL
    """
    try:
        # 前置校验：检查表/索引是否存在
        with conn.cursor() as cursor:
            # 检查表存在
            cursor.execute(f"SHOW TABLES LIKE '{table_name}'")
            if not cursor.fetchone():
                logging.error(f"表{table_name}不存在", extra={'user': os.getlogin(), 'sql': '', 'elapsed': 0})
                return False
            
            # 检查索引是否已存在
            cursor.execute(f"SHOW INDEX FROM {table_name} WHERE Key_name = '{index_name}'")
            if cursor.fetchone():
                logging.info(f"索引{index_name}已存在，跳过", extra={'user': os.getlogin(), 'sql': '', 'elapsed': 0})
                return True
            
            # 获取表行数
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            table_size = cursor.fetchone()[0]

            # 构造Online DDL语句（MySQL 5.6+支持）
            if table_size < TABLE_SIZE_THRESHOLD:
                sql = f"ALTER TABLE {table_name} ADD INDEX {index_name} ({index_columns})"
            else:
                # 大表使用Online DDL，无锁添加索引
                sql = f"ALTER TABLE {table_name} ADD INDEX {index_name} ({index_columns}) ALGORITHM=INPLACE, LOCK=NONE"
            
            # 执行索引添加（带超时）
            start_time = time.time()
            cursor.execute(sql)
            conn.commit()
            elapsed = time.time() - start_time
            logging.info(f"索引{index_name}添加成功", extra={'user': os.getlogin(), 'sql': sql, 'elapsed': elapsed})
            return True

    except (OperationalError, ProgrammingError) as e:
        conn.rollback()
        logging.error(f"添加索引失败：{str(e)}", extra={'user': os.getlogin(), 'sql': sql, 'elapsed': 0})
        return False

# 使用示例
if __name__ == "__main__":
    # 建立数据库连接
    conn = pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )
    
    try:
        # 为私有文件夹表添加索引
        add_index_safely(
            conn,
            'spug_document_folder_private',
            'idx_tenant_id',
            'tenant_id'
        )
        
        add_index_safely(
            conn,
            'spug_document_folder_private',
            'idx_tenant_parent',
            'tenant_id, parent_id'
        )
        
        # 为私有文件表添加索引
        add_index_safely(
            conn,
            'spug_document_file_private',
            'idx_tenant_id',
            'tenant_id'
        )
        
        add_index_safely(
            conn,
            'spug_document_file_private',
            'idx_tenant_folder',
            'tenant_id, folder_id'
        )
        
        # 为公共文件夹表添加唯一索引
        add_index_safely(
            conn,
            'spug_document_folder_public',
            'idx_name_parent',
            'name, parent_id'
        )
    finally:
        conn.close()