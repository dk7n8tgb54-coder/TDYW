#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MariaDB Backup 还原脚本
使用 mariabackup 恢复数据库
"""

import subprocess
import os
import sys
from pathlib import Path

# ==================== 配置区域 ====================
CONTAINER_NAME = "tdyw-db"  # MariaDB 容器名称
BACKUP_DIR = r"E:\TDYW\spug-3.0\backups\mariabackup"
TEMP_DIR = r"E:\temp\mariadb_restore"

# MariaDB 连接配置
DB_USER = "root"
DB_PASS = "spug.cc"
# =================================================


def log(message):
    """记录日志"""
    print(message)


def run_command(cmd, timeout=300):
    """执行命令"""
    log(f"执行: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        log(f"失败: {result.stderr}")
        return False
    return True


def list_backups():
    """列出所有可用备份"""
    log("=" * 60)
    log("可用备份列表：")
    log("=" * 60)

    backups = sorted(Path(BACKUP_DIR).glob("backup_*.zip"), key=lambda x: x.stat().st_mtime, reverse=True)

    if not backups:
        log("没有找到备份文件")
        sys.exit(1)

    for idx, backup in enumerate(backups, 1):
        size_mb = backup.stat().st_size / (1024 * 1024)
        mtime = backup.stat().st_mtime
        mtime_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        log(f"{idx}. {backup.name} ({size_mb:.2f} MB) - {mtime_str}")

    log("=" * 60)
    return backups


def extract_backup(backup_file, extract_dir):
    """解压备份"""
    log(f"解压备份: {backup_file}")
    os.makedirs(extract_dir, exist_ok=True)

    cmd = [
        "powershell", "-Command",
        f"Expand-Archive -Path '{backup_file}' -DestinationPath '{extract_dir}' -Force"
    ]

    if not run_command(cmd, timeout=600):
        return False

    log(f"✓ 解压完成: {extract_dir}")
    return True


def backup_current_data():
    """备份当前数据（可选，防止恢复失败）"""
    log("=" * 60)
    log("备份当前数据（防止恢复失败）...")
    log("=" * 60)

    current_backup_dir = os.path.join(TEMP_DIR, "current_backup")
    os.makedirs(current_backup_dir, exist_ok=True)

    cmd = ["docker", "cp", f"{CONTAINER_NAME}:/var/lib/mysql", current_backup_dir]

    if run_command(cmd, timeout=600):
        log(f"✓ 当前数据已备份到: {current_backup_dir}")
        return True
    else:
        log("✗ 备份当前数据失败，但继续执行恢复")
        return False


def stop_container():
    """停止容器"""
    log("停止容器...")
    cmd = ["docker", "stop", CONTAINER_NAME]
    return run_command(cmd, timeout=60)


def start_container():
    """启动容器"""
    log("启动容器...")
    cmd = ["docker", "start", CONTAINER_NAME]
    if run_command(cmd, timeout=60):
        log("✓ 容器已启动")
        # 等待容器启动
        log("等待容器启动...")
        import time
        time.sleep(10)
        return True
    return False


def clear_mysql_dir():
    """清空 MySQL 数据目录"""
    log("清空 MySQL 数据目录...")
    cmd = ["docker", "exec", CONTAINER_NAME, "sh", "-c", "rm -rf /var/lib/mysql/*"]
    return run_command(cmd, timeout=60)


def restore_backup(backup_dir):
    """恢复备份"""
    log("=" * 60)
    log("恢复备份...")
    log("=" * 60)

    # 将备份复制到容器
    container_backup = f"/tmp/restore_backup"
    log(f"复制备份到容器: {container_backup}")

    cmd = ["docker", "cp", backup_dir, f"{CONTAINER_NAME}:{container_backup}"]
    if not run_command(cmd, timeout=600):
        return False

    # 执行恢复
    log("执行 mariabackup --copy-back...")
    cmd = [
        "docker", "exec", CONTAINER_NAME,
        "mariabackup", "--copy-back",
        f"--target-dir={container_backup}",
        f"--user={DB_USER}",
        f"--password={DB_PASS}"
    ]

    if not run_command(cmd, timeout=600):
        return False

    log("✓ 数据恢复完成")
    return True


def fix_permissions():
    """修复权限"""
    log("修复文件权限...")
    cmd = ["docker", "exec", CONTAINER_NAME, "chown", "-R", "mysql:mysql", "/var/lib/mysql"]
    return run_command(cmd, timeout=60)


def verify_restore():
    """验证恢复结果"""
    log("=" * 60)
    log("验证恢复结果...")
    log("=" * 60)

    # 检查容器日志
    log("检查容器日志（最近20行）...")
    cmd = ["docker", "logs", "--tail", "20", CONTAINER_NAME]
    subprocess.run(cmd)

    # 连接数据库测试
    log("\n测试数据库连接...")
    cmd = [
        "docker", "exec", CONTAINER_NAME,
        "mysql", f"-u{DB_USER}", f"-p{DB_PASS}",
        "-e", "SHOW DATABASES;"
    ]

    if run_command(cmd, timeout=30):
        log("\n✓ 数据库连接成功，恢复成功！")
        return True
    else:
        log("\n✗ 数据库连接失败，请检查容器日志")
        return False


def cleanup_temp(backup_dir, extract_dir):
    """清理临时文件"""
    log("清理临时文件...")

    # 删除容器内的备份
    container_backup = f"/tmp/restore_backup"
    cmd = ["docker", "exec", CONTAINER_NAME, "rm", "-rf", container_backup]
    subprocess.run(cmd, capture_output=True)

    # 询问是否删除解压的备份
    response = input(f"是否删除解压的备份文件 {extract_dir}？(y/n): ")
    if response.lower() == 'y':
        import shutil
        shutil.rmtree(extract_dir)
        log(f"✓ 已删除: {extract_dir}")


def main():
    """主函数"""
    import datetime

    print("""
