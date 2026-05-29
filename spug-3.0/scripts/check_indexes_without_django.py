#!/usr/bin/env python
"""不依赖Django，直接连接MySQL检查索引"""
import configparser
import pymysql

def get_db_config():
    """从配置文件读取数据库配置"""
    config = configparser.ConfigParser()
    config.read('db_config.ini', encoding='utf-8')

    return {
        'host': 'localhost',
        'port': 3307,
        'user': 'spug',
        'password': 'spug123',
        'database': 'spug'
    }

def check_indexes():
    """检查runlog_run_logs表的索引"""
    try:
        db_config = get_db_config()
        conn = pymysql.connect(**db_config)

        print("="*70)
        print("  运行日志表索引检查")
        print("="*70)
        print(f"\n数据库: {db_config['database']}\n")

        with conn.cursor() as cursor:
            # 查询表的所有索引
            cursor.execute("SHOW INDEX FROM runlog_run_logs")
            indexes = cursor.fetchall()

            # 按索引名分组
            index_dict = {}
            for idx in indexes:
                index_name = idx[2]
                column_name = idx[4]
                seq_in_index = idx[3]

                if index_name not in index_dict:
                    index_dict[index_name] = {
                        'non_unique': idx[1],
                        'columns': []
                    }
                index_dict[index_name]['columns'].append((seq_in_index, column_name))

            # 显示所有索引
            print("当前索引列表:\n")
            for idx_name, info in sorted(index_dict.items()):
                columns = [col[1] for col in sorted(info['columns'], key=lambda x: x[0])]
                unique = "唯一" if info['non_unique'] == 0 else "非唯一"
                print(f"  📌 {idx_name}")
                print(f"     类型: {unique}")
                print(f"     字段: {', '.join(columns)}")
                print()

        # 检查关键索引
        print("="*70)
        print("  关键索引检查")
        print("="*70)

        # 检查两种可能的索引名
        expected_indexes = [
            ('idx_runlog_tenant_status_severity', ['tenant_id', 'status', 'severity']),
            ('idx_runlog_tenant_created', ['tenant_id', 'created_at']),
            ('runlog_run_logs_tenant_id_status_severity_idx', ['tenant_id', 'status', 'severity']),
            ('runlog_run_logs_tenant_id_created_at_idx', ['tenant_id', 'created_at']),
            ('runlog_run_logs_tenant_id_status_idx', ['tenant_id', 'status']),
            ('runlog_run_logs_tenant_id_severity_idx', ['tenant_id', 'severity']),
        ]

        found_indexes = []
        for idx_name, columns in expected_indexes:
            if idx_name in index_dict:
                actual_columns = [col[1] for col in sorted(index_dict[idx_name]['columns'], key=lambda x: x[0])]
                if actual_columns == columns:
                    print(f"  ✅ {idx_name} - 正确")
                    found_indexes.append(idx_name)

        if not found_indexes:
            print("\n  ❌ 未找到任何优化索引！")
            print("\n  请执行以下命令创建索引:")
            print("    mysql -h localhost -u root -p spug < scripts/create_runlog_indexes.sql")
        else:
            print(f"\n  ✅ 共找到 {len(found_indexes)} 个优化索引")

        conn.close()

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        print("\n提示: 请确保已安装 pymysql: pip install pymysql")
        print("      请确保 db_config.ini 文件存在且配置正确")

if __name__ == '__main__':
    check_indexes()
