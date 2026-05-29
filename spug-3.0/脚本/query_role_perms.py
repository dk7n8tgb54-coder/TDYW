#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json

# 直接查询MySQL数据库
import pymysql

# 数据库连接配置
db_config = {
    'host': 'localhost',
    'port': 3306,
    'user': 'spug',
    'password': 'spug@2024',
    'database': 'spug',
    'charset': 'utf8mb4'
}

try:
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # 查询通信科角色
    cursor.execute("SELECT id, name, page_perms FROM roles WHERE name = %s", ('通信科',))
    role = cursor.fetchone()

    if role:
        print(f"=== 角色: {role['name']} ===")
        print(f"角色ID: {role['id']}")
        print(f"\npage_perms 原始数据:")
        print(role['page_perms'])

        if role['page_perms']:
            print(f"\npage_perms 解析后:")
            try:
                perms = json.loads(role['page_perms'])
                print(json.dumps(perms, indent=2, ensure_ascii=False))
            except Exception as e:
                print(f"解析失败: {e}")
        else:
            print("page_perms 为空")

    else:
        print("未找到通信科角色")

    cursor.close()
    conn.close()

except Exception as e:
    print(f"数据库连接失败: {e}")