╔══════════════════════════════════════════════════════════╗
║         MariaDB Backup 数据库恢复工具                     ║
╚══════════════════════════════════════════════════════════╝
    """)

    # 列出可用备份
    backups = list_backups()

    # 选择备份
    try:
        choice = input("\n请选择要恢复的备份编号: ").strip()
        idx = int(choice) - 1
        if idx < 0 or idx >= len(backups):
            log("无效的选择")
            sys.exit(1)

        backup_file = backups[idx]
        log(f"已选择: {backup_file.name}")
    except ValueError:
        log("无效的输入")
        sys.exit(1)

    # 确认恢复
    log("\n" + "=" * 60)
    log("警告：此操作将覆盖当前数据库！")
    log("=" * 60)
    confirm = input("确认继续恢复？(输入 'yes' 确认): ")
    if confirm.lower() != 'yes':
        log("已取消恢复")
        sys.exit(0)

    # 解压备份
    extract_dir = os.path.join(TEMP_DIR, os.path.splitext(backup_file.name)[0])
    if not extract_backup(backup_file, extract_dir):
        log("✗ 解压备份失败")
        sys.exit(1)

    # 获取解压后的备份目录
    extracted_backup = os.path.join(extract_dir, os.path.splitext(backup_file.name)[0])

    # 备份当前数据
    backup_current_data()

    # 停止容器
    if not stop_container():
        log("✗ 停止容器失败")
        sys.exit(1)

    # 清空数据目录
    if not clear_mysql_dir():
        log("✗ 清空数据目录失败")
        sys.exit(1)

    # 恢复备份
    if not restore_backup(extracted_backup):
        log("✗ 恢复备份失败")
        log("\n尝试重新启动容器...")
        start_container()
        sys.exit(1)

    # 修复权限
    if not fix_permissions():
        log("✗ 修复权限失败")

    # 启动容器
    if not start_container():
        log("✗ 启动容器失败")
        sys.exit(1)

    # 验证恢复
    if verify_restore():
        # 清理临时文件
        cleanup_temp(extracted_backup, extract_dir)
        log("\n" + "=" * 60)
        log("恢复完成！")
        log("=" * 60)
    else:
        log("\n恢复可能失败，请检查容器日志和数据库状态")
        log(f"当前数据备份在: {os.path.join(TEMP_DIR, 'current_backup')}")


if __name__ == "__main__":
    main()
