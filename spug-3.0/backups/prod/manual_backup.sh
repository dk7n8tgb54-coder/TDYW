#!/bin/bash

# ============================================================================
# Spug 生产环境手动备份脚本（加密）
# 版本: 1.0.0
# 日期: 2026-02-16
# 使用方法: ./prod/manual_backup.sh
# ============================================================================

set -e  # 遇到错误立即退出

# ==================== 版本信息 ====================
SCRIPT_VERSION="1.0.0"
SCRIPT_DATE="2026-02-16"

# ==================== 安全配置 ====================

# 确保脚本权限正确
chmod 700 "$0" 2>/dev/null || true

# 确保备份目录权限正确
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="${SCRIPT_DIR}/backups"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR" 2>/dev/null || true

# ==================== 配置加载 ====================

# 加载配置文件
CONFIG_FILE="${SCRIPT_DIR}/backup_config.sh"
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE" 2>/dev/null || true
else
    echo "错误: 配置文件不存在: $CONFIG_FILE"
    exit 1
fi

# 数据库配置
DB_HOST="localhost"
DB_PORT="3306"

# 强制使用环境变量中的密码，避免默认值
if [ -z "$MYSQL_PASSWORD" ]; then
    echo "错误: 必须设置 MYSQL_PASSWORD 环境变量"
    exit 1
fi
DB_PASS="$MYSQL_PASSWORD"

# 强制使用环境变量中的密码，避免默认值
if [ -z "$BACKUP_ENCRYPT_PASSWORD" ]; then
    echo "错误: 必须设置 BACKUP_ENCRYPT_PASSWORD 环境变量"
    exit 1
fi
ENCRYPT_PASSWORD="$BACKUP_ENCRYPT_PASSWORD"

# 备份文件名（包含时间戳）
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/spug_prod_backup_${TIMESTAMP}.sql"

# 密码安全处理（确保密码不会出现在进程列表中）
export MYSQL_PWD="$DB_PASS"
# 清空密码变量，避免在脚本中意外泄露
unset DB_PASS

# ==================== 函数定义 ====================

# 检查磁盘空间
check_disk_space() {
    local required_space_mb=500  # 至少需要500MB空间
    local available_space=$(df -m "$BACKUP_DIR" | tail -1 | awk '{print $4}')
    
    if [ "$available_space" -lt "$required_space_mb" ]; then
        echo "✗ 磁盘空间不足!"
        echo "  可用空间: ${available_space}MB, 所需空间: ${required_space_mb}MB"
        return 1
    fi
    
    echo "✓ 磁盘空间检查通过"
    echo "  可用空间: ${available_space}MB"
    return 0
}

# 检查数据库健康状态
check_db_health() {
    echo "开始检查数据库健康状态..."
    
    # 检查数据库容器是否运行
    if ! docker ps | grep -q "$DB_CONTAINER"; then
        echo "✗ 数据库容器 $DB_CONTAINER 未运行!"
        echo "请使用: docker-compose -f docker-compose.prod.yml up -d"
        return 1
    fi
    
    # 检查数据库是否可访问
    docker exec -e MYSQL_PWD="$MYSQL_PWD" "$DB_CONTAINER" mysql -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USER" -e "SELECT 1" > /dev/null
    if [ $? -ne 0 ]; then
        echo "✗ 数据库连接失败!"
        return 1
    fi
    
    # 检查数据库大小
    local db_size=$(docker exec -e MYSQL_PWD="$MYSQL_PWD" "$DB_CONTAINER" mysql -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USER" -e "SELECT table_schema AS 'Database', ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) AS 'Size (MB)' FROM information_schema.TABLES WHERE table_schema = '$DB_NAME' GROUP BY table_schema;" | tail -1 | awk '{print $2}')
    if [ -n "$db_size" ]; then
        echo "✓ 数据库健康检查通过"
        echo "  数据库大小: ${db_size}MB"
    else
        echo "⚠ 数据库大小检查失败，但继续执行备份"
    fi
    
    return 0
}

# 重试函数
retry() {
    local command="$1"
    local max_attempts=3
    local attempt=1
    local delay=5
    
    while [ $attempt -le $max_attempts ]; do
        echo "尝试执行: $command (尝试 $attempt/$max_attempts)"
        eval "$command"
        if [ $? -eq 0 ]; then
            echo "✓ 执行成功"
            return 0
        fi
        echo "✗ 执行失败，等待 $delay 秒后重试..."
        sleep $delay
        attempt=$((attempt + 1))
    done
    
    echo "✗ 执行失败，已达到最大重试次数"
    return 1
}

# 验证备份文件完整性
verify_backup() {
    local backup_file="$1"
    
    # 检查文件是否存在
    if [ ! -f "$backup_file" ]; then
        echo "✗ 备份文件不存在: $backup_file"
        return 1
    fi
    
    # 检查文件大小
    local file_size=$(du -b "$backup_file" | cut -f1)
    if [ "$file_size" -lt 1024 ]; then
        echo "✗ 备份文件太小 ($file_size bytes)，可能备份失败!"
        return 1
    fi
    
    # 计算并记录文件哈希值
    local file_hash=$(md5sum "$backup_file" 2>/dev/null || md5 "$backup_file" 2>/dev/null | cut -d' ' -f1)
    if [ -n "$file_hash" ]; then
        echo "✓ 备份文件验证通过"
        echo "  文件大小: $(du -h "$backup_file" | cut -f1)"
        echo "  文件哈希: $file_hash"
    else
        echo "⚠ 无法计算文件哈希值，但文件存在且大小正常"
    fi
    
    return 0
}

