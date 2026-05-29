#!/bin/bash
# -*- coding: utf-8 -*-
#
# Spug 资料库模块 Linux 恢复脚本
# 功能：从备份恢复 MySQL 数据库 + 存储文件
#

set -e

# ============================================
# 配置参数
# ============================================
BACKUP_DIR="/data/backups/spug"
SPUG_ROOT="/data/spug"
DB_CONTAINER="spug-db"
DB_NAME="spug"
DB_USER="root"

# ============================================
# 显示帮助
# ============================================
show_help() {
    cat << EOF
Spug 恢复脚本

用法: $0 <备份文件路径>

示例:
  $0 /data/backups/spug/spug_backup_20250330_120000.tar.gz

注意:
  1. 恢复前请确保 Docker 容器正在运行
  2. 恢复会覆盖现有数据，请谨慎操作
  3. 建议先备份当前数据

EOF
}

# ============================================
# 检查参数
# ============================================
if [ $# -eq 0 ] || [ "$1" == "-h" ] || [ "$1" == "--help" ]; then
    show_help
    exit 0
fi

BACKUP_FILE="$1"

if [ ! -f "${BACKUP_FILE}" ]; then
    echo "[ERROR] 备份文件不存在: ${BACKUP_FILE}"
    exit 1
fi

echo "========================================"
echo "Spug 恢复脚本"
echo "备份文件: ${BACKUP_FILE}"
echo "开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# 确认
read -p "⚠️  恢复将覆盖现有数据，是否继续? [y/N] " confirm
if [[ ! $confirm =~ ^[Yy]$ ]]; then
    echo "已取消恢复操作"
    exit 0
fi

# ============================================
# 解压备份
# ============================================
echo ""
echo "[1/4] 解压备份文件..."

RESTORE_TMP="/tmp/spug_restore_$$"
mkdir -p "${RESTORE_TMP}"

tar xzf "${BACKUP_FILE}" -C "${RESTORE_TMP}"

# 找到解压后的目录
BACKUP_NAME=$(ls "${RESTORE_TMP}")
BACKUP_PATH="${RESTORE_TMP}/${BACKUP_NAME}"

echo "[OK] 备份已解压到: ${BACKUP_PATH}"

# ============================================
# 检查备份内容
# ============================================
echo ""
echo "[2/4] 检查备份内容..."

if [ ! -f "${BACKUP_PATH}/database.sql" ]; then
    echo "[ERROR] 备份中缺少数据库文件 (database.sql)"
    rm -rf "${RESTORE_TMP}"
    exit 1
fi

echo "[OK] 备份内容检查通过"
ls -lh "${BACKUP_PATH}/"

# ============================================
# 恢复数据库
# ============================================
echo ""
echo "[3/4] 恢复数据库..."

# 检查容器是否运行
if ! docker ps | grep -q "${DB_CONTAINER}"; then
    echo "[ERROR] MySQL 容器未运行: ${DB_CONTAINER}"
    rm -rf "${RESTORE_TMP}"
    exit 1
fi

# 复制 SQL 文件到容器
CONTAINER_SQL="/tmp/restore_$$.sql"
docker cp "${BACKUP_PATH}/database.sql" "${DB_CONTAINER}:${CONTAINER_SQL}"

# 在容器内执行恢复
read -sp "请输入数据库密码: " DB_PASSWORD
echo ""

echo "正在导入数据库，请稍候..."
docker exec "${DB_CONTAINER}" sh -c "
    mysql -u${DB_USER} -p'${DB_PASSWORD}' ${DB_NAME} < ${CONTAINER_SQL} 2>&1
"

if [ $? -ne 0 ]; then
    echo "[ERROR] 数据库恢复失败"
    docker exec "${DB_CONTAINER}" rm -f "${CONTAINER_SQL}"
    rm -rf "${RESTORE_TMP}"
    exit 1
fi

# 清理容器内临时文件
docker exec "${DB_CONTAINER}" rm -f "${CONTAINER_SQL}"

echo "[OK] 数据库恢复完成"

# ============================================
# 恢复存储文件
# ============================================
echo ""
echo "[4/4] 恢复存储文件..."

STORAGE_DIR="${SPUG_ROOT}/spug_api/storage"
mkdir -p "${STORAGE_DIR}"

# 恢复文档文件
if [ -f "${BACKUP_PATH}/documents.tar.gz" ]; then
    echo "  - 恢复文档文件..."
    tar xzf "${BACKUP_PATH}/documents.tar.gz" -C "${STORAGE_DIR}/"
    echo "  [OK] 文档文件恢复完成"
fi

# 恢复传输分片
if [ -f "${BACKUP_PATH}/chunks.tar.gz" ]; then
    echo "  - 恢复传输分片..."
    tar xzf "${BACKUP_PATH}/chunks.tar.gz" -C "${STORAGE_DIR}/"
    echo "  [OK] 传输分片恢复完成"
fi

# 恢复任务文件
if [ -f "${BACKUP_PATH}/merge_tasks.tar.gz" ]; then
    echo "  - 恢复任务文件..."
    tar xzf "${BACKUP_PATH}/merge_tasks.tar.gz" -C "${STORAGE_DIR}/"
    echo "  [OK] 任务文件恢复完成"
fi

# 设置权限
chown -R 1000:1000 "${STORAGE_DIR}" 2>/dev/null || true

echo "[OK] 存储文件恢复完成"

# ============================================
# 清理临时文件
# ============================================
echo ""
echo "清理临时文件..."
rm -rf "${RESTORE_TMP}"
echo "[OK] 临时文件已清理"

# ============================================
# 恢复完成
# ============================================
echo ""
echo "========================================"
echo "✅ 恢复完成!"
echo "完成时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
echo "请检查:"
echo "  1. 登录系统验证数据完整性"
echo "  2. 测试文件上传下载功能"
echo "  3. 检查回收站数据是否正常"
echo "========================================"

exit 0
