#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MariaDB Backup 定时备份脚本
使用 mariabackup 进行物理备份（热备份，不锁表）
"""

import subprocess
import datetime
import os
import sys
import shutil
from pathlib import Path

# ==================== 配置区域 ====================
# Docker 配置
CONTAINER_NAME = "tdyw-db"  # MariaDB 容器名称

# 备份配置
BACKUP_DIR = r"E:\TDYW\spug-3.0\backups\mariabackup"
RETENTION_DAYS = 7  # 保留最近7天的备份

# MariaDB 连接配置
DB_USER = "root"
DB_PASS = "spug.cc"
DB_NAME = "spug"

# 日志配置
LOG_FILE = os.path.join(BACKUP_DIR, "backup.log")
# =================================================


def log(message):
    """记录日志"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    print(log_line)
    # 确保日志目录存在
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_line + "\n")


def cleanup_old_backups():
    """清理过期备份"""
    log("开始清理过期备份...")
    now = datetime.datetime.now()

    for backup_path in Path(BACKUP_DIR).glob("backup_*"):
        try:
            if backup_path.is_dir():
                # 获取目录修改时间
                mod_time = datetime.datetime.fromtimestamp(backup_path.stat().st_mtime)
                days_old = (now - mod_time).days

                if days_old > RETENTION_DAYS:
                    log(f"删除过期备份: {backup_path.name} ({days_old}天)")
                    shutil.rmtree(backup_path)
        except Exception as e:
            log(f"清理备份失败 {backup_path}: {e}")

    log(f"清理完成，保留最近{RETENTION_DAYS}天的备份")


def check_mariabackup():
    """检查 mariabackup 是否可用"""
    log("检查 mariabackup 是否可用...")
    try:
        result = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "which", "mariabackup"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0 and "/mariabackup" in result.stdout:
            log("✓ mariabackup 可用")
            return True
        else:
            log("✗ mariabackup 不可用，尝试安装...")
            return install_mariabackup()
    except Exception as e:
        log(f"检查 mariabackup 失败: {e}")
        return False


def install_mariabackup():
    """安装 mariabackup"""
    log("尝试在容器内安装 mariabackup...")

    # 检测发行版
    check_dist_cmd = ["docker", "exec", CONTAINER_NAME, "sh", "-c", "cat /etc/os-release | grep '^ID=' | cut -d'=' -f2 | tr -d '\"'"]
    result = subprocess.run(check_dist_cmd, capture_output=True, text=True, timeout=10)

    if result.returncode != 0:
        log("✗ 无法检测发行版")
        return False

    distro = result.stdout.strip().lower()

    # 根据发行版安装
    install_commands = {
        "ubuntu": ["docker", "exec", CONTAINER_NAME, "sh", "-c", "apt-get update && apt-get install -y mariadb-backup"],
        "debian": ["docker", "exec", CONTAINER_NAME, "sh", "-c", "apt-get update && apt-get install -y mariadb-backup"],
        "centos": ["docker", "exec", CONTAINER_NAME, "sh", "-c", "yum install -y MariaDB-backup"],
        "rhel": ["docker", "exec", CONTAINER_NAME, "sh", "-c", "yum install -y MariaDB-backup"],
        "alpine": ["docker", "exec", CONTAINER_NAME, "sh", "-c", "apk add --no-cache mariadb-backup"],
    }

    install_cmd = install_commands.get(distro)
    if not install_cmd:
        log(f"✗ 不支持的发行版: {distro}")
        return False

    log(f"检测到发行版: {distro}，开始安装 mariadb-backup...")
    result = subprocess.run(install_cmd, capture_output=True, text=True, timeout=300)

    if result.returncode == 0:
        log("✓ mariabackup 安装成功")
        return True
    else:
        log(f"✗ mariabackup 安装失败: {result.stderr}")
        return False


def create_backup():
    """使用 mariabackup 创建备份"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{timestamp}"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    container_backup_path = f"/tmp/{backup_name}"

    log(f"开始备份: {backup_name}")

    # 1. 执行 mariabackup
    log("执行 mariabackup --backup ...")
    backup_cmd = [
        "docker", "exec", CONTAINER_NAME,
        "mariabackup", "--backup",
        f"--target-dir={container_backup_path}",
        f"--user={DB_USER}",
        f"--password={DB_PASS}"
    ]

    result = subprocess.run(backup_cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        log(f"✗ mariabackup 失败: {result.stderr}")
        return False

    log("✓ 备份完成")

    # 2. 准备备份（prepare）
    log("执行 mariabackup --prepare ...")
    prepare_cmd = [
        "docker", "exec", CONTAINER_NAME,
        "mariabackup", "--prepare",
        f"--target-dir={container_backup_path}",
        f"--user={DB_USER}",
        f"--password={DB_PASS}"
    ]

    result = subprocess.run(prepare_cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        log(f"✗ prepare 失败: {result.stderr}")
        return False

    log("✓ 备份准备完成")

    # 3. 将备份从容器复制到宿主机
    log(f"复制备份到: {backup_path}")
    copy_cmd = ["docker", "cp", f"{CONTAINER_NAME}:{container_backup_path}", backup_path]

    result = subprocess.run(copy_cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        log(f"✗ 复制备份失败: {result.stderr}")
        return False

    log("✓ 备份复制完成")

    # 4. 清理容器内临时备份
    log("清理容器内临时文件...")
    cleanup_cmd = ["docker", "exec", CONTAINER_NAME, "rm", "-rf", container_backup_path]
    subprocess.run(cleanup_cmd, capture_output=True)

    # 5. 压缩备份
    log(f"压缩备份...")
    zip_path = backup_path + ".zip"
    zip_cmd = [
        "powershell", "-Command",
        f"Compress-Archive -Path '{backup_path}' -DestinationPath '{zip_path}' -Force"
    ]

    result = subprocess.run(zip_cmd, capture_output=True, text=True, timeout=300)

    if result.returncode == 0:
        # 删除未压缩的备份
        shutil.rmtree(backup_path)
        backup_size = os.path.getsize(zip_path) / (1024 * 1024)
        log(f"✓ 备份压缩完成: {zip_path} ({backup_size:.2f} MB)")
        return True
    else:
        log(f"✗ 压缩失败: {result.stderr}")
        return False


def main():
    """主函数"""
    start_time = datetime.datetime.now()
    log("=" * 60)
    log("MariaDB Backup 定时备份开始")
    log("=" * 60)

    # 确保备份目录存在
    os.makedirs(BACKUP_DIR, exist_ok=True)

    # 检查 mariabackup
    if not check_mariabackup():
        log("✗ 无法使用 mariabackup，退出")
        sys.exit(1)

    # 创建备份
    if not create_backup():
        log("✗ 备份失败，退出")
        sys.exit(1)

    # 清理过期备份
    cleanup_old_backups()

    # 完成
    elapsed = (datetime.datetime.now() - start_time).total_seconds()
    log(f"✓ 备份成功完成，耗时: {elapsed:.1f}秒")
    log("=" * 60)


if __name__ == "__main__":
    main()
