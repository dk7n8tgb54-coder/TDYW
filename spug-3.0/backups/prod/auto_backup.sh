#!/bin/bash

# ============================================================================
# Spug 生产环境自动备份脚本（加密）
# 使用方法: ./prod/auto_backup.sh
# 建议添加到crontab每天执行: 0 2 * * * /path/to/prod/auto_backup.sh
# ============================================================================

set -e  # 遇到错误立即退出

# ==================== 配置区域 ====================

# 数据库配置
DB_CONTAINER="spug-db-prod"
DB_NAME="spug"
DB_USER="spug"
DB_PASS="${MYSQL_PASSWORD:-spug.cc}"
DB_HOST="localhost"
DB_PORT="3306"

# 备份文件保存目录
BACKUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/backups"
mkdir -p "$BACKUP_DIR"

# 保留最近多少天的备份（生产环境建议30天）
RETENTION_DAYS=30

# 加密配置
ENCRYPT=true
ENCRYPT_METHOD="openssl"
ENCRYPT_PASSWORD="${BACKUP_ENCRYPT_PASSWORD:-your_secure_password_change_me}"

# 日志文件
LOG_FILE="${BACKUP_DIR}/auto_backup.log"

# 异地备份配置（可选）
REMOTE_BACKUP_ENABLED=false
REMOTE_HOST="192.168.1.200"
REMOTE_USER="backup"
REMOTE_DIR="/data/spug_backups"

# ==================== 函数定义 ====================

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

send_alert() {
    local message="$1"
    log "⚠ 警告: $message"
    # 这里可以集成邮件、钉钉、企业微信等告警
    # 例如: curl -X POST "钉钉webhook" -d "{\"text\":\"$message\"}"
}

encrypt_openssl() {
    local input_file="$1"
    local output_file="${input_file}.enc"
    openssl enc -aes-256-cbc -salt -in "$input_file" -out "$output_file" -k "$ENCRYPT_PASSWORD" 2>> "$LOG_FILE"
    if [ $? -eq 0 ]; then
        rm -f "$input_file"
        return 0
    fi
    return 1
}

compress_backup() {
    local input_file="$1"
    local output_file="${input_file}.gz"
    gzip -c "$input_file" > "$output_file" 2>> "$LOG_FILE"
    if [ $? -eq 0 ]; then
        rm -f "$input_file"
        return 0
    fi
    return 1
}

remote_backup() {
    local backup_file="$1"
    log "开始传输备份到远程服务器..."
    
    # 使用scp传输
    scp "$backup_file" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/" >> "$LOG_FILE" 2>&1
    
    if [ $? -eq 0 ]; then
        log "✓ 远程备份传输成功"
        return 0
    else
        log "✗ 远程备份传输失败!"
        send_alert "生产环境远程备份失败: $backup_file"
        return 1
    fi
}

# ==================== 备份流程 ====================

log "========================================="
log "Spug 生产环境自动备份开始"
log "========================================="

# 检查数据库容器
if ! docker ps | grep -q "$DB_CONTAINER"; then
    log "✗ 数据库容器 $DB_CONTAINER 未运行!"
    send_alert "生产环境数据库容器未运行，备份失败!"
    exit 1
fi

log "✓ 数据库容器运行正常"

# 获取当前日期
TODAY=$(date +"%Y%m%d")
BACKUP_FILE="${BACKUP_DIR}/spug_prod_auto_${TODAY}.sql"

# 执行备份
log "开始备份数据库: $DB_NAME"
docker exec "$DB_CONTAINER" mysqldump -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USER" -p"$DB_PASS" \
    --single-transaction \
    --routines \
    --triggers \
    --events \
    --databases "$DB_NAME" > "$BACKUP_FILE" 2>> "$LOG_FILE"

if [ $? -ne 0 ]; then
    log "✗ 数据库备份失败!"
    rm -f "$BACKUP_FILE"
    send_alert "生产环境数据库备份失败!"
    exit 1
fi

log "✓ 数据库备份成功"
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
log "  文件大小: $BACKUP_SIZE"

# 压缩
if ! compress_backup "$BACKUP_FILE"; then
    log "✗ 压缩失败!"
    send_alert "生产环境备份压缩失败!"
    exit 1
fi
log "✓ 压缩成功"
COMPRESSED_FILE="${BACKUP_FILE}.gz"

# 加密
if [ "$ENCRYPT" = true ]; then
    if [ "$ENCRYPT_METHOD" = "openssl" ]; then
        if encrypt_openssl "$COMPRESSED_FILE"; then
            log "✓ OpenSSL加密成功"
        else
            log "✗ OpenSSL加密失败!"
            send_alert "生产环境备份加密失败!"
            exit 1
        fi
    fi
fi

# 远程备份（可选）
if [ "$REMOTE_BACKUP_ENABLED" = true ]; then
    remote_backup "${COMPRESSED_FILE}.enc"
fi

# 清理旧备份
log ""
log "清理超过 $RETENTION_DAYS 天的旧备份..."
DELETED=0

if [ "$ENCRYPT" = true ]; then
    DELETED=$(find "$BACKUP_DIR" -name "spug_prod_auto_*.sql.gz.enc" -mtime +$RETENTION_DAYS -delete -print 2>/dev/null | wc -l)
else
    DELETED=$(find "$BACKUP_DIR" -name "spug_prod_auto_*.sql.gz" -mtime +$RETENTION_DAYS -delete -print 2>/dev/null | wc -l)
fi

log "✓ 已删除 $DELETED 个旧备份文件"

# 统计当前备份
log ""
log "当前备份文件:"
BACKUP_COUNT=$(find "$BACKUP_DIR" -name "spug_prod_auto_*" | wc -l)
TOTAL_SIZE=$(du -sh "$BACKUP_DIR"/spug_prod_auto_* 2>/dev/null | cut -f1)
log "  备份文件数: $BACKUP_COUNT"
log "  总大小: $TOTAL_SIZE"

log ""
log "========================================="
log "✓ 生产环境自动备份完成!"
log "========================================="

# 验证备份文件
FINAL_BACKUP=$(find "$BACKUP_DIR" -name "spug_prod_auto_*.sql.gz.enc" -newer "$BACKUP_DIR/auto_backup.log" 2>/dev/null | head -1)
if [ -n "$FINAL_BACKUP" ]; then
    SIZE=$(du -b "$FINAL_BACKUP" | cut -f1)
    if [ "$SIZE" -lt 1024 ]; then
        log "⚠ 警告: 备份文件太小 ($SIZE bytes)，可能备份失败!"
        send_alert "生产环境备份文件异常小，请检查!"
    else
        log "✓ 备份文件验证通过: $SIZE bytes"
    fi
else
    log "⚠ 警告: 未找到今天的备份文件!"
    send_alert "生产环境今日备份文件未生成!"
fi
