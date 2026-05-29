# -*- coding: utf-8 -*-
import subprocess
import re

print("=== 数据库表碎片检查 ===")
print()

# 1. 检查碎片情况
print("1. 碎片情况检查：")
print("-" * 80)
print(f"{'数据库':<15} {'表名':<30} {'碎片大小(字节)':<20} {'存储引擎':<10}")
print("-" * 80)

cmd_check_fragmentation = [
    "docker", "exec", "tdyw-db", "mysql", "-uroot", "-pspug.cc", "spug",
    "-e", "SELECT table_schema, table_name, data_free, engine FROM information_schema.tables WHERE table_schema = 'spug' AND data_free > 0 ORDER BY data_free DESC"
]
result = subprocess.run(cmd_check_fragmentation, capture_output=True, text=True)

fragmented_tables = []
if result.returncode == 0:
    lines = result.stdout.strip().split('\n')
    for line in lines[1:]:  # 跳过表头
        if line.strip():
            parts = line.split('\t')
            if len(parts) >= 4:
                table_schema, table_name, data_free, engine = parts[0], parts[1], parts[2], parts[3]
                print(f"{table_schema:<15} {table_name:<30} {data_free:<20} {engine:<10}")
                fragmented_tables.append(table_name)

    if fragmented_tables:
        print("-" * 80)
        print(f"发现 {len(fragmented_tables)} 个表存在碎片")
    else:
        print("未发现碎片，数据库状态良好")
else:
    print(f"查询失败: {result.stderr}")

print()

# 2. 检查所有表
print("2. 所有表状态：")
print("-" * 100)
print(f"{'表名':<30} {'行数':<10} {'数据大小':<15} {'索引大小':<15} {'总大小':<15}")
print("-" * 100)

cmd_check_all = [
    "docker", "exec", "tdyw-db", "mysql", "-uroot", "-pspug.cc", "spug",
    "-e", "SELECT table_name, table_rows, data_length, index_length, data_length + index_length as total_size FROM information_schema.tables WHERE table_schema = 'spug' ORDER BY total_size DESC"
]
result = subprocess.run(cmd_check_all, capture_output=True, text=True)

if result.returncode == 0:
    lines = result.stdout.strip().split('\n')
    for line in lines[1:]:  # 跳过表头
        if line.strip():
            parts = line.split('\t')
            if len(parts) >= 5:
                table_name = parts[0]
                table_rows = parts[1] if parts[1] != 'NULL' else '0'
                data_length = parts[2] if parts[2] != 'NULL' else '0'
                index_length = parts[3] if parts[3] != 'NULL' else '0'
                total_size = parts[4] if parts[4] != 'NULL' else '0'
                print(f"{table_name:<30} {table_rows:<10} {data_length:<15} {index_length:<15} {total_size:<15}")
else:
    print(f"查询失败: {result.stderr}")

print()

# 3. 优化建议
print("3. 优化建议：")
print("-" * 80)
if fragmented_tables:
    print(f"建议对以下表执行 OPTIMIZE TABLE 操作：")
    for table in fragmented_tables:
        print(f"  - {table}")
    print()
    print("执行 OPTIMIZE TABLE 是正确的优化措施，可以：")
    print("  1. 回收碎片空间")
    print("  2. 优化表结构")
    print("  3. 提高查询性能")
    print()
    print("定期执行 OPTIMIZE TABLE 是推荐的数据库维护操作")
else:
    print("当前数据库无碎片，无需优化")
    print("定期执行 OPTIMIZE TABLE 仍然是良好的数据库维护习惯")

print()
print("=== 检查完成 ===")
print()
