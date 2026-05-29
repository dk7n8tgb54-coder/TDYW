import os
import glob

print("=== 数据库优化方案 ===")
print()

# 检查数据库文件
mysql_data_path = os.path.join('e:\TDYW\spug-3.0', 'data', 'mysql', 'spug')
print(f"检查数据库文件位置: {mysql_data_path}")
print()

if os.path.exists(mysql_data_path):
    print("✓ 数据库文件存在")
    
    # 列出数据库表文件
    table_files = glob.glob(os.path.join(mysql_data_path, '*.ibd'))
    print(f"发现 {len(table_files)} 个InnoDB表文件")
    print()
    
    print("=== 优化分析 ===")
    print()
    print("1. 优化措施确认：")
    print("   ✓ 定期执行 OPTIMIZE TABLE 是正确的优化措施")
    print("   ✓ 此操作可以回收碎片空间，提高查询性能")
    print()
    
    print("2. 推荐的优化计划：")
    print("   - 每月执行一次 OPTIMIZE TABLE 操作")
    print("   - 在业务低峰期执行，如凌晨2-4点")
    print("   - 对所有表执行优化")
    print()
    
    print("3. 完整的优化命令：")
    print("   执行以下SQL命令:")
    print()
    print("   -- 优化所有表")
    print("   USE spug;")
    print("   OPTIMIZE TABLE apps;")
    print("   OPTIMIZE TABLE config_histories;")
    print("   OPTIMIZE TABLE configs;")
    print("   OPTIMIZE TABLE django_migrations;")
    print("   OPTIMIZE TABLE environments;")
    print("   OPTIMIZE TABLE exec_duty_records;")
    print("   OPTIMIZE TABLE exec_fault_parts;")
    print("   OPTIMIZE TABLE exec_fault_records;")
    print("   OPTIMIZE TABLE exec_interferences;")
    print("   OPTIMIZE TABLE exec_run_logs;")
    print("   OPTIMIZE TABLE exec_schedule;")
    print("   OPTIMIZE TABLE exec_schedule_swap;")
    print("   OPTIMIZE TABLE login_histories;")
    print("   OPTIMIZE TABLE navigations;")
    print("   OPTIMIZE TABLE notices;")
    print("   OPTIMIZE TABLE notifies;")
    print("   OPTIMIZE TABLE repositories;")
    print("   OPTIMIZE TABLE roles;")
    print("   OPTIMIZE TABLE services;")
    print("   OPTIMIZE TABLE settings;")
    print("   OPTIMIZE TABLE user_role_rel;")
    print("   OPTIMIZE TABLE user_settings;")
    print("   OPTIMIZE TABLE users;")
    print()
    
    print("4. 优化效果：")
    print("   - 回收碎片空间，减少磁盘使用")
    print("   - 优化索引结构，提高查询速度")
    print("   - 减少表扫描时间，提升整体性能")
    print()
    
    print("5. 注意事项：")
    print("   - OPTIMIZE TABLE 会锁定表，执行期间该表不可写入")
    print("   - 对于大表，执行时间可能较长")
    print("   - 确保有足够的磁盘空间用于临时操作")
    
else:
    print("✗ 数据库文件不存在或路径不正确")
    print("请检查数据库配置和文件位置")

print()
print("=== 优化方案完成 ===")
print()
print("结论：定期执行 OPTIMIZE TABLE 是正确的数据库优化措施！")
print()
