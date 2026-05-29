# -*- coding: utf-8 -*-
import subprocess
import datetime
import os
import sys

BACKUP_DIR = r"E:\TDYW\spug-3.0\backups"
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
backup_file = os.path.join(BACKUP_DIR, f"spug_backup_{timestamp}.sql")
container_file = f"/tmp/spug_backup_{timestamp}.sql"

print(f"开始备份数据库...")

# 确保备份目录存在
if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

# 在容器内执行 mysqldump
cmd1 = [
    "docker", "exec", "tdyw-db", "sh", "-c",
    f"mysqldump -uroot -p'spug.cc' spug --default-character-set=utf8mb4 --set-charset --skip-add-locks --skip-disable-keys > {container_file}"
]
print("在容器内执行 mysqldump...")
result = subprocess.run(cmd1, capture_output=True, text=True)

if result.returncode != 0:
    print(f"mysqldump 失败: {result.stderr}")
    sys.exit(1)

# 从容器复制文件到本地
cmd2 = ["docker", "cp", f"tdyw-db:{container_file}", backup_file]
print(f"从容器复制文件: {backup_file}")
result = subprocess.run(cmd2, capture_output=True, text=True)

if result.returncode != 0:
    print(f"docker cp 失败: {result.stderr}")
    sys.exit(1)

# 清理容器内的文件
cmd3 = ["docker", "exec", "tdyw-db", "rm", "-f", container_file]
subprocess.run(cmd3, capture_output=True)

# 检查文件
if os.path.exists(backup_file):
    size = os.path.getsize(backup_file) / 1024
    print(f"[OK] 备份成功: {backup_file} ({size:.2f} KB)")

    # 压缩
    zip_file = backup_file + ".zip"
    cmd4 = ["powershell", "-Command", f"Compress-Archive -Path '{backup_file}' -DestinationPath '{zip_file}' -Force; Remove-Item '{backup_file}' -Force"]
    subprocess.run(cmd4, capture_output=True)

    print(f"[OK] 压缩完成: {zip_file}")
    print("备份完成！")
else:
    print("备份失败")
    sys.exit(1)
