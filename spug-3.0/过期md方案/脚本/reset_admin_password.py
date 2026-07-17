#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
重置 admin 用户密码为 'spug'
"""
import pymysql
from django.contrib.auth.hashers import make_password

def reset_admin_password():
    """重置 admin 密码"""
    db_config = {
        'host': 'localhost',
        'port': 3306,
        'user': 'spug',
        'password': 'spug.cc',
        'database': 'spug',
        'charset': 'utf8mb4'
    }

    # Django pbkdf2_sha256 密码哈希
    password = 'spug'
    password_hash = make_password(password, hasher='pbkdf2_sha256')

    print("=" * 80)
    print("重置 admin 用户密码")
    print("=" * 80)
    print(f"新密码: {password}")
    print(f"密码哈希: {password_hash[:80]}...")

    connection = None
    cursor = None

    try:
        connection = pymysql.connect(**db_config)
        cursor = connection.cursor()

        # 更新密码
        update_sql = "UPDATE users SET password_hash = %s WHERE username = 'admin'"
        cursor.execute(update_sql, (password_hash,))
        connection.commit()

        print(f"\n✓ 密码更新成功!")
        print(f"  影响行数: {cursor.rowcount}")

        # 验证更新
        cursor.execute("SELECT username, password_hash FROM users WHERE username = 'admin'")
        result = cursor.fetchone()
        print(f"  用户名: {result[0]}")
        print(f"  密码哈希: {result[1][:80]}...")

    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


if __name__ == '__main__':
    reset_admin_password()