encrypt_openssl() {
    local input_file="$1"
    local output_file="${input_file}.enc"
    openssl enc -aes-256-cbc -salt -in "$input_file" -out "$output_file" -k "$ENCRYPT_PASSWORD"
    if [ $? -eq 0 ]; then
        rm -f "$input_file"
        return 0
    fi
    return 1
}

compress_backup() {
    local input_file="$1"
    local output_file="${input_file}.gz"
    gzip -c "$input_file" > "$output_file"
    if [ $? -eq 0 ]; then
        rm -f "$input_file"
        return 0
    fi
    return 1
}

# ==================== 备份流程 ====================

echo "========================================="
echo "Spug 生产环境数据库手动备份"
echo "备份时间: $(date +'%Y-%m-%d %H:%M:%S')"
echo "版本: $SCRIPT_VERSION"
echo "配置文件: $CONFIG_FILE"
echo "备份目录: $BACKUP_DIR"
echo "========================================="

# 检查磁盘空间
if ! check_disk_space; then
    exit 1
fi

# 检查数据库健康状态
if ! check_db_health; then
    exit 1
fi

# 执行数据库备份（使用重试机制）
echo ""
echo "开始备份数据库: $DB_NAME"
retry "docker exec -e MYSQL_PWD=\"$MYSQL_PWD\" \"$DB_CONTAINER\" mysqldump -h\"$DB_HOST\" -P\"$DB_PORT\" -u\"$DB_USER\" \
    --single-transaction \
    --routines \
    --triggers \
    --events \
    --databases \"$DB_NAME\" > \"$BACKUP_FILE\""

if [ $? -eq 0 ]; then
    echo "✓ 数据库备份成功"
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "  文件大小: $BACKUP_SIZE"
else
    echo "✗ 数据库备份失败!"
    rm -f "$BACKUP_FILE"
    exit 1
fi

# 压缩备份文件（使用重试机制）
echo ""
echo "正在压缩备份文件..."
if ! retry "compress_backup \"$BACKUP_FILE\""; then
    echo "✗ 压缩失败!"
    exit 1
fi
COMPRESSED_FILE="${BACKUP_FILE}.gz"
echo "✓ 压缩成功: $COMPRESSED_FILE"
echo "  压缩大小: $(du -h "$COMPRESSED_FILE" | cut -f1)"

# 加密备份文件（使用重试机制）
if [ "$ENCRYPT" = true ]; then
    if [ "$ENCRYPT_METHOD" = "openssl" ]; then
        echo ""
        echo "正在使用OpenSSL加密备份文件..."
        if ! retry "encrypt_openssl \"$COMPRESSED_FILE\""; then
            echo "✗ 加密失败!"
            exit 1
        fi
        echo "✓ 加密成功: ${COMPRESSED_FILE}.enc"
    elif [ "$ENCRYPT_METHOD" = "gpg" ]; then
        echo ""
        echo "正在使用GPG加密备份文件..."
        if ! retry "encrypt_gpg \"$COMPRESSED_FILE\""; then
            echo "✗ 加密失败!"
            exit 1
        fi
    fi
fi

# 验证备份文件完整性
FINAL_BACKUP=$(find "$BACKUP_DIR" -name "spug_prod_backup_*.sql.gz.enc" -type f -exec ls -t {} \; 2>/dev/null | head -1)
if [ -n "$FINAL_BACKUP" ]; then
    echo ""
    if ! verify_backup "$FINAL_BACKUP"; then
        exit 1
    fi
else
    echo ""
    echo "⚠ 警告: 未找到备份文件!"
    exit 1
fi

# 显示备份文件列表
echo ""
echo "备份完成!"
echo "备份文件列表:"
ls -lh "$BACKUP_DIR"/spug_prod_backup_* | tail -10

echo ""
echo "========================================="
echo "✓ 生产环境手动备份完成!"
echo "========================================="

# 显示恢复提示
if [ "$ENCRYPT" = true ]; then
    echo ""
    echo "恢复备份命令:"
    if [ "$ENCRYPT_METHOD" = "openssl" ]; then
        FINAL_FILE="${BACKUP_FILE}.gz.enc"
        echo "openssl enc -aes-256-cbc -d -in $FINAL_FILE -k \$BACKUP_ENCRYPT_PASSWORD | gunzip | docker exec -e MYSQL_PWD=\"\$MYSQL_PASSWORD\" $DB_CONTAINER mysql -u$DB_USER $DB_NAME"
    fi
else
    echo ""
    echo "恢复备份命令:"
    echo "gunzip -c ${BACKUP_FILE}.gz | docker exec -e MYSQL_PWD=\"\$MYSQL_PASSWORD\" $DB_CONTAINER mysql -u$DB_USER $DB_NAME"
fi

# 清理函数
cleanup() {
    # 清理环境变量中的敏感信息
    unset MYSQL_PWD
    unset BACKUP_ENCRYPT_PASSWORD
}

# 清理敏感信息
cleanup
