#!/usr/bin/env python
"""检查运行日志表索引"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from django.db import connection

def check_indexes():
    """检查runlog_run_logs表的索引"""
    print("="*70)
    print("  运行日志表索引检查")
    print("="*70)

    with connection.cursor() as cursor:
        # 查询表的所有索引
        cursor.execute("""
            SHOW INDEX FROM runlog_run_logs
        """)
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

        # 按顺序显示索引
        print("\n当前索引列表:\n")
        for idx_name, info in sorted(index_dict.items()):
            # 对列按顺序排序
            columns = [col[1] for col in sorted(info['columns'], key=lambda x: x[0])]
            unique = "唯一" if info['non_unique'] == 0 else "非唯一"
            print(f"  📌 {idx_name}")
            print(f"     类型: {unique}")
            print(f"     字段: {', '.join(columns)}")
            print()

    # 检查关键的复合索引
    print("="*70)
    print("  关键索引检查")
    print("="*70)

    expected_indexes = [
        ('runlog_run_logs_tenant_id_status_severity_idx', ['tenant_id', 'status', 'severity']),
        ('runlog_run_logs_tenant_id_created_at_idx', ['tenant_id', 'created_at']),
        ('runlog_run_logs_tenant_id_status_idx', ['tenant_id', 'status']),
        ('runlog_run_logs_tenant_id_severity_idx', ['tenant_id', 'severity']),
    ]

    all_found = True
    for idx_name, columns in expected_indexes:
        if idx_name in index_dict:
            actual_columns = [col[1] for col in sorted(index_dict[idx_name]['columns'], key=lambda x: x[0])]
            if actual_columns == columns:
                print(f"  ✅ {idx_name} - 正确")
            else:
                print(f"  ⚠️  {idx_name} - 字段不匹配")
                print(f"      期望: {columns}")
                print(f"      实际: {actual_columns}")
        else:
            print(f"  ❌ {idx_name} - 未找到")
            all_found = False

    print()

    if not all_found:
        print("="*70)
        print("  建议执行以下SQL创建缺失的索引:")
        print("="*70)
        print()

        for idx_name, columns in expected_indexes:
            if idx_name not in index_dict:
                col_str = ', '.join(columns)
                print(f"CREATE INDEX {idx_name} ON runlog_run_logs ({col_str});")

        print()

if __name__ == '__main__':
    check_indexes()
